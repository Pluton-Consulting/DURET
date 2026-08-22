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


def _jsonb(valeur) -> dict:
    """Un JSONB tel qu'asyncpg le rend : une CHAÎNE, pas un dict.

    Relevé en production le 22/08, traces Langfuse : `liste_clients` rendait
    « dictionary update sequence element #0 has length 1; 2 is required » — le
    message de `dict()` nourri d'une chaîne. Aucun codec JSON n'est posé sur le
    pool (`database/connection.py`), donc `row["data"]` arrive en texte. Le
    banc ne l'avait pas vu parce que sa fausse base rendait des dicts : une
    doublure qui ment sur le TYPE teste un code qui n'existe pas. Elle rend
    désormais des chaînes, comme la vraie.
    """
    if not valeur:
        return {}
    if isinstance(valeur, dict):
        return valeur
    if isinstance(valeur, (bytes, bytearray)):
        valeur = valeur.decode("utf-8", "replace")
    if isinstance(valeur, str):
        import json
        try:
            d = json.loads(valeur)
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}
    try:
        return dict(valeur)
    except (TypeError, ValueError):
        return {}


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

            # Un jeu de données INEXISTANT ne doit pas répondre « zéro ». Observé
            # en production : « fournisseurs » demandé au pluriel alors que le
            # type est « fournisseur », zéro rendu, et l'assistant en a déduit
            # que les données n'étaient pas importées — juste après en avoir
            # listé quatre-vingt-dix. Un zéro sur un nom qui n'existe pas est
            # indiscernable d'un zéro sur un jeu réellement vide.
            reel, existants = await _resoudre_type(conn, niveaux, type_source)
            if reel is None:
                return {
                    "source_type_demande": type_source, "nombre": 0,
                    "jeux_de_donnees": existants,
                    "message": (f"Il n'existe aucun jeu de données nommé « {type_source} ». "
                                f"Ce n'est PAS un jeu vide : ce nom n'existe pas. "
                                f"Disponibles : {', '.join(existants) or 'aucun'}. "
                                "Reformule avec l'un de ces noms."),
                }

            agreger = data.get("agreger") or {}
            if isinstance(agreger, str):
                import json as _j
                try:
                    agreger = _j.loads(agreger)
                except _j.JSONDecodeError:
                    agreger = {"operation": "somme", "colonne": agreger}
            annee = str(data.get("annee") or "").strip()
            if agreger or annee:
                resultat = await _agreger(conn, niveaux, reel,
                                          agreger if isinstance(agreger, dict) else {},
                                          annee, filtres)
            elif not filtres:
                resultat = await _colonnes(conn, niveaux, reel)
            else:
                resultat = await _filtrer(conn, niveaux, reel, filtres)
            if reel != type_source:
                resultat["source_type_demande"] = type_source
                resultat["note_nom"] = (f"« {type_source} » a été compris comme « {reel} », "
                                        "le nom réel du jeu de données.")
            return resultat
    except Exception as e:  # noqa: BLE001 - une lecture ratée n'est pas une panne du chat
        logger.warning("Interrogation des données impossible : %s", e)
        # Un ECHEC, pas une reponse. Rendu comme un dictionnaire ordinaire, il
        # passait pour une interrogation reussie : le modele en concluait que la
        # donnee n'existait pas, au lieu de dire que la lecture avait echoue.
        from skills.erreurs import SkillError
        raise SkillError("Les données importées sont momentanément indisponibles.")


def _cle_comparaison(nom: str) -> str:
    """Forme comparable d'un nom de jeu de données.

    Sans accents, en minuscules, et sans le « s » final : le modèle écrit
    naturellement « fournisseurs » ou « Devis » là où le type est « fournisseur ».
    Exiger le nom exact ferait dépendre une réponse chiffrée d'un pluriel.
    """
    import unicodedata
    plat = "".join(c for c in unicodedata.normalize("NFD", (nom or "").strip().lower())
                   if unicodedata.category(c) != "Mn")
    return plat[:-1] if len(plat) > 3 and plat.endswith("s") else plat


