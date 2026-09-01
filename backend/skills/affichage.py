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


def garantir_recherche(resultat: dict, motif: str) -> dict:
    """La recherche par NOM en tableau mécanique : nom, type, emplacement.

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
    resultat["bloc_garanti"] = True
    pages = int(resultat.get("pages") or 1)
    resultat["message_final"] = (
        f"« {motif} » : {dossiers} dossier(s) et {fichiers} fichier(s) trouvés "
        "par leur nom"
        + (f" (page {resultat.get('page', 1)} sur {pages})" if pages > 1 else "")
        + ".")
    resultat["a_faire"] = (
        "Les résultats sont DÉJÀ affichés à l'écran par un bloc mécanique : ne "
        "les recopie pas, n'écris aucun bloc doc ou fichier pour eux. Rédige "
        "une ou deux phrases sur ce qui a été trouvé, puis PROPOSE la suite : "
        "ouvrir un fichier trouvé, explorer un dossier trouvé, ou pousser la "
        "recherche plus loin (contenu des documents, autre orthographe) — "
        "c'est à l'utilisateur de dire s'il veut aller plus loin."
        + (" Le résultat est PAGINÉ : si la demande porte sur tout, enchaîne "
           "les pages (`page` suivante) — rien ne te limite en nombre de pages."
           if pages > 1 else ""))
    return resultat
