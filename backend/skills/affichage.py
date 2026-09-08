"""
Blocs d'écran MÉCANIQUES des gestes qui montrent le classement des fichiers
(arborescence, aperçu d'un dossier).

POURQUOI CE MODULE EXISTE. Relevé le 01/09 : « liste les dossiers du Drive » —
le catalogue demandait au modèle de recopier `schema` dans un bloc ``` ; il a
inventé à la place une carte de document (« TXT — Arborescence du Drive ») qui
ne montrait RIEN, puis, sur un aperçu de dossier, un tableau aux lignes
inventées (« Autres dossiers éventuels… (voir arborescence) »). La leçon est
celle de `terminer_document` (30/08) : un bloc d'écran qui DOIT s'afficher se
construit en mécanique dans le skill — on ne demande jamais au modèle de le
recopier. Le résultat porte `bloc_garanti` : `_blocs_garantis` (agent1) ajoute
les blocs au message si le modèle ne les a pas repris, et efface la carte de
document inventée qui les désigne.

Module commun aux deux projets : seul le VOCABULAIRE (« du Drive » /
« du serveur ») vient de l'appelant. Les deux formes d'aperçu sont acceptées
(`detail`/`dossier` côté Drive, `emplacements`/`chemin` côté NAS).
"""
from __future__ import annotations

# Le schéma entre dans le bloc, et le bloc dans le résultat JSON renvoyé au
# modèle : au-delà de cette taille, la coupe du résultat (plafond généreux,
# 12 000) tomberait AU MILIEU du JSON et le bloc deviendrait illisible — donc
# invisible. On coupe ici, À LA LIGNE, et la coupe est DITE.
MAX_SCHEMA_BLOC = 9000


def octets_lisibles(n) -> str:
    """« 3,2 Mo » plutôt que 3355443 : la taille d'un dossier se lit, ne se compte pas."""
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        return ""
    for unite in ("o", "Ko", "Mo", "Go"):
        if v < 1024:
            return f"{int(v)} {unite}" if unite == "o" else f"{v:.1f} {unite}".replace(".", ",")
        v /= 1024
    return f"{v:.1f} To".replace(".", ",")


def garantir_arborescence(resultat: dict, quoi: str) -> dict:
    """Transforme le `schema` texte en bloc d'écran `arbre`, garanti à l'écran.

    `quoi` : « du Drive », « du serveur », « du dossier « X » » — le complément
    qui finit les phrases. Le `schema` QUITTE le résultat : il vit dans le
    bloc, que le modèle voit aussi — le porter deux fois doublait le poids du
    résultat et faisait dépasser le plafond de sérialisation.
    """
    if not isinstance(resultat, dict):
        return resultat
    schema = str(resultat.pop("schema", "") or "")
    if not schema.strip():
        return resultat
    coupe = len(schema) > MAX_SCHEMA_BLOC
    if coupe:
        schema = schema[:MAX_SCHEMA_BLOC].rsplit("\n", 1)[0]

    morceaux = []
    if resultat.get("dossiers_total"):
        morceaux.append(f"{resultat['dossiers_total']} dossiers")
    if resultat.get("fichiers_total"):
        morceaux.append(f"{resultat['fichiers_total']} fichiers")
    sous_titre = " · ".join(morceaux)
    if not resultat.get("complet", True):
        sous_titre = (sous_titre + " · " if sous_titre else "") + "arbre partiel"
    elif coupe:
        sous_titre = (sous_titre + " · " if sous_titre else "") + "affichage coupé"

    bloc = {"type": "arbre", "titre": f"Arborescence {quoi}", "schema": schema}
    if sous_titre:
        bloc["sous_titre"] = sous_titre
    resultat["bloc_ui"] = bloc
    resultat["bloc_garanti"] = True
    resultat["message_final"] = (f"Voici l'arborescence {quoi}"
                                 + (f" : {' et '.join(morceaux)}." if morceaux else "."))
    resultat["a_faire"] = (
        "L'arborescence est DÉJÀ affichée à l'écran par un bloc mécanique : ne "
        "recopie pas le schéma, n'écris AUCUN bloc doc, doc_apercu ou fichier "
        "pour elle, et ne produis JAMAIS un document pour montrer une liste de "
        "dossiers. Rédige une ou deux phrases sur ce que l'arbre montre."
        + (" L'affichage est coupé : propose de préciser un dossier pour zoomer."
           if coupe else ""))
    return resultat