async def _resoudre_type(conn, niveaux: list[str], demande: str) -> tuple[str | None, list[str]]:
    """Nom RÉEL du jeu de données visé, ou None s'il n'existe pas.

    Rend aussi la liste de ce qui existe : c'est elle qui permet de dire « ce
    nom n'existe pas, voici les vrais » plutôt que de laisser croire à un vide.
    """
    existants = [l["source_type"] for l in await conn.fetch(
        "SELECT DISTINCT source_type FROM document_metadata "
        "WHERE access_level = ANY($1::text[]) ORDER BY source_type", niveaux)]
    if demande in existants:
        return demande, existants
    cible = _cle_comparaison(demande)
    proches = [t for t in existants if _cle_comparaison(t) == cible]
    # Une seule correspondance : on la retient. Plusieurs : on ne devine pas,
    # choisir au hasard donnerait un chiffre juste pour le mauvais jeu.
    return (proches[0] if len(proches) == 1 else None), existants


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
        # Le jeu EXISTE (le nom a été résolu) mais rien n'est visible à ce
        # profil. Le dire ainsi, et pas « il n'y a pas de données » : la
        # nuance est tout l'écart entre un problème de droits et une absence.
        return {"source_type": type_source, "enregistrements": 0,
                "message": (f"Le jeu de données « {type_source} » existe, mais aucun "
                            "de ses enregistrements n'est visible à ce profil. "
                            "C'est une question de droits d'accès, pas une absence "
                            "de données : ne conclus pas qu'il n'y en a pas.")}

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
    communs = await conn.fetch(
        "SELECT DISTINCT d.key AS cle FROM document_metadata m, "
        "       jsonb_each_text(m.champs) AS d "
        "WHERE m.source_type = $1 AND m.access_level = ANY($2::text[])",
        type_source, niveaux)
    # Le sens n'est connu que pour les amorces ; un champ né d'un import au
    # sujet imprévu n'en a pas, et c'est normal — son nom parle de lui-même.
    from ingestion.schema import amorces_de
    connus = amorces_de(type_source)

    return {
        "source_type": type_source, "enregistrements": total,
        "champs_communs": [{"nom": l["cle"], "sens": connus.get(l["cle"], "")}
                           for l in communs],
        "colonnes": [{"nom": c, "valeurs_frequentes": v}
                     for c, v in list(colonnes.items())[:MAX_COLONNES]],
        "note": ("Valeurs les plus fréquentes seulement, pas la liste complète. "
                 "Filtre de préférence sur `champs_communs` : ils portent le même nom "
                 "quel que soit le fichier d'origine. Les `colonnes` sont les entêtes "
                 "brutes du fichier. Rappelle avec `filtres` pour un compte exact. "
                 "Réponds toujours par une PHRASE, jamais par un nombre seul."),
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
    #
    # On interroge les champs RÉELLEMENT PRÉSENTS, et non une liste écrite à
    # l'avance : un champ né d'un import au sujet imprévu (`surface_m2`…) est
    # tout aussi légitime, et le confronter à une liste figée le renverrait vers
    # `data` où il n'existe pas — un zéro faux.
    presents = {l["cle"] for l in await conn.fetch(
        "SELECT DISTINCT d.key AS cle FROM document_metadata m, "
        "       jsonb_each_text(m.champs) AS d "
        "WHERE m.source_type = $1 AND m.access_level = ANY($2::text[])",
        type_source, niveaux)}
    colonne = "champs" if presents and all(k in presents for k in critere) else "data"

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
        "enregistrements": [{"titre": l["title"], "valeurs": _jsonb(l["data"]),
                             "fichier": l["source_filename"], "ligne": l["ligne"]}
                            for l in lignes],
        "note": (f"{total} enregistrement(s) au total ; {min(total, MAX_ENREGISTREMENTS)} "
                 f"montré(s). Le nombre est EXACT, cite-le tel quel. Réponds par une "
                 f"PHRASE qui dit ce qui est compté, jamais par le nombre seul : un "
                 f"chiffre nu se lit comme une panne, même quand il est juste."),
    }


# ── Agrégation : sommer, moyenner, grouper ─────────────────────────────────
#
# « Quel chiffre d'affaires avons-nous réalisé en 2024 ? » — et l'assistant
# répondait, honnêtement, qu'il savait COMPTER les devis mais pas en TOTALISER
# les montants. Relevé en production, avec 1 398 devis importés sous la main.
# Compter sans sommer, c'est décrire un tableur sans savoir l'additionner.
#
# Les valeurs sont des chaînes telles qu'importées (« 12 500,00 € »,
# « 03/04/2024 ») : le schéma d'import ne les type pas, à dessein. On les lit
# donc ici avec prudence, et on DIT combien ont pu être lues : « sur 1 398
# devis de 2024, 1 350 montants lisibles, total X » vaut mieux qu'un total
# silencieusement faux.

_OPERATIONS = {"somme": "SUM", "total": "SUM", "moyenne": "AVG", "min": "MIN",
               "minimum": "MIN", "max": "MAX", "maximum": "MAX", "compte": "COUNT"}

