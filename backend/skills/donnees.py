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
                    # DEUX PUBLICS, DEUX CHAMPS. `message` est ce que la personne
                    # LIT quand le modèle ne rédige pas (repli d'affichage, cf.
                    # `_message_apres_action`) ; `a_faire` est la consigne au
                    # modèle. Les confondre a mis « Reformule avec l'un de ces
                    # noms » et des noms de skills sous les yeux d'un utilisateur.
                    "message": (f"Il n'existe pas de jeu de données nommé "
                                f"« {type_source} ». Jeux disponibles : "
                                f"{', '.join(existants) or 'aucun'}."),
                    "a_faire": (f"Ce n'est PAS un jeu vide : ce nom n'existe pas. "
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
            fragments = _fragments(data)
            depuis = str(data.get("depuis") or data.get("periode") or "").strip()
            if agreger or annee or depuis:
                resultat = await _agreger(conn, niveaux, reel,
                                          agreger if isinstance(agreger, dict) else {},
                                          annee, filtres, fragments, depuis)
            elif not filtres and not fragments:
                resultat = await _colonnes(conn, niveaux, reel)
            else:
                try:
                    page = max(1, int(data.get("page") or 1))
                except (TypeError, ValueError):
                    page = 1
                resultat = await _filtrer(conn, niveaux, reel, filtres, fragments, page)
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


def _fragments(data: dict) -> dict:
    """Les recherches PARTIELLES demandées : {colonne: bout de texte}.

    POURQUOI CELA MANQUAIT, ET CE QUE ÇA COÛTAIT. `filtres` est une égalité
    stricte (containment JSONB, indexé) : « combien de chantiers avec terrasse
    bois » ne trouvait donc RIEN, parce que la colonne réelle contient des
    phrases — « Création terrasse bois et allée », « Terrasse bois exotique +
    massif ». Le zéro rendu était juste au sens du code et faux au sens de la
    question, et rien ne signalait la différence. Or c'est la forme même des
    questions qu'on pose à un assistant : un mot, pas une valeur exacte.
    """
    brut = data.get("contient") or data.get("contenant") or {}
    if isinstance(brut, str):
        import json
        try:
            brut = json.loads(brut)
        except ValueError:
            return {}
    if not isinstance(brut, dict):
        return {}
    return {str(k): str(v) for k, v in brut.items() if str(k).strip() and str(v).strip()}


def _clause_contient(fragments: dict, premier: int) -> tuple[str, list]:
    """La condition SQL des recherches partielles, et ses paramètres.

    Les noms de colonnes viennent du modèle : ils voyagent en PARAMÈTRE, jamais
    dans le texte de la requête — même règle que partout ailleurs ici.
    """
    morceaux, params = [], []
    for colonne, bout in fragments.items():
        morceaux.append(
            f"COALESCE(m.champs->>${premier}::text, m.data->>${premier}::text) "
            f"ILIKE ${premier + 1}::text")
        params += [colonne, f"%{bout}%"]
        premier += 2
    return (" AND ".join(morceaux) if morceaux else "TRUE"), params


# ── La période : elle se lit dans `skills/lecture.py` ─────────────────────
#
# Il y avait ici deux fonctions maison : une lecture de « 12m » en jours, et un
# motif de MOIS ENTIERS cherché dans la colonne de date. Elles ont été retirées
# pour deux raisons. La granularité du mois comptait un mois de trop sur « les
# 12 derniers mois » ; et le motif ne connaissait que AAAA-MM et MM/AAAA, si
# bien qu'un export datant « 5 sept. 25 » ou « 3 avril 2024 » sortait de la
# période SANS QUE RIEN NE LE DISE — des lignes perdues en silence, ce qui est
# la pire des deux erreurs possibles.
#
# `skills/lecture.py` fait les deux, au jour près et sur tous les formats
# rencontrés, et il DIT ce qu'il ne sait pas lire. Une seule implémentation,
# testable sans base.


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
                            "de ses enregistrements n'est accessible avec vos droits."),
                "a_faire": ("C'est une question de droits d'accès, pas une absence "
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


async def _filtrer(conn, niveaux: list[str], type_source: str, filtres: dict,
                   fragments: dict = None, page: int = 1) -> dict:
    """Compte exact + une PAGE d'enregistrements correspondants.

    `page` (31/08) : 2 000 devis filtrés se lisaient 25 par 25… sans jamais
    pouvoir passer aux 25 suivants. Le compte reste exact, la page se dit.
    """
    page = max(1, int(page or 1))
    import json

    # Égalité stricte via l'opérateur de containment JSONB : c'est indexé (GIN)
    # et ça évite toute construction de SQL à partir de noms fournis par le
    # modèle — les clés voyagent en PARAMÈTRE, jamais dans le texte de requête.
    critere = {str(k): str(v) for k, v in filtres.items() if str(k).strip()}
    fragments = fragments or {}
    if not critere and not fragments:
        return await _colonnes(conn, niveaux, type_source)
    # Sans égalité stricte, le containment doit accepter TOUT : `{}` est contenu
    # dans n'importe quel objet JSON, la condition devient donc neutre et seule
    # la recherche partielle filtre.
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

    partiel, params_partiel = _clause_contient(fragments, 4)

    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM document_metadata m "
        f"WHERE source_type = $1 AND access_level = ANY($2::text[]) "
        f"AND {colonne} @> $3::jsonb AND ({partiel})",
        type_source, niveaux, charge, *params_partiel)

    if not total:
        return {"source_type": type_source, "filtres": critere,
                "contient": fragments or None, "nombre": 0,
                "message": "Aucun enregistrement ne correspond à ces critères.",
                "a_faire": ("Les `filtres` exigent la valeur EXACTE ; pour chercher un "
                            "mot À L'INTÉRIEUR d'une colonne (« terrasse bois » dans une "
                            "prestation rédigée en toutes lettres), passe plutôt "
                            "`contient`. Rappelle `interroger_donnees` avec le seul "
                            "`source_type` pour voir les valeurs réellement présentes.")}

    lignes = await conn.fetch(
        f"SELECT title, data, champs, source_filename, ligne FROM document_metadata m "
        f"WHERE source_type = $1 AND access_level = ANY($2::text[]) "
        f"AND {colonne} @> $3::jsonb AND ({partiel}) "
        f"ORDER BY ligne NULLS LAST LIMIT ${4 + len(params_partiel)} "
        f"OFFSET ${5 + len(params_partiel)}",
        type_source, niveaux, charge, *params_partiel, MAX_ENREGISTREMENTS,
        (page - 1) * MAX_ENREGISTREMENTS)
    pages = max(1, -(-int(total) // MAX_ENREGISTREMENTS))

    return {
        "source_type": type_source, "filtres": critere,
        "contient": fragments or None, "nombre": total,
        "page": page, "pages": pages,
        "pour_continuer": (
            f"Pour les {MAX_ENREGISTREMENTS} enregistrements SUIVANTS, rappelle "
            f"interroger_donnees avec les mêmes paramètres et page={page + 1}."
            if page < pages else None),
        "enregistrements": [{"titre": l["title"], "valeurs": _jsonb(l["data"]),
                             "fichier": l["source_filename"], "ligne": l["ligne"]}
                            for l in lignes],
        "note": (f"{total} enregistrement(s) au total ; page {page} sur {pages}, "
                 f"{len(lignes)} montré(s). Le nombre est EXACT, cite-le tel quel. Réponds par une "
                 f"PHRASE qui dit ce qui est compté, jamais par le nombre seul : un "
                 f"chiffre nu se lit comme une panne, même quand il est juste."),
    }


# ── Agrégation : compter, sommer, moyenner, grouper ────────────────────────
#
# « Quel chiffre d'affaires avons-nous réalisé en 2024 ? » — et l'assistant
# répondait, honnêtement, qu'il savait COMPTER les devis mais pas en TOTALISER
# les montants. Relevé en production, avec 1 398 devis importés sous la main.
# Compter sans sommer, c'est décrire un tableur sans savoir l'additionner.
#
# POURQUOI CE CALCUL A QUITTÉ LE SQL.
#
# La première version agrégeait dans la requête : nettoyage des montants par
# expressions régulières SQL, période par motif de mois cherché dans la colonne
# de date. Cela tenait tant qu'on demandait une ANNÉE, sur des dates écrites
# AAAA-MM-JJ ou JJ/MM/AAAA. Deux questions banales l'ont mise en défaut : « sur
# les douze derniers mois » (le motif de mois ne sait pas couper au jour, et
# comptait donc un mois de trop) et « depuis plus de quinze jours » (rien ne
# comparait une date à aujourd'hui). Et tout export datant autrement — « 5 sept.
# 25 », « 3 avril 2024 » — sortait de la période SANS QUE RIEN NE LE DISE.
#
# Écrire tout cela en SQL demandait une fonction Postgres et une migration ;
# surtout, cela restait intestable ici, où aucune base ne tourne : une doublure
# qui réimplémente le SQL en Python teste la doublure, pas le code livré. Le
# calcul se fait donc en Python, sur les lignes que Postgres a filtrées avec ce
# qu'il fait mieux que nous (source, droits, containment indexé, ILIKE).
#
# Ce sont des PME : quelques milliers de lignes par jeu. Le chargement est
# borné, et la borne se DIT quand elle mord — un total tronqué en silence est
# un total faux.
MAX_LIGNES_AGREGEES = 50000

_OPERATIONS = {"somme": "sum", "total": "sum", "moyenne": "avg", "min": "min",
               "minimum": "min", "max": "max", "maximum": "max",
               "compte": "count", "nombre": "count", "combien": "count"}


def _valeur_de(ligne: dict, colonne: str) -> str:
    """La valeur d'une colonne, cherchée dans le vocabulaire commun PUIS dans
    les entêtes d'origine. C'est ce qui permet d'interroger « montant_ht » sans
    savoir comment le logiciel exportateur l'appelait."""
    if not colonne:
        return ""
    for source in ("champs", "data"):
        d = ligne.get(source) or {}
        if colonne in d and str(d[colonne] or "").strip():
            return str(d[colonne])
    # Dernier recours : une comparaison insensible à la casse et aux accents.
    cible = _cle_comparaison(colonne)
    for source in ("champs", "data"):
        for k, v in (ligne.get(source) or {}).items():
            if _cle_comparaison(k) == cible and str(v or "").strip():
                return str(v)
    return ""


async def _charger(conn, niveaux: list[str], type_source: str, filtres: dict,
                   fragments: dict) -> tuple[list, bool]:
    """Les lignes d'un jeu, filtrées par ce que la base sait faire vite."""
    import json
    critere = {str(k): str(v) for k, v in (filtres or {}).items() if str(k).strip()}
    charge = json.dumps(critere, ensure_ascii=False)
    partiel, params = _clause_contient(fragments or {}, 4)
    lignes = await conn.fetch(
        f"SELECT data, champs FROM document_metadata m "
        f"WHERE source_type = $1::text AND access_level = ANY($2::text[]) "
        f"  AND (champs @> $3::jsonb OR data @> $3::jsonb) AND ({partiel}) "
        f"LIMIT ${4 + len(params)}",
        type_source, niveaux, charge, *params, MAX_LIGNES_AGREGEES + 1)
    tronque = len(lignes) > MAX_LIGNES_AGREGEES
    return ([{"data": _jsonb(l["data"]), "champs": _jsonb(l["champs"])}
             for l in lignes[:MAX_LIGNES_AGREGEES]], tronque)


def _groupe_de(ligne: dict, par: str, colonne_date: str):
    """La clé de regroupement : une année, un mois, ou la valeur d'une colonne."""
    from skills.lecture import lire_date
    if par in ("annee", "année"):
        d, _ = lire_date(_valeur_de(ligne, colonne_date))
        return f"{d.year}" if d else None
    if par == "mois":
        d, _ = lire_date(_valeur_de(ligne, colonne_date))
        return f"{d.year}-{d.month:02d}" if d else None
    return _valeur_de(ligne, par) or None


async def _agreger(conn, niveaux: list[str], type_source: str, agreger: dict,
                   annee: str, filtres: dict, fragments: dict = None,
                   depuis: str = "") -> dict:
    """Compte / somme / moyenne / min / max, avec période et regroupement."""
    import datetime
    from skills.lecture import (lire_date, lire_montant, est_un_nombre,
                                fin_de_precision, debut_de_periode)

    fragments = fragments or {}
    # COMPTER EST UNE OPÉRATION, PAS UN OUBLI. Demander « les chantiers de
    # 2026 » sans rien à sommer répondait « Précise agreger.colonne » : le
    # défaut « somme » réclamait une colonne chiffrée pour une question qui
    # n'en voulait aucune. Sans `agreger`, on compte.
    demandee = str(agreger.get("operation")
                   or ("somme" if agreger else "compte")).strip().lower()
    # UNE OPÉRATION INCONNUE N'EST PAS UNE SOMME. Relevé dans les traces du
    # 22/08 : le modèle a demandé {"operation": "liste", "colonne": "nom"} pour
    # obtenir les noms des clients, et a reçu… la SOMME de la colonne nom — un
    # résultat absurde, rendu avec l'assurance d'un calcul juste.
    if demandee not in _OPERATIONS:
        return {"source_type": type_source, "erreur":
                f"Opération « {demandee} » inconnue. Opérations possibles : "
                + ", ".join(sorted(set(_OPERATIONS))) + ". Pour LISTER des "
                "enregistrements, n'utilise pas `agreger` : passe des `filtres`, ou "
                "appelle `liste_clients` / `fiche_client` s'il s'agit de clients."}
    operation = _OPERATIONS[demandee]
    colonne = str(agreger.get("colonne") or "").strip()
    par = str(agreger.get("par") or "").strip()
    colonne_date = str(agreger.get("colonne_date") or "date").strip()

    if operation != "count" and not colonne:
        return {"source_type": type_source, "erreur":
                "Précise `agreger.colonne` (la colonne à sommer/moyenner, ex. montant_ht). "
                "Rappelle `interroger_donnees` avec le seul `source_type` pour voir les colonnes."}

    # ── La période, au JOUR près ───────────────────────────────────────────
    debut = fin = None
    libelle_periode = None
    if annee:
        if not annee.isdigit() or len(annee) != 4:
            return {"source_type": type_source,
                    "erreur": f"`annee` doit être sur quatre chiffres (reçu « {annee} »)."}
        debut = datetime.date(int(annee), 1, 1)
        fin = datetime.date(int(annee), 12, 31)
        libelle_periode = f"année {annee}"
    elif depuis:
        debut = debut_de_periode(depuis)
        if debut is None:
            return {"source_type": type_source, "erreur":
                    f"`depuis` n'est pas une période lisible (reçu « {depuis} »). "
                    "Écris « 12m », « 30j », « 6 mois », « 15 jours », « cette semaine », "
                    "ou une date AAAA-MM-JJ. Ne devine pas : redemande-la."}
        fin = datetime.date.today()
        libelle_periode = f"du {debut.isoformat()} au {fin.isoformat()}"

    lignes, tronque = await _charger(conn, niveaux, type_source, filtres, fragments)

    # ── Le tri des lignes : dans la période, hors période, date illisible ──
    retenues, hors_periode, sans_date = [], 0, 0
    for ligne in lignes:
        if debut is None:
            retenues.append(ligne)
            continue
        brut = _valeur_de(ligne, colonne_date)
        d, precision = lire_date(brut)
        if not d:
            sans_date += 1
            continue
        # Une date imprécise (« avril 2024 ») est retenue dès que sa PLAGE
        # croise la période : c'est le seul choix qui ne perd pas de ligne, et
        # le compte des imprécises est rendu pour qu'on puisse le dire.
        if d <= fin and fin_de_precision(d, precision) >= debut:
            retenues.append(ligne)
        else:
            hors_periode += 1

    if not retenues:
        return {"source_type": type_source, "operation": operation, "colonne": colonne,
                "annee": annee or None, "periode": libelle_periode,
                "filtres": filtres or None, "contient": fragments or None, "nombre": 0,
                "lignes_hors_periode": hors_periode or None,
                "lignes_sans_date_lisible": sans_date or None,
                # Ce que la personne lit garde les COMPTES — ils expliquent le
                # vide, et c'est une information, pas de la tuyauterie.
                "message": (
                    "Aucun enregistrement ne correspond."
                    + (f" {hors_periode} sont hors de la période." if hors_periode else "")
                    + (f" {sans_date} n'ont pas de date lisible dans la colonne "
                       f"« {colonne_date} »." if sans_date else "")),
                "a_faire": (
                    (f"Vérifie `agreger.colonne_date`. " if sans_date else "")
                    + "Rappelle `interroger_donnees` avec le seul `source_type` pour "
                      "voir les colonnes et leurs valeurs réelles.")}

    # ── Le calcul ──────────────────────────────────────────────────────────
    groupes: dict = {}
    for ligne in retenues:
        cle = _groupe_de(ligne, par, colonne_date) if par else None
        g = groupes.setdefault(cle, {"enregistrements": 0, "valeurs": []})
        g["enregistrements"] += 1
        if colonne:
            brut = _valeur_de(ligne, colonne)
            if est_un_nombre(brut):
                g["valeurs"].append(lire_montant(brut))

    def _resultat(g):
        v = g["valeurs"]
        if operation == "count":
            # Compter les ENREGISTREMENTS, pas les valeurs lisibles d'une
            # colonne qu'on n'a pas demandée : « combien de chantiers » ne
            # dépend pas de la présence d'un montant.
            return float(g["enregistrements"]) if not colonne else float(len(v))
        if not v:
            return None
        return {"sum": sum(v), "avg": sum(v) / len(v),
                "min": min(v), "max": max(v)}[operation]

    sortie_groupes = [
        {"groupe": cle, "enregistrements": g["enregistrements"],
         "lisibles": len(g["valeurs"]), "resultat": _resultat(g)}
        for cle, g in sorted(groupes.items(),
                             key=lambda x: (x[0] is None, str(x[0] or "")))]
    total_enr = sum(g["enregistrements"] for g in sortie_groupes)
    total_lis = sum(g["lisibles"] for g in sortie_groupes)

    commun = {"source_type": type_source, "operation": operation, "colonne": colonne,
              "annee": annee or None, "periode": libelle_periode,
              "filtres": filtres or None, "contient": fragments or None,
              "lignes_hors_periode": hors_periode or None,
              "lignes_sans_date_lisible": sans_date or None}
    if not par:
        g = sortie_groupes[0]
        sortie = dict(commun, enregistrements=g["enregistrements"],
                      valeurs_lisibles=g["lisibles"], resultat=g["resultat"])
    else:
        sortie = dict(commun, par=par, groupes=sortie_groupes,
                      enregistrements=total_enr, valeurs_lisibles=total_lis)

    sortie["note"] = (
        (f"Période retenue : {libelle_periode}, bornes comprises. " if libelle_periode else "")
        + f"{total_enr} enregistrement(s) pris en compte"
        + (f", {total_lis} valeur(s) de « {colonne} » lisibles comme nombres "
           f"({total_enr - total_lis} ignorée(s))" if colonne else "")
        + "."
        + (f" {hors_periode} enregistrement(s) écarté(s) car hors période."
           if hors_periode else "")
        + (f" ATTENTION : {sans_date} enregistrement(s) n'ont AUCUNE date lisible dans "
           f"« {colonne_date} » et n'ont pas pu être comptés — dis-le, et propose de "
           f"vérifier la colonne de date." if sans_date else "")
        + (f" ATTENTION : le jeu dépasse {MAX_LIGNES_AGREGEES} lignes, le calcul ne "
           "porte que sur les premières — dis-le." if tronque else "")
        + " Les montants sont dans l'unité du fichier d'origine (souvent HT, en euros) : "
          "ne convertis pas, ne devine pas la TVA. Réponds par une PHRASE qui dit ce qui "
          "est calculé, sur quoi, et avec quelle réserve"
        + (", en citant la période telle quelle." if libelle_periode else "."))
    return sortie