def garantir_apercu(resultat: dict, quoi: str) -> dict:
    """L'aperçu compté d'un dossier en blocs d'écran : la fiche, puis les noms.

    Deux blocs, tous deux MÉCANIQUES : un `keyvalue` (comptes, taille, types)
    et une `list` des sous-dossiers — exactement ce que l'utilisateur demandait
    quand le modèle lui a servi un tableau inventé. Le `titre` du keyvalue ne
    s'affiche pas : il sert au garde-fou à reconnaître la carte inventée qui
    désigne le même aperçu, pour l'effacer.
    """
    if not isinstance(resultat, dict):
        return resultat
    detail = resultat.get("detail") or resultat.get("emplacements") or []
    if not isinstance(detail, list) or not detail:
        return resultat
    entrees = [r for r in detail if isinstance(r, dict)]
    total_d = resultat.get("total_dossiers")
    total_f = resultat.get("total_fichiers")
    if total_d is None:
        total_d = sum(int(r.get("dossiers") or 0) for r in entrees)
    if total_f is None:
        total_f = sum(int(r.get("fichiers") or 0) for r in entrees)
    octets = sum(int(r.get("octets") or r.get("octets_total") or 0) for r in entrees)
    types: dict[str, int] = {}
    noms: list[str] = []
    for r in entrees:
        for ext, n in (r.get("types_de_fichiers") or {}).items():
            try:
                types[str(ext)] = types.get(str(ext), 0) + int(n or 0)
            except (TypeError, ValueError):
                continue
        for nom in (r.get("noms_des_dossiers") or []):
            if nom and nom not in noms:
                noms.append(str(nom))

    rows = [["Dossier", quoi],
            ["Sous-dossiers", str(total_d)],
            ["Fichiers", str(total_f)]]
    if octets:
        rows.append(["Taille", octets_lisibles(octets)])
    if types:
        tri = sorted(types.items(), key=lambda kv: -kv[1])[:6]
        rows.append(["Types de fichiers", " · ".join(f"{e} ×{n}" for e, n in tri)])
    blocs: list[dict] = [{"type": "keyvalue", "titre": f"Aperçu — {quoi}", "rows": rows}]
    if noms:
        blocs.append({"type": "list", "items": noms[:60]})

    # Les noms des sous-dossiers sont déjà dans le bloc : les laisser AUSSI
    # dans le résultat doublait son poids et le poussait au-delà de la coupe.
    resultat.pop("detail", None)
    resultat.pop("emplacements", None)
    resultat["bloc_ui"] = blocs
    resultat["bloc_garanti"] = True
    resultat["message_final"] = (f"{quoi} : {total_d} sous-dossier(s) et "
                                 f"{total_f} fichier(s).")
    resultat["a_faire"] = (
        "L'aperçu (comptes et noms des sous-dossiers) est DÉJÀ affiché à "
        "l'écran par des blocs mécaniques : ne le recopie pas, n'écris AUCUN "
        "bloc doc, doc_apercu ou fichier pour lui, et ne produis JAMAIS un "
        "document pour montrer un dossier. Rédige une ou deux phrases ; pour "
        "le détail d'un sous-dossier, rappelle l'aperçu avec son nom.")
    return resultat


