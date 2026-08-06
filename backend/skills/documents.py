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
        # Une recherche vide ne dit RIEN sur le contenu global de la mémoire.
        # Sans cette distinction, le modèle conclut « la mémoire ne contient
        # aucun mail » alors qu'elle en contient des dizaines qui n'ont
        # simplement pas atteint le seuil de similarité — une affirmation fausse
        # sur l'état du système, bien plus grave qu'un « je ne trouve pas ».
        inventaire, appris = await _inventaire(getattr(user, "role", ""))
        return {
            "requete": requete, "resultats": [], "nombre": 0,
            "inventaire_memoire": inventaire,
            "message": (
                "Aucun document ne correspond à CETTE recherche. "
                + ("La mémoire est effectivement vide pour les types consultés : "
                   "tu peux le dire." if not inventaire else
                   f"La mémoire contient pourtant : {inventaire}. "
                   "Ne dis donc PAS qu'elle est vide : dis que tu n'as rien trouvé "
                   "sur ce point précis. "
                   + ("Des connaissances DÉJÀ APPRISES existent : appelle "
                      "`connaissances_acquises` pour les lire. NE PROPOSE PAS de lancer "
                      "une campagne d'enrichissement, elle a déjà tourné."
                      if appris else
                      "Propose des termes plus concrets (un nom de client, un numéro "
                      "de dossier, une période)."))),
        }

    return {"requete": requete, "nombre": len(resultats), "resultats": resultats}


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
