"""
Skill natif : interroger les données importées de façon EXACTE.

La recherche sémantique retrouve ce qui ressemble. Elle ne sait pas compter.
« Combien de chantiers à Arcachon », « le total des devis signés » : approximer
une réponse chiffrée, c'est la donner fausse, et rien dans la réponse ne signale
qu'elle l'est. Ces questions doivent taper sur les colonnes d'origine, conservées
à l'import dans `document_metadata`.

Trois usages, du plus général au plus précis :
  * sans argument            -> quels jeux de données existent, et quelles colonnes
  * `source_type` seul       -> les valeurs les plus fréquentes de chaque colonne
  * `source_type` + `filtres` -> le compte exact et les enregistrements

Le cloisonnement par rôle est appliqué comme partout ailleurs : on ne compte que
ce que la personne aurait le droit de lire.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.skills.donnees")

MAX_ENREGISTREMENTS = 25
MAX_VALEURS_DISTINCTES = 12
MAX_COLONNES = 30


async def interroger_donnees(data: dict, user) -> dict:
    """Compte et filtre sur les colonnes importées. Aucun embedding, aucun seuil."""
    from database.connection import get_db
    from security.acces import niveaux_visibles

    niveaux = sorted(niveaux_visibles(getattr(user, "role", "")))
    type_source = (data.get("source_type") or "").strip()
    filtres = data.get("filtres") or {}
    if isinstance(filtres, str):
        import json
        try:
            filtres = json.loads(filtres)
        except json.JSONDecodeError:
            filtres = {}
    if not isinstance(filtres, dict):
        filtres = {}

    try:
        async with get_db() as conn:
            if not type_source:
                return await _catalogue(conn, niveaux)
            if not filtres:
                return await _colonnes(conn, niveaux, type_source)
            return await _filtrer(conn, niveaux, type_source, filtres)
    except Exception as e:  # noqa: BLE001 - une lecture ratée n'est pas une panne du chat
        logger.warning("Interrogation des données impossible : %s", e)
        return {"message": "Les données importées sont momentanément indisponibles."}


async def _catalogue(conn, niveaux: list[str]) -> dict:
    """Quels jeux de données existent, et combien d'enregistrements chacun."""
    lignes = await conn.fetch(
        "SELECT source_type, COUNT(*) AS n FROM document_metadata "
        "WHERE access_level = ANY($1::text[]) "
        "GROUP BY source_type ORDER BY n DESC LIMIT 30", niveaux)
    if not lignes:
        return {"jeux_de_donnees": [], "message":
                "Aucune donnée structurée n'a encore été importée. Seuls les documents "
                "et les mails sont consultables, par la recherche."}
    return {
        "jeux_de_donnees": [{"source_type": l["source_type"], "enregistrements": l["n"]}
                            for l in lignes],
        "note": "Rappelle `interroger_donnees` avec un `source_type` pour voir ses colonnes.",
    }


