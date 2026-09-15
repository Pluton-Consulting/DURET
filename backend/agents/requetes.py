"""
UNE DEMANDE, UN SEUL TOUR (16/09, audit D-13).

CE QUI ÉTAIT FAUX. L'écran envoie sa demande par WebSocket ; si la socket se
ferme (réseau, veille, changement de page), il la REJOUE en HTTP. Le tour
d'origine, lui, continuait — le serveur ne les reliait pas. Deux tours pour une
demande : deux appels de modèle payés, deux fois les mêmes gestes, et, quand la
demande portait un effet externe, deux cartes d'accord pour le même envoi.

CE QUE FAIT CE MODULE. L'écran fabrique un `request_id` AVANT d'envoyer, et le
garde pour toutes ses reprises. Ici, on l'inscrit une fois par personne : la
seconde arrivée ne relance rien, elle REJOINT le tour déjà en cours (ou rend son
résultat s'il est fini).

`reclamer()` est une écriture conditionnelle : c'est elle qui tranche entre
« c'est moi qui démarre » et « quelqu'un d'autre l'a déjà fait ». Sans la
migration, tout continue comme avant (best-effort, jamais une panne de plus).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("duret.agents.requetes")

ETATS = ("en_cours", "terminee", "echouee")


async def reclamer(user_id, request_id: Optional[str], thread_id: Optional[str] = None) -> dict:
    """{"nouvelle": bool, "etat": …, "thread_id": …} — `nouvelle` dit si C'EST
    NOUS qui démarrons le tour. Sans `request_id` (client ancien), on démarre :
    le comportement d'avant."""
    if not request_id or not user_id:
        return {"nouvelle": True, "etat": None, "thread_id": thread_id}
    from database.connection import get_db, schema_incomplet
    try:
        async with get_db() as conn:
            ligne = await conn.fetchrow(
                """INSERT INTO requetes_chat (user_id, request_id, thread_id, etat)
                   VALUES ($1::uuid, $2, $3, 'en_cours')
                   ON CONFLICT (user_id, request_id) DO NOTHING
                   RETURNING id::text""",
                str(user_id), str(request_id)[:120], str(thread_id or "") or None)
            if ligne:
                return {"nouvelle": True, "etat": "en_cours", "thread_id": thread_id}
            connue = await conn.fetchrow(
                """SELECT etat, thread_id, resultat FROM requetes_chat
                    WHERE user_id = $1::uuid AND request_id = $2""",
                str(user_id), str(request_id)[:120])
        logger.info("Demande %s déjà en cours ou terminée : aucun second tour", str(request_id)[:12])
        return {"nouvelle": False, "etat": (connue or {}).get("etat"),
                "thread_id": (connue or {}).get("thread_id") or thread_id,
                "resultat": (connue or {}).get("resultat")}
    except Exception as e:  # noqa: BLE001
        if not schema_incomplet(e):
            logger.warning("Registre des demandes indisponible (%s)", type(e).__name__)
        return {"nouvelle": True, "etat": None, "thread_id": thread_id}


async def terminer(user_id, request_id: Optional[str], etat: str = "terminee",
                   resultat: Optional[str] = None) -> None:
    """Le tour est fini : la demande porte son état (et, si l'on veut, de quoi
    répondre à une reprise tardive)."""
    if not request_id or not user_id:
        return
    from database.connection import get_db
    try:
        async with get_db() as conn:
            await conn.execute(
                """UPDATE requetes_chat SET etat = $3, resultat = COALESCE($4, resultat),
                       maj_le = NOW()
                     WHERE user_id = $1::uuid AND request_id = $2""",
                str(user_id), str(request_id)[:120], etat,
                (resultat[:4000] if isinstance(resultat, str) else None))
    except Exception:  # noqa: BLE001 — un registre d'appoint ne casse pas un tour
        pass


async def oublier_anciennes(jours: int = 7) -> int:
    """Les demandes d'avant-hier n'ont plus rien à empêcher."""
    from database.connection import get_db
    try:
        async with get_db() as conn:
            fait = await conn.execute(
                "DELETE FROM requetes_chat WHERE cree_le < NOW() - ($1::int * INTERVAL '1 day')",
                max(1, int(jours)))
        return int(str(fait).split()[-1] or 0)
    except Exception:  # noqa: BLE001
        return 0
