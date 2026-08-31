"""
Skill natif : rechercher dans la mémoire d'entreprise.

Avant, la recherche documentaire tournait AVANT chaque appel au modèle, quoi
qu'on lui dise. Un « bonjour » déclenchait donc une recherche vectorielle, une
passe d'anonymisation sur les résultats, et un préambule « aucun document
trouvé » qui poussait le modèle à répondre à côté.

Ici, c'est le MODÈLE qui décide : il reçoit le message, et n'appelle cet outil
que si la demande porte réellement sur des données de l'entreprise. Deux gains :
les échanges conversationnels deviennent immédiats, et le modèle peut relancer
une recherche avec de meilleurs termes s'il n'a rien trouvé du premier coup.

Effet `lecture` : ne modifie rien. Le cloisonnement reste entier — la recherche
est faite avec les droits de l'appelant, et ne peut remonter que les boîtes mail
auxquelles il a accès.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, status

logger = logging.getLogger("duret.skills.documents")

MAX_RESULTATS = 6
# Jusqu'à vingt DOCUMENTS par page : « tous les comptes rendus qui parlent de
# drainage » ne se lit pas six par six. Au-delà, on pagine (`page`).
MAX_LIMITE = 20
# Budget de caractères d'une page d'extraits : elle doit atteindre le modèle
# entière (résultat généreux, 12 000) avec ses en-têtes.
BUDGET_EXTRAITS = 9000


class RechercheInvalide(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _entier(valeur, defaut: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(valeur)))
    except (TypeError, ValueError):
        return defaut


async def rechercher_documents(data: dict, user) -> dict:
    """Cherche dans la mémoire d'entreprise, avec les droits de l'appelant.

    Petite ou énorme : `limite` documents par page (6 par défaut, 20 au plus),
    `page` pour la suite, `fichier` pour ne chercher que dans un nom de
    fichier. Le résultat est GROUPÉ par document (avec le nombre de morceaux
    qui correspondent dans chacun), les extraits sont CENTRÉS sur les termes
    cherchés, et le compte total est EXACT — c'est lui qu'on cite pour
    « combien de documents parlent de … ».
    """
    requete = (data.get("requete") or data.get("query") or "").strip()
    if not requete:
        raise RechercheInvalide("Précisez ce que vous cherchez (paramètre « requete »).")

    types = data.get("types") or data.get("type_source")
    if isinstance(types, str):
        types = [t.strip() for t in types.split(",") if t.strip()]
    limite = _entier(data.get("limite") or data.get("nombre"), MAX_RESULTATS, 1, MAX_LIMITE)
    page = _entier(data.get("page"), 1, 1, 1000)
    fichier = str(data.get("fichier") or data.get("source") or data.get("nom_fichier") or "").strip() or None

    from vectorstore.rag import rechercher
    from vectorstore.fusion import fenetre, budget_extrait
    from mail.authorization import boites_par_id

    # Cloisonnement : la recherche ne remonte que les boîtes de CET utilisateur.
    # En cas de souci, aucune boîte — jamais de repli permissif.
    try:
        boites = await boites_par_id(str(user.id))
    except Exception:  # noqa: BLE001
        boites = []

    try:
        trouve = await rechercher(
            requete, getattr(user, "role", "terrain"),
            source_types=types or None, mailboxes=boites,
            limite=limite, page=page, fichier=fichier,
        )
    except Exception as e:  # noqa: BLE001 - une recherche en échec n'est pas une panne
        logger.warning("Recherche « %s » échouée : %s", requete[:60], e)
        return {"requete": requete, "resultats": [], "nombre": 0,
                "message": "La recherche a échoué, la mémoire est momentanément indisponible."}

    documents = trouve.get("documents") or []
    total_documents = int(trouve.get("total_documents") or len(documents))
    pages = max(1, -(-len(documents) // limite))
    page_docs = documents[(page - 1) * limite: page * limite]

    if not page_docs:
        if page > 1 and documents:
            return {"requete": requete, "resultats": [], "nombre": 0, "page": page, "pages": pages,
                    "total_documents": total_documents,
                    "message": f"Il n'y a que {pages} page(s) de résultats pour cette recherche.",
                    "a_faire": f"La page {page} n'existe pas : la dernière est la page {pages}."}
        # Une recherche vide ne dit RIEN sur le contenu global de la mémoire.
        # Sans cette distinction, le modèle conclut « la mémoire ne contient
        # aucun mail » alors qu'elle en contient des dizaines qui n'ont
        # simplement pas atteint le seuil de similarité — une affirmation fausse
        # sur l'état du système, bien plus grave qu'un « je ne trouve pas ».
        inventaire, appris = await _inventaire(getattr(user, "role", ""))
        return {
            "requete": requete, "resultats": [], "nombre": 0,
            "inventaire_memoire": inventaire,
            # DEUX PUBLICS, DEUX CHAMPS. `message` est ce que la personne LIT
            # quand le modèle ne rédige pas ; `a_faire` est la consigne au
            # modèle. Confondus, ils ont mis « Ne dis donc PAS qu'elle est
            # vide » et un nom de skill sous les yeux d'un utilisateur, à la
            # question 8 du cahier de démo (27/08).
            #
            # L'INVENTAIRE RESTE CÔTÉ HUMAIN : savoir que la mémoire contient
            # 1 398 devis alors que la recherche ne rend rien, c'est une
            # information, pas de la tuyauterie.
            "message": (
                "Aucun document ne correspond à cette recherche."
                + ("" if not inventaire else
                   f" La mémoire contient pourtant : {inventaire}.")),
            "a_faire": (
                "La mémoire est effectivement vide pour les types consultés : "
                "tu peux le dire." if not inventaire else
                "Ne dis PAS que la mémoire est vide : dis que tu n'as rien trouvé "
                "sur ce point précis. "
                + ("Des connaissances DÉJÀ APPRISES existent : appelle "
                   "`connaissances_acquises` pour les lire. NE PROPOSE PAS de lancer "
                   "une campagne d'enrichissement, elle a déjà tourné."
                   if appris else
                   "Propose des termes plus concrets (un nom de client, un numéro "
                   "de dossier, une période).")),
        }

    # Les extraits d'une page se partagent un budget : longs quand ils sont
    # peu, courts quand ils sont vingt — et CENTRÉS sur les termes cherchés.
    longueur = budget_extrait(sum(len(d.get("extraits") or []) for d in page_docs), BUDGET_EXTRAITS)
    resultats = []
    for d in page_docs:
        extraits = [{"morceau": e.get("morceau"), "texte": fenetre(e.get("texte") or "", requete, longueur)}
                    for e in (d.get("extraits") or [])]
        resultats.append({
            "source": d.get("source"), "type": d.get("type"),
            "morceaux_correspondants": d.get("morceaux_correspondants"),
            "morceaux_total": d.get("morceaux_total"),
            # `extrait` : le meilleur, pour les lecteurs qui n'en attendent qu'un.
            "extrait": extraits[0]["texte"] if extraits else "",
            "extraits": extraits,
        })

    compte = (f"{total_documents} document(s) correspondent à « {requete} »"
              + (f" dans les types {', '.join(types)}" if types else "")
              + (f" (fichiers « {fichier} »)" if fichier else "")
              + (f" ; page {page} sur {pages}, {len(resultats)} document(s) détaillé(s)."
                 if total_documents > len(resultats) else ", tous détaillés ci-dessous."))
    suite = page < pages
    return {
        "requete": requete, "nombre": len(resultats),
        "total_documents": total_documents,
        "total_morceaux": trouve.get("total_morceaux"),
        "page": page, "pages": pages, "limite": limite,
        "compte": compte,
        # La PAGE SUIVANTE, mécanique : le modèle n'a rien à calculer.
        "pour_continuer": (
            f"Pour les {limite} documents SUIVANTS, rappelle rechercher_documents avec les "
            f"mêmes paramètres et page={page + 1}."
            if suite else None),
        "a_faire": (
            "Commence par le COMPTE, dans ces mots : « " + compte + " ». Chaque extrait est "
            "une FENÊTRE sur le document, centrée sur les termes cherchés : cite la source "
            "(champ `source`) quand tu t'appuies dessus. "
            + ("Le détail ne couvre pas tout : dis-le, et propose la page suivante ou des "
               "termes plus précis. " if suite else "")),
        "resultats": resultats,
    }


async def _inventaire(role: str = "") -> tuple[str, bool]:
    """Ce que la mémoire contient réellement, par type de source.

    Un simple comptage, pas une recherche : c'est la seule façon de distinguer
    « je n'ai rien trouvé » de « il n'y a rien ». Ne lève jamais — un inventaire
    indisponible rend une chaîne vide, et le modèle reste prudent.

    Le comptage est FILTRÉ par rôle : annoncer « la mémoire contient 55
    apprentissages » à quelqu'un qui n'a pas le droit de les lire renseigne déjà
    sur ce qui existe. On ne compte que ce que la personne pourrait ouvrir.

    Rend aussi un booléen : des connaissances APPRISES sont-elles disponibles ?
    Sans lui, le modèle conseille de lancer une campagne d'enrichissement qui a
    déjà tourné — constaté en production, campagne terminée depuis peu.
    """
    try:
        from database.connection import get_db
        from security.acces import niveaux_visibles
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT source_type, COUNT(DISTINCT source_id) AS n "
                "FROM documents WHERE access_level = ANY($1::text[]) "
                "GROUP BY source_type ORDER BY n DESC LIMIT 12",
                sorted(niveaux_visibles(role)))
    except Exception as e:  # noqa: BLE001
        logger.info("Inventaire de la mémoire indisponible : %s", e)
        return "", False
    appris = any(l["source_type"] in ("apprentissage", "procedure") and l["n"]
                 for l in lignes)
    return ", ".join(f"{l['n']} {l['source_type']}" for l in lignes if l["n"]) or "", appris