# Une valeur textuelle → un nombre, ou NULL. Gère « 12 500,00 € », « 12.500,00 »,
# « 1,234.50 », « 850 ». Jamais d'erreur : une chaîne illisible devient NULL.
_SQL_NOMBRE = r"""
    CASE
      WHEN nettoye ~ '^-?[0-9]+(\.[0-9]+)?$' THEN nettoye::numeric
      ELSE NULL
    END
"""
_SQL_NETTOYAGE = r"""
    CASE
      WHEN brut IS NULL THEN NULL
      -- virgule ET point : le dernier des deux est le séparateur décimal
      WHEN brut ~ ',' AND brut ~ '\.' THEN
        CASE WHEN position(',' in reverse(brut)) < position('.' in reverse(brut))
             THEN replace(replace(regexp_replace(brut, '[^0-9,.-]', '', 'g'), '.', ''), ',', '.')
             ELSE replace(regexp_replace(brut, '[^0-9,.-]', '', 'g'), ',', '') END
      -- virgule seule : décimale à la française
      WHEN brut ~ ',' THEN replace(regexp_replace(brut, '[^0-9,-]', '', 'g'), ',', '.')
      -- plusieurs points : des milliers
      WHEN (length(brut) - length(replace(brut, '.', ''))) > 1
           THEN replace(regexp_replace(brut, '[^0-9.-]', '', 'g'), '.', '')
      -- UN point suivi d'exactement trois chiffres, sans virgule : « 7.000 »,
      -- « 12.500 € » — en français c'est un séparateur de milliers, pas une
      -- décimale. Relevé au test : 7.000 lu 7,0, le total d'une année faux
      -- de 6 993 €. « 1250.50 » ou « 1.5 » restent des décimales.
      WHEN regexp_replace(brut, '[^0-9.-]', '', 'g') ~ '^-?[0-9]{1,3}\.[0-9]{3}$'
           THEN replace(regexp_replace(brut, '[^0-9.-]', '', 'g'), '.', '')
      ELSE regexp_replace(brut, '[^0-9.-]', '', 'g')
    END
"""


