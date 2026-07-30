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


class RechercheInvalide(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


async def rechercher_documents(data: dict, user) -> dict:
    """Cherche dans la mémoire d'entreprise, avec les droits de l'appelant."""
    requete = (data.get("requete") or data.get("query") or "").strip()
    if not requete:
        raise RechercheInvalide("Précisez ce que vous cherchez (paramètre « requete »).")

    types = data.get("types") or data.get("type_source")
    if isinstance(types, str):
        types = [t.strip() for t in types.split(",") if t.strip()]

    from vectorstore.rag import retrieve
    from mail.authorization import boites_par_id

    # Cloisonnement : la recherche ne remonte que les boîtes de CET utilisateur.
    # En cas de souci, aucune boîte — jamais de repli permissif.
    try:
        boites = await boites_par_id(str(user.id))
    except Exception:  # noqa: BLE001
        boites = []

    try:
        trouves = await retrieve(
            requete,
            getattr(user, "role", "terrain"),
            source_types=types or None,
            top_k=MAX_RESULTATS,
            mailboxes=boites,
        )
    except Exception as e:  # noqa: BLE001 - une recherche en échec n'est pas une panne
        logger.warning("Recherche « %s » échouée : %s", requete[:60], e)
        return {"requete": requete, "resultats": [], "nombre": 0,
                "message": "La recherche a échoué, la mémoire est momentanément indisponible."}

    from optim.tokens import trim_chunks
    contenus = trim_chunks([c.get("content") or "" for c in trouves])

    resultats = []
    for chunk, contenu in zip(trouves, contenus):
        resultats.append({
            "source": chunk.get("source_filename") or chunk.get("source_id"),
            "type": chunk.get("source_type"),
            "extrait": contenu,
        })

    if not resultats:
        return {"requete": requete, "resultats": [], "nombre": 0,
                "message": ("Aucun document ne correspond. Si la formulation peut être "
                            "améliorée, relance une recherche avec d'autres termes ; "
                            "sinon, dis simplement que la mémoire ne contient rien "
                            "là-dessus.")}

    return {"requete": requete, "nombre": len(resultats), "resultats": resultats}
