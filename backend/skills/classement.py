"""
Skill `ou_chercher` — dans quel dossier du classement se trouve ce qu'on cherche.

Demande de Noa du 08/09 : l'assistant doit « savoir exactement où chercher ».
La carte du classement (`classement.carte`) est relevée en fond et tenue en
mémoire ; ce skill l'interroge SANS toucher au stockage : une réponse en
quelques millisecondes, là où « parcours le Drive » coûtait une minute.

Il rend les DOSSIERS dont le nom ou le contenu parle du sujet, avec leur
chemin exact et ce qu'ils contiennent, dans un tableau mécanique (bloc
garanti, comme la recherche par nom). Il ne lit aucun fichier : le geste
d'ouverture reste celui du stockage, et le résultat dit lequel.
"""
from __future__ import annotations

from skills.registre import Declaration


async def ou_chercher(data: dict, user) -> dict:
    from classement.carte import chercher_dans_la_carte, chunks_prets, statut
    try:
        from classement.source import GESTE_CHERCHER, GESTE_LISTER, NOM_STOCKAGE
    except Exception:  # noqa: BLE001 — pas de source déclarée chez ce client
        GESTE_LISTER, GESTE_CHERCHER, NOM_STOCKAGE = "lister", "chercher", "stockage"

    sujet = str(data.get("sujet") or data.get("motif") or data.get("requete") or "").strip()
    etat = statut()
    chunks = chunks_prets()
    if not chunks:
        return {"sujet": sujet, "resultats": [], "carte": etat.get("etat"),
                "message_final": ("La carte du classement n'est pas encore relevée"
                                  + (f" ({etat.get('erreur')})" if etat.get("erreur") else "")
                                  + "."),
                "a_faire": (f"La carte se construit en tâche de fond. En attendant, cherche "
                            f"par le nom avec `{GESTE_CHERCHER}`.")}
    if not sujet:
        from classement.carte import carte_prete
        return {"carte": carte_prete(), "dossiers": etat.get("dossiers"),
                "fichiers": etat.get("fichiers"), "complet": etat.get("complet"),
                "message_final": (f"Carte du {NOM_STOCKAGE} : {etat.get('dossiers')} dossiers, "
                                  f"{etat.get('fichiers')} fichiers relevés."),
                "a_faire": "Donne un `sujet` (client, chantier, type de pièce) pour savoir où il est rangé."}

    trouves = chercher_dans_la_carte(chunks, sujet)
    lignes = [[t["chemin"].rsplit("/", 1)[-1], t["chemin"], t.get("detail") or ""] for t in trouves]
    resultat = {
        "sujet": sujet, "nombre": len(trouves),
        "resultats": [{"chemin": t["chemin"], "contenu": t.get("detail") or ""} for t in trouves],
        "carte_complete": bool(etat.get("complet")),
    }
    if trouves:
        resultat["bloc_ui"] = {"type": "table", "titre": f"Où c'est classé — {sujet}",
                               "columns": ["Dossier", "Emplacement", "Contenu"], "rows": lignes}
        resultat["bloc_garanti"] = True
        resultat["message_final"] = (f"« {sujet} » : {len(trouves)} emplacement(s) dans le classement"
                                     + ("" if etat.get("complet") else " (relevé partiel)") + ".")
        resultat["a_faire"] = (
            "Les emplacements sont DÉJÀ affichés par un bloc mécanique : ne les recopie pas. "
            f"Pour voir ce qu'un dossier contient, appelle `{GESTE_LISTER}` avec son chemin "
            "EXACT recopié ci-dessus ; pour lire un fichier, ouvre-le ensuite par son chemin. "
            "Ne devine jamais un autre emplacement.")
    else:
        resultat["message_final"] = f"Aucun dossier du classement ne porte « {sujet} » dans son nom."
        resultat["a_faire"] = (
            "Rien dans les NOMS du classement, ce qui ne prouve pas l'absence : retente avec "
            f"UN seul mot, puis `{GESTE_CHERCHER}` (fichiers par nom) et `rechercher_documents` "
            "(le CONTENU des documents).")
    return resultat


SKILLS = {
    "ou_chercher": Declaration(
        fonction=ou_chercher,
        description=(
            "DIT DANS QUEL DOSSIER du classement se trouve un client, un chantier, un "
            "type de pièce (« où sont les CCTP », « le dossier de Martin », « les "
            "photos du chantier X ») — depuis la CARTE du classement relevée en "
            "mémoire, sans parcourir le stockage : instantané. Rend les chemins EXACTS "
            "et ce que chaque dossier contient. À appeler AVANT de parcourir "
            "l'arborescence ou de deviner un emplacement. Sans `sujet` : la carte des "
            "racines."),
        requis=[], optionnels=["sujet"],
        effet="lecture",
        libelle="je regarde où c'est classé"),
}