def garantir_recherche(resultat: dict, motif: str, ouvreur: str | None = None) -> dict:
    """La recherche par NOM en tableau mécanique : nom, type, emplacement.

    08/09 soir (Symbiose) : « trouve un devis que nous avons fait et ouvre-le »
    → cinq gestes, 993 correspondances, et RIEN d'ouvert : la consigne disait
    « propose la suite, c'est à l'utilisateur de dire s'il veut aller plus
    loin ». Quand la demande EST d'ouvrir, la suite ne se propose pas, elle
    s'enchaîne — sur un FICHIER, choisi par le modèle (« au hasard », « le
    plus récent »), avec `ouvreur` (`drive_ouvrir` / `nas_ouvrir`).

    Demande de Noa du 01/09 : quand une information sur un client manque en
    mémoire, l'assistant cherche « instinctivement » les dossiers et fichiers
    qui PARLENT de ce client — et montre ce qu'il trouve, avant de proposer
    d'aller plus loin. Les deux recherches (Drive et NAS) rendent la même
    forme (`resultats`: nom, chemin, dossier) : un seul afficheur.
    """
    if not isinstance(resultat, dict):
        return resultat
    entrees = [r for r in (resultat.get("resultats") or []) if isinstance(r, dict)]
    dossiers = sum(1 for r in entrees if r.get("dossier"))
    fichiers = len(entrees) - dossiers
    if not entrees:
        resultat["message_final"] = (f"Aucun dossier ni fichier ne porte "
                                     f"« {motif} » dans son nom.")
        resultat["a_faire"] = (
            "Rien ne SORT de cette recherche, ce qui ne prouve pas l'absence : "
            "dis ce que tu as cherché et retente avec UN seul mot du nom ou une "
            "autre orthographe avant de conclure ; propose aussi la recherche "
            "dans le CONTENU des documents.")
        return resultat
    lignes = [[str(r.get("nom") or ""),
               "Dossier" if r.get("dossier") else "Fichier",
               str(r.get("chemin") or "")] for r in entrees]
    resultat["bloc_ui"] = {"type": "table",
                           "titre": f"Recherche — {motif}",
                           "columns": ["Nom", "Type", "Emplacement"],
                           "rows": lignes}
    # Mêmes données que `rows` : on ne les rend pas deux fois (cf. le `schema`
    # de l'arborescence, retiré pour la même raison).
    resultat.pop("resultats", None)
    resultat["bloc_garanti"] = True
    pages = int(resultat.get("pages") or 1)
    # Les totaux (toutes pages) quand la recherche les donne : « 993
    # correspondances » sans dire combien de FICHIERS laissait croire qu'il n'y
    # avait que des dossiers nommés « Devis ».
    total_d = resultat.get("dossiers_total")
    total_f = resultat.get("fichiers_total")
    if total_d is not None and total_f is not None and pages > 1:
        compte = (f"« {motif} » : {total_d} dossier(s) et {total_f} fichier(s) portent "
                  f"ce nom (page {resultat.get('page', 1)} sur {pages} : {dossiers} "
                  f"dossier(s), {fichiers} fichier(s) affichés).")
    else:
        compte = (f"« {motif} » : {dossiers} dossier(s) et {fichiers} fichier(s) trouvés "
                  "par leur nom"
                  + (f" (page {resultat.get('page', 1)} sur {pages})" if pages > 1 else "")
                  + ".")
    resultat["message_final"] = compte
    geste = f"`{ouvreur}`" if ouvreur else "le geste d'ouverture"
    resultat["a_faire"] = (
        "Les résultats sont DÉJÀ affichés à l'écran par un bloc mécanique : ne "
        "les recopie pas, n'écris aucun bloc doc ou fichier pour eux. "
        "SI LA DEMANDE DE CE TOUR EST D'OUVRIR OU DE LIRE UN DOCUMENT (« ouvre un "
        "devis », « un au hasard », « le plus récent », « trouve X et ouvre-le ») : "
        f"enchaîne MAINTENANT avec {geste} sur le NOM EXACT d'une ligne de type "
        "« Fichier » — jamais un dossier —, en choisissant toi-même ; "
        + ("aucun fichier sur cette page : rappelle la recherche avec `type: "
           "\"fichiers\"` ou liste un dossier trouvé ; "
           if (not fichiers and resultat.get("fichiers_total")) else "")
        + "n'ouvre pas de dossier, ne demande pas lequel. Sinon : rédige une ou "
        "deux phrases sur ce qui a été trouvé, puis PROPOSE la suite (ouvrir un "
        "fichier, explorer un dossier, chercher dans le contenu des documents)."
        + (" Le résultat est PAGINÉ : si la demande porte sur tout, enchaîne "
           "les pages (`page` suivante) — rien ne te limite en nombre de pages."
           if pages > 1 else ""))
    return resultat


