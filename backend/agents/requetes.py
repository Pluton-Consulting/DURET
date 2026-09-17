"""
UNE DEMANDE, UN SEUL TOUR (16/09, audit D-13/S-13).

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
migration ou si la base est indisponible, une demande identifiée est refusée :
lancer sans registre rendrait possible une double exécution.
"""
from __future__ import annotations

import logging
import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4
import json
from typing import Optional

logger = logging.getLogger("duret.agents.requetes")

PROPRIETAIRE = uuid4().hex

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
                """INSERT INTO requetes_chat (user_id, request_id, thread_id, etat, proprietaire)
                   VALUES ($1::uuid, $2, $3, 'en_cours', $4)
                   ON CONFLICT (user_id, request_id) DO NOTHING
                   RETURNING id::text""",
                str(user_id), str(request_id)[:120], str(thread_id or "") or None, PROPRIETAIRE)
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
        return {"nouvelle": False, "etat": "echouee", "thread_id": thread_id,
                "resultat": {"status": "error", "response": "Le registre des demandes est indisponible. Aucun nouveau traitement n’a été lancé ; vérifiez l’historique avant de réessayer."}}


async def terminer(user_id, request_id: Optional[str], etat: str = "terminee",
                   resultat=None) -> None:
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
                     WHERE user_id = $1::uuid AND request_id = $2
                       AND etat = 'en_cours' AND (proprietaire = $5 OR proprietaire IS NULL)""",
                str(user_id), str(request_id)[:120], etat,
                (json.dumps(resultat, ensure_ascii=False, default=str) if isinstance(resultat, dict)
                 else resultat if isinstance(resultat, str) else None), PROPRIETAIRE)
    except Exception:  # noqa: BLE001 — un registre d'appoint ne casse pas un tour
        pass


# L'ÉTAPE COURANTE D'UNE DEMANDE (17/09). Une socket perdue (téléphone en veille,
# changement de réseau) fait passer l'écran au SONDAGE de la demande ; or le sondage
# ne rendait que « toujours en cours ». L'écran restait figé sur la dernière étape
# reçue — « je cherche ce nom sur le Drive », dix minutes durant — alors que le
# serveur en était à produire l'Excel. La personne a cru le tour mort, a rechargé,
# a renvoyé, et a reçu un refus qui ressemblait à une panne.
# En mémoire du processus, comme `_REPRISES` côté validations : l'étape ne vaut que
# pendant le tour, et un redémarrage tue le tour avec elle. Aucun contenu de
# message n'y entre : un nom de nœud, le libellé « je … » déjà montré à l'écran.
_ETAPES: dict[str, dict] = {}
_ETAPES_MAX = 500


def noter_etape(request_id, node=None, libelle=None, skill=None) -> None:
    """Retient l'étape que la socket vient d'annoncer. Ne lève jamais."""
    try:
        if not request_id:
            return
        cle = str(request_id)[:120]
        avant = _ETAPES.get(cle) or {}
        if len(_ETAPES) >= _ETAPES_MAX and cle not in _ETAPES:
            _ETAPES.pop(next(iter(_ETAPES)), None)
        # Un nœud sans libellé laisse le libellé PRÉCÉDENT, comme à l'écran.
        _ETAPES[cle] = {"node": str(node or avant.get("node") or ""),
                        "libelle": str(libelle or avant.get("libelle") or "")[:200],
                        "skill": str(skill or "")[:80]}
    except Exception:  # noqa: BLE001 — un affichage ne casse jamais un tour
        pass


def oublier_etape(request_id) -> None:
    _ETAPES.pop(str(request_id or "")[:120], None)


def reponse_de_reprise(demande: dict) -> dict:
    """Une reprise reçoit le résultat acquis, jamais une bulle vide."""
    if demande.get("etat") in ("terminee", "echouee"):
        brut = demande.get("resultat")
        try:
            resultat = json.loads(brut) if isinstance(brut, str) else brut
        except (ValueError, TypeError):
            resultat = {"response": brut}
        if not isinstance(resultat, dict):
            resultat = {"response": "Ce traitement est terminé. Son résultat est à retrouver dans l'historique du fil."}
        return {**resultat, "thread_id": demande.get("thread_id"), "reprise": False}
    return {"response": None, "thread_id": demande.get("thread_id"), "reprise": True,
            "etat": demande.get("etat"), "message": "Le même traitement est toujours en cours.",
            "etape": _ETAPES.get(str(demande.get("request_id") or "")[:120])}


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


async def consulter(user_id, request_id: str) -> dict | None:
    """Lecture authentifiée d'une demande ; ne réserve et ne relance rien."""
    from database.connection import get_db
    async with get_db() as conn:
        # Un processus mort ne bat plus. Ne jamais reprendre automatiquement
        # une intention dont une partie a pu produire un effet externe.
        await conn.execute("""UPDATE requetes_chat SET etat='echouee', maj_le=NOW(), resultat=$3
            WHERE user_id=$1::uuid AND request_id=$2 AND etat='en_cours'
              AND maj_le < NOW() - INTERVAL '120 seconds'""",
            str(user_id), request_id, json.dumps({"status": "error", "response":
                "Le traitement a été interrompu. Vérifiez l’historique et les actions déjà effectuées avant de relancer."}, ensure_ascii=False))
        ligne = await conn.fetchrow("""SELECT etat, thread_id, resultat FROM requetes_chat
            WHERE user_id=$1::uuid AND request_id=$2""", str(user_id), request_id)
    # L'identifiant accompagne la ligne : c'est par lui que `reponse_de_reprise`
    # retrouve l'étape courante du tour.
    return {**dict(ligne), "request_id": request_id} if ligne else None


@asynccontextmanager
async def suivre(user_id, request_id):
    """Signe de vie pendant un tour, y compris quand sa socket est fermée."""
    if not request_id or not user_id:
        yield
        return
    parent = asyncio.current_task()
    async def battre():
        from database.connection import get_db
        import time
        dernier = time.monotonic()
        while True:
            await asyncio.sleep(15)
            try:
                async with get_db() as conn:
                    fait = await conn.fetchval("""UPDATE requetes_chat SET maj_le=NOW()
                        WHERE user_id=$1::uuid AND request_id=$2 AND etat='en_cours'
                          AND proprietaire=$3 RETURNING id""", str(user_id), str(request_id)[:120], PROPRIETAIRE)
                if not fait:
                    async with get_db() as conn:
                        etat = await conn.fetchval("SELECT etat FROM requetes_chat WHERE user_id=$1::uuid AND request_id=$2", str(user_id), str(request_id)[:120])
                    # UN REGISTRE D'APPOINT NE TUE PAS UN TOUR VIVANT (17/09). Ce
                    # battement annulait le tour quand sa ligne avait été marquée
                    # « échouée » par une lecture voisine (120 s sans battement :
                    # il suffit d'un pool de connexions occupé par une rédaction
                    # de fond). Le tour pouvait être au milieu d'une action. On
                    # le dit au journal, et on le laisse finir : sa réponse
                    # entre dans l'historique de toute façon.
                    if etat != "terminee":
                        logger.warning("Demande %s : battement perdu (état %s) — le tour continue",
                                       str(request_id)[:12], etat)
                    return
                dernier = time.monotonic()
            except Exception:
                if time.monotonic() - dernier > 75:
                    logger.warning("Demande %s : registre injoignable depuis 75 s — le tour continue",
                                   str(request_id)[:12])
                    return
    tache = asyncio.create_task(battre())
    try:
        yield
    finally:
        tache.cancel()
        try:
            await tache
        except asyncio.CancelledError:
            pass