async def _colonnes(conn, niveaux: list[str], type_source: str) -> dict:
    """Colonnes disponibles et valeurs les plus fréquentes — de quoi filtrer juste.

    Sans cette étape, le modèle devine des noms de colonnes et des orthographes
    de valeurs, et un filtre qui ne correspond à rien rend « 0 » : un zéro faux
    est indiscernable d'un vrai.
    """
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM document_metadata "
        "WHERE source_type = $1 AND access_level = ANY($2::text[])",
        type_source, niveaux)
    if not total:
        return {"source_type": type_source, "enregistrements": 0,
                "message": f"Aucun enregistrement « {type_source} » visible à ce profil."}

    lignes = await conn.fetch(
        "SELECT cle, valeur, COUNT(*) AS n FROM ("
        "  SELECT d.key AS cle, d.value AS valeur FROM document_metadata m,"
        "         jsonb_each_text(m.data) AS d"
        "  WHERE m.source_type = $1 AND m.access_level = ANY($2::text[])"
        ") t GROUP BY cle, valeur ORDER BY cle, n DESC", type_source, niveaux)

    colonnes: dict[str, list] = {}
    for l in lignes:
        vals = colonnes.setdefault(l["cle"], [])
        if len(vals) < MAX_VALEURS_DISTINCTES:
            vals.append({"valeur": l["valeur"], "n": l["n"]})

    # Vocabulaire commun réellement rempli pour ce type : c'est celui-là qu'il
    # faut privilégier, parce qu'il est le même d'un export à l'autre.
    from ingestion.schema import champs_de
    communs = await conn.fetch(
        "SELECT DISTINCT d.key AS cle FROM document_metadata m, "
        "       jsonb_each_text(m.champs) AS d "
        "WHERE m.source_type = $1 AND m.access_level = ANY($2::text[])",
        type_source, niveaux)
    connus = champs_de(type_source)

    return {
        "source_type": type_source, "enregistrements": total,
        "champs_communs": [{"nom": l["cle"], "sens": connus.get(l["cle"], "")}
                           for l in communs],
        "colonnes": [{"nom": c, "valeurs_frequentes": v}
                     for c, v in list(colonnes.items())[:MAX_COLONNES]],
        "note": ("Valeurs les plus fréquentes seulement, pas la liste complète. "
                 "Filtre de préférence sur `champs_communs` : ils portent le même nom "
                 "quel que soit le fichier d'origine. Les `colonnes` sont les entêtes "
                 "brutes du fichier. Rappelle avec `filtres` pour un compte exact."),
    }


async def _filtrer(conn, niveaux: list[str], type_source: str, filtres: dict) -> dict:
    """Compte exact + échantillon d'enregistrements correspondants."""
    import json

    # Égalité stricte via l'opérateur de containment JSONB : c'est indexé (GIN)
    # et ça évite toute construction de SQL à partir de noms fournis par le
    # modèle — les clés voyagent en PARAMÈTRE, jamais dans le texte de requête.
    critere = {str(k): str(v) for k, v in filtres.items() if str(k).strip()}
    if not critere:
        return await _colonnes(conn, niveaux, type_source)
    charge = json.dumps(critere, ensure_ascii=False)

    # Le filtre porte sur le vocabulaire COMMUN (`champs`) si les clés en font
    # partie, sinon sur les entêtes d'origine (`data`). C'est ce qui permet
    # d'interroger « nom » ou « montant_ht » sans savoir comment le logiciel
    # exportateur les appelait, tout en gardant l'accès aux colonnes brutes.
    from ingestion.schema import champs_de
    connus = champs_de(type_source)
    colonne = "champs" if connus and all(k in connus for k in critere) else "data"

    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM document_metadata "
        f"WHERE source_type = $1 AND access_level = ANY($2::text[]) "
        f"AND {colonne} @> $3::jsonb",
        type_source, niveaux, charge)

    if not total:
        return {"source_type": type_source, "filtres": critere, "nombre": 0,
                "message": ("Aucun enregistrement ne correspond EXACTEMENT à ces valeurs. "
                            "Les filtres sont sensibles à l'orthographe : rappelle "
                            "`interroger_donnees` avec le seul `source_type` pour voir "
                            "les valeurs réellement présentes.")}

    lignes = await conn.fetch(
        f"SELECT title, data, champs, source_filename, ligne FROM document_metadata "
        f"WHERE source_type = $1 AND access_level = ANY($2::text[]) "
        f"AND {colonne} @> $3::jsonb "
        f"ORDER BY ligne NULLS LAST LIMIT $4",
        type_source, niveaux, charge, MAX_ENREGISTREMENTS)

    return {
        "source_type": type_source, "filtres": critere, "nombre": total,
        "enregistrements": [{"titre": l["title"], "valeurs": dict(l["data"] or {}),
                             "fichier": l["source_filename"], "ligne": l["ligne"]}
                            for l in lignes],
        "note": (f"{total} enregistrement(s) au total ; {min(total, MAX_ENREGISTREMENTS)} "
                 f"montré(s). Le nombre est EXACT, cite-le tel quel."),
    }