def garantir_fichier_lu(resultat: dict, nom: str, octets: bytes, proprietaire: str,
                        mime: str | None = None) -> dict:
    """Un fichier LU sur le serveur de fichiers s'affiche : carte avec aperçu et
    téléchargement, posée MÉCANIQUEMENT dans le résultat.

    Relevé de Noa du 08/09 (export Langfuse de Duret) : « il n'arrive pas à
    ouvrir un document du NAS et le prévisualiser dans le chat, il n'arrive à
    prévisualiser que les documents qu'il crée ». Cause : `nas_ouvrir` et
    `drive_ouvrir` rendaient le TEXTE extrait, rien d'autre — aucun dépôt,
    donc aucune carte, aucun aperçu, rien à télécharger ; le modèle résumait
    le texte et l'écran restait vide. Les pièces jointes des mails, elles,
    passent par le dépôt depuis le 31/08 (`mail/pieces.py`) : même geste ici,
    même écran. Une image va au dépôt des visuels (bloc `visuel`), tout le
    reste à l'atelier (bloc `fichier`, aperçu PDF / Word / Excel), sous
    l'origine « serveur » — un fichier lu n'est pas un document PRODUIT.

    Un dépôt qui échoue ne fait pas tomber la lecture : le texte reste.
    """
    import logging
    if not isinstance(resultat, dict) or not octets or not (proprietaire or "").strip():
        return resultat
    nom = (nom or "fichier").rsplit("/", 1)[-1]
    extension = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
    try:
        if (mime or "").startswith("image/") or extension in ("jpg", "jpeg", "png", "webp", "gif"):
            from visuels.depot import deposer_octets
            cle = deposer_octets(octets, mime or f"image/{'jpeg' if extension == 'jpg' else extension or 'png'}")
            if not cle:
                return resultat
            resultat["url"] = f"/api/visuels/{cle}"
            resultat["bloc_ui"] = {"type": "visuel", "titre": nom,
                                   "images": [{"cle": cle, "legende": nom}]}
        else:
            from bureautique.atelier import deposer_fichier
            jeton = deposer_fichier(nom, octets, proprietaire, origine="serveur")
            if not jeton:
                return resultat
            resultat["url"] = f"/api/documents/{jeton}"
            resultat["bloc_ui"] = {"type": "fichier", "url": resultat["url"], "nom": nom,
                                   "titre": nom.rsplit(".", 1)[0], "format": extension or "bin",
                                   "octets": len(octets)}
    except Exception as e:  # noqa: BLE001 — la lecture vaut sans la carte
        logging.getLogger("skills.affichage").warning(
            "Dépôt du fichier lu « %s » impossible : %s", nom, e)
        return resultat
    resultat["bloc_garanti"] = True
    resultat["message_final"] = (f"« {nom} » ({octets_lisibles(len(octets))}) est affiché : "
                                 "aperçu et téléchargement dans le chat.")
    resultat["a_faire"] = (
        "Le fichier est DÉJÀ affiché à l'écran par un bloc mécanique (carte avec "
        "aperçu et téléchargement) : n'écris AUCUN bloc fichier, doc ou visuel pour "
        "lui, ne colle pas son contenu. Réponds à la demande avec ce que le fichier "
        "contient (`texte` ou `apercu`), en quelques lignes, puis propose la suite "
        "si elle est évidente (résumer, chiffrer, comparer).")
    return resultat


def garantir_listage(resultat: dict, quoi: str, ouvreur: str = "nas_ouvrir") -> dict:
    """Le contenu d'un dossier en tableau MÉCANIQUE : nom, type, taille.

    08/09 : « ouvre le » → le modèle a décrit un dossier avec QUATRE fichiers
    inventés (DPGF, DCE 10,5 Mo, plan de réception) alors qu'aucun listage
    n'avait tourné ; et sur un vrai listage, il recopiait la liste à sa façon,
    puis demandait « lequel je prends ? ». Le tableau vient du serveur, pas du
    modèle ; `entrees` reste dans le résultat (le modèle a besoin des
    `chemin`) ; et la consigne dit d'ENCHAÎNER l'ouverture quand c'est ce que
    la demande réclame.
    """
    if not isinstance(resultat, dict):
        return resultat
    entrees = [e for e in (resultat.get("entrees") or []) if isinstance(e, dict)]
    if not entrees:
        return resultat
    lignes = [[str(e.get("nom") or ""),
               "Dossier" if e.get("dossier") else "Fichier",
               ("" if e.get("dossier") else octets_lisibles(e.get("octets") or 0))]
              for e in entrees]
    dossiers = sum(1 for e in entrees if e.get("dossier"))
    fichiers = len(entrees) - dossiers
    resultat["bloc_ui"] = {"type": "table",
                           "titre": f"Contenu — {(resultat.get('chemin') or quoi or '').rsplit('/', 1)[-1]}",
                           "columns": ["Nom", "Type", "Taille"],
                           "rows": lignes}
    resultat["bloc_garanti"] = True
    resultat["message_final"] = (f"{dossiers} dossier(s) et {fichiers} fichier(s) dans "
                                 f"« {(resultat.get('chemin') or quoi or '').rsplit('/', 1)[-1]} »"
                                 + (" (liste tronquée)." if resultat.get("tronque") else "."))
    resultat["a_faire"] = (
        "Le contenu du dossier est DÉJÀ affiché à l'écran par un tableau mécanique : "
        "ne le recopie pas, n'écris aucun bloc list, doc ou fichier pour lui. "
        f"Si la demande de ce tour est d'OUVRIR ou de LIRE un document, enchaîne "
        f"MAINTENANT avec `{ouvreur}` et le `chemin` EXACT d'une entrée `dossier: false` "
        "(« au hasard », « le plus lourd », « le plus récent », « le DCE » : choisis toi-même "
        "d'après les noms et les tailles, ne demande pas lequel). Si la demande était de "
        "voir le contenu, une phrase suffit. "
        + (resultat.get("note") or ""))
    return resultat