async def _agreger(conn, niveaux: list[str], type_source: str, agreger: dict,
                   annee: str, filtres: dict) -> dict:
    """Somme / moyenne / min / max d'une colonne numérique, avec filtre d'année
    et regroupement facultatifs. Les clés voyagent en PARAMÈTRE, jamais dans le
    texte SQL."""
    import json
    demandee = str(agreger.get("operation") or "somme").strip().lower()
    # UNE OPÉRATION INCONNUE N'EST PAS UNE SOMME. Relevé dans les traces du
    # 22/08 : le modèle a demandé {"operation": "liste", "colonne": "nom"} pour
    # obtenir les noms des clients, et a reçu… la SOMME de la colonne nom — un
    # résultat absurde, rendu avec l'assurance d'un calcul juste. On refuse, et
    # on dit quel geste fait ce qu'il voulait.
    if demandee not in _OPERATIONS:
        return {"source_type": type_source, "erreur":
                f"Opération « {demandee} » inconnue. Opérations possibles : "
                + ", ".join(sorted(set(_OPERATIONS))) + ". Pour LISTER des "
                "enregistrements, n'utilise pas `agreger` : passe des `filtres`, ou "
                "appelle `liste_clients` / `fiche_client` s'il s'agit de clients."}
    operation = _OPERATIONS[demandee]
    colonne = str(agreger.get("colonne") or "").strip()
    par = str(agreger.get("par") or "").strip()          # "annee", "mois" ou un nom de colonne
    colonne_date = str(agreger.get("colonne_date") or "date").strip()

    if operation != "COUNT" and not colonne:
        return {"source_type": type_source, "erreur":
                "Précise `agreger.colonne` (la colonne à sommer/moyenner, ex. montant_ht). "
                "Rappelle `interroger_donnees` avec le seul `source_type` pour voir les colonnes."}

    # Filtres d'égalité éventuels (même logique que _filtrer).
    critere = {str(k): str(v) for k, v in (filtres or {}).items() if str(k).strip()}
    charge = json.dumps(critere, ensure_ascii=False) if critere else None

    # L'année se lit dans la colonne de date, texte brut : on cherche les quatre
    # chiffres entourés de non-chiffres (03/04/2024, 2024-04-03, « avril 2024 »).
    motif_annee = None
    if annee:
        if not annee.isdigit() or len(annee) != 4:
            return {"source_type": type_source,
                    "erreur": f"`annee` doit être sur quatre chiffres (reçu « {annee} »)."}
        motif_annee = f"(^|[^0-9]){annee}([^0-9]|$)"

    # Regroupement : par année (4 chiffres de la date), par mois (AAAA-MM, ou
    # MM/AAAA ramené à AAAA-MM), ou par la valeur brute d'une colonne.
    if par in ("annee", "année"):
        sql_groupe = "substring(COALESCE(m.champs->>$5::text, m.data->>$5::text) from '([0-9]{4})')"
    elif par == "mois":
        sql_groupe = ("COALESCE(substring(COALESCE(m.champs->>$5::text, m.data->>$5::text) from '([0-9]{4}-[0-9]{2})'), "
                      "regexp_replace(substring(COALESCE(m.champs->>$5::text, m.data->>$5::text) from '([0-9]{2}/[0-9]{4})'), "
                      r"'([0-9]{2})/([0-9]{4})', '\2-\1'))")
    elif par:
        sql_groupe = "COALESCE(m.champs->>$6::text, m.data->>$6::text)"
    else:
        sql_groupe = "NULL"

    sql = f"""
        WITH base AS (
          SELECT COALESCE(m.champs->>$3::text, m.data->>$3::text) AS brut,
                 {sql_groupe} AS groupe,
                 -- $6 est cite ici meme quand le regroupement ne s'en sert pas :
                 -- asyncpg ne sait pas typer un parametre absent de la requete.
                 $6::text AS _groupe_param
          FROM document_metadata m
          WHERE m.source_type = $1::text AND m.access_level = ANY($2::text[])
            AND ($4::text IS NULL OR COALESCE(m.champs->>$5::text, m.data->>$5::text) ~ $4)
            AND ($7::jsonb IS NULL OR m.champs @> $7::jsonb OR m.data @> $7::jsonb)
        ), nettoyee AS (
          SELECT groupe, brut, ({_SQL_NETTOYAGE}) AS nettoye FROM base
        ), valeurs AS (
          SELECT groupe, brut, ({_SQL_NOMBRE}) AS nombre FROM nettoyee
        )
        SELECT groupe,
               COUNT(*)                         AS enregistrements,
               COUNT(nombre)                    AS lisibles,
               {operation}(nombre)              AS resultat
        FROM valeurs
        GROUP BY groupe
        ORDER BY groupe NULLS LAST
    """
    param_groupe = par if par not in ("annee", "année", "mois", "") else colonne_date
    lignes = await conn.fetch(sql, type_source, niveaux, colonne or "_", motif_annee,
                              colonne_date, param_groupe, charge)

    total_enr = sum(int(l["enregistrements"]) for l in lignes)
    total_lis = sum(int(l["lisibles"]) for l in lignes)
    if not total_enr:
        return {"source_type": type_source, "operation": operation.lower(), "colonne": colonne,
                "annee": annee or None, "filtres": critere or None, "nombre": 0,
                "message": ("Aucun enregistrement ne correspond (année ou filtres). Vérifie "
                            "la colonne de date (`agreger.colonne_date`, par défaut « date ») "
                            "et les valeurs réelles avec le seul `source_type`.")}

    def _num(v):
        return float(v) if v is not None else None

    groupes = [{"groupe": l["groupe"], "enregistrements": int(l["enregistrements"]),
                "lisibles": int(l["lisibles"]), "resultat": _num(l["resultat"])} for l in lignes]
    if not par:
        g = groupes[0]
        sortie = {"source_type": type_source, "operation": operation.lower(), "colonne": colonne,
                  "annee": annee or None, "filtres": critere or None,
                  "enregistrements": g["enregistrements"], "valeurs_lisibles": g["lisibles"],
                  "resultat": g["resultat"]}
    else:
        sortie = {"source_type": type_source, "operation": operation.lower(), "colonne": colonne,
                  "par": par, "annee": annee or None, "filtres": critere or None,
                  "groupes": groupes, "enregistrements": total_enr, "valeurs_lisibles": total_lis}
    sortie["note"] = (
        f"{total_enr} enregistrement(s) pris en compte, {total_lis} valeur(s) de "
        f"« {colonne or 'compte'} » lisibles comme nombres ({total_enr - total_lis} "
        "illisible(s) ou vide(s), ignorée(s)). Le résultat porte sur les valeurs lisibles "
        "UNIQUEMENT : dis-le si l'écart est notable. Les montants sont dans l'unité du "
        "fichier d'origine (souvent HT, en euros) : ne convertis pas, ne devine pas la TVA. "
        "Réponds par une PHRASE qui dit ce qui est calculé, sur quoi, et avec quelle réserve.")
    return sortie
