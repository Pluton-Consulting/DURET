"""
UN EFFET EXTERNE NE SE FAIT QU'UNE FOIS (16/09, audit D-11/S-11).

CE QUI MANQUAIT. L'accord humain est réclamé atomiquement depuis longtemps :
deux personnes ne peuvent pas approuver deux fois la même carte. Mais entre
« approuvé » et « le mail est parti », rien n'était écrit. Un redémarrage au
mauvais moment, une réponse SMTP perdue, et plus personne ne savait si l'envoi
avait eu lieu — la seule façon de « vérifier » était de renvoyer.

CE QUE FAIT CE MODULE. Il tient un registre durable (`operations_externes`,
migration 045) avec DEUX états séparés :

  · la DÉCISION humaine : preparee → approuvee | refusee ;
  · l'EXÉCUTION dans le monde : en_attente → en_cours → reussie | echouee |
    effet_inconnu.

`reclamer()` passe `en_attente` à `en_cours` en UNE écriture conditionnelle :
si deux reprises se déclenchent (reconnexion, tâche de fond, clic), la seconde
ne réclame rien et n'appelle pas le fournisseur.

`effet_inconnu` est le cas honnête : un délai dépassé après l'acceptation ne
prouve ni l'envoi ni l'échec. On ne relance JAMAIS tout seul — on le dit, et la
réconciliation (chercher le message chez le fournisseur) tranche.

SANS LA MIGRATION, TOUT CONTINUE. Chaque fonction est best-effort : si la table
n'existe pas encore, l'opération s'exécute comme avant et le journal le dit. Le
registre ajoute une garantie, il n'ajoute pas une panne.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger("duret.skills.operations")

DECISIONS = ("preparee", "approuvee", "refusee")
EXECUTIONS = ("en_attente", "en_cours", "reussie", "echouee", "effet_inconnu")


def _indisponible(e: Exception) -> bool:
    from database.connection import schema_incomplet
    return schema_incomplet(e)


async def ouvrir(skill: str, user_id, validation_id=None, thread_id=None,
                 payload_hash: Optional[str] = None, effet: str = "externe") -> Optional[str]:
    """Inscrit l'opération (ou retrouve celle de cette validation). Rend son id."""
    from database.connection import get_db
    try:
        async with get_db() as conn:
            if validation_id:
                connue = await conn.fetchval(
                    "SELECT id::text FROM operations_externes WHERE validation_id = $1::uuid",
                    str(validation_id))
                if connue:
                    return connue
            return await conn.fetchval(
                """INSERT INTO operations_externes
                       (validation_id, user_id, thread_id, skill, effet, payload_hash, decision)
                   VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, 'approuvee')
                   RETURNING id::text""",
                str(validation_id) if validation_id else None,
                str(user_id) if user_id else None, str(thread_id or "") or None,
                skill, effet, payload_hash)
    except Exception as e:  # noqa: BLE001
        if not _indisponible(e):
            logger.warning("Registre des opérations indisponible (%s)", type(e).__name__)
        else:
            logger.info("Migration 045 absente : l'effet externe s'exécute sans registre.")
        return None


async def reclamer(operation_id: Optional[str]) -> bool:
    """Passe l'opération à « en_cours » — et rend False si quelqu'un l'a déjà
    prise (ou si elle est déjà finie). C'est CE refus qui empêche un second
    envoi après une reprise."""
    if not operation_id:
        return True                     # sans registre, on garde le comportement d'avant
    from database.connection import get_db
    try:
        async with get_db() as conn:
            pris = await conn.fetchval(
                """UPDATE operations_externes SET execution = 'en_cours', maj_le = NOW()
                    WHERE id = $1::uuid AND execution = 'en_attente'
                RETURNING id::text""", str(operation_id))
        return bool(pris)
    except Exception as e:  # noqa: BLE001
        logger.warning("Opération %s non réclamée (%s) : exécution quand même",
                       str(operation_id)[:8], type(e).__name__)
        return True


async def _etat(operation_id: Optional[str], execution: str, recu=None, erreur=None) -> None:
    if not operation_id:
        return
    from database.connection import get_db
    try:
        async with get_db() as conn:
            await conn.execute(
                """UPDATE operations_externes
                      SET execution = $2, recu = COALESCE($3::jsonb, recu),
                          erreur = COALESCE($4, erreur), maj_le = NOW()
                    WHERE id = $1::uuid""",
                str(operation_id), execution,
                json.dumps(recu, ensure_ascii=False, default=str) if recu is not None else None,
                (str(erreur)[:500] if erreur else None))
    except Exception as e:  # noqa: BLE001
        logger.warning("État %s non écrit pour l'opération %s (%s)", execution,
                       str(operation_id)[:8], type(e).__name__)


async def reussie(operation_id, recu=None) -> None:
    await _etat(operation_id, "reussie", recu=recu)


async def echouee(operation_id, erreur) -> None:
    await _etat(operation_id, "echouee", erreur=erreur)


async def effet_inconnu(operation_id, erreur) -> None:
    """Ni preuve d'envoi, ni preuve d'échec. On l'écrit, et on ne relance pas."""
    await _etat(operation_id, "effet_inconnu", erreur=erreur)
    logger.warning("Opération %s : EFFET INCONNU (%s) — aucune relance automatique",
                   str(operation_id or "")[:8], str(erreur)[:120])


def ambigu(e: BaseException) -> bool:
    """Cette panne laisse-t-elle un doute sur l'effet ? Un délai dépassé ou une
    connexion coupée APRÈS l'envoi ne prouvent rien ; un refus explicite du
    fournisseur (adresse invalide, droit manquant), si."""
    import asyncio as _asyncio
    if isinstance(e, (_asyncio.TimeoutError, TimeoutError, ConnectionError, ConnectionResetError)):
        return True
    texte = str(e).lower()
    return any(mot in texte for mot in ("timeout", "timed out", "connection reset",
                                        "connexion", "temporarily unavailable", "502", "503", "504"))


async def en_attente_de_verification(user_id=None, limite: int = 20) -> list:
    """Les opérations dont l'effet reste inconnu : ce que l'écran doit dire
    « à vérifier », et ce que la réconciliation doit examiner."""
    from database.connection import get_db
    try:
        async with get_db() as conn:
            lignes = await conn.fetch(
                """SELECT id::text, skill, thread_id, erreur, cree_le
                     FROM operations_externes
                    WHERE execution = 'effet_inconnu'
                      AND ($1::uuid IS NULL OR user_id = $1::uuid)
                    ORDER BY cree_le DESC LIMIT $2""",
                str(user_id) if user_id else None, max(1, int(limite)))
        return [dict(l) for l in lignes]
    except Exception:  # noqa: BLE001
        return []
