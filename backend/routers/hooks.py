"""
Webhooks de déclenchement — le SEUL point d'entrée non authentifié par JWT.

Modèle de sécurité, en trois idées :

  1. **Le corps de la requête n'a AUCUNE autorité.** On n'y lit ni consigne, ni
     nom de skill, ni identité. Ce que la tâche fait a été décidé à sa création
     par un utilisateur authentifié. Un webhook ne peut que DÉCLENCHER une tâche
     déjà définie — jamais en décrire une nouvelle. C'est ce qui empêche un
     appelant de transformer un déclencheur en exécution arbitraire.

  2. **Signature HMAC** sur `horodatage + "." + corps brut`, avec une fenêtre de
     cinq minutes. Le secret ne transite donc jamais sur le réseau, et une
     requête capturée devient inutilisable passé ce délai.

  3. **Clé d'idempotence** en contrainte d'unicité : rejouer une requête valide
     ne crée pas de seconde exécution.

Les réponses d'erreur sont volontairement IDENTIQUES (« signature invalide »)
que la tâche existe ou non : sonder les identifiants ne doit rien apprendre.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, status

from database.connection import get_db
from security.audit import log_action

logger = logging.getLogger("duret.hooks")
router = APIRouter()

FENETRE_S = 300     # tolérance d'horloge et de latence, en secondes


def _refus() -> HTTPException:
    """Message unique : ne rien révéler sur l'existence d'une tâche."""
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                         detail="Signature invalide.")


@router.post("/{task_id}")
async def declencher(task_id: str, request: Request,
                     x_signature: Optional[str] = Header(default=None),
                     x_timestamp: Optional[str] = Header(default=None),
                     x_idempotency_key: Optional[str] = Header(default=None)):
    """Déclenche une tâche configurée en mode webhook."""
    corps = await request.body()

    if not x_signature or not x_timestamp:
        raise _refus()

    try:
        async with get_db() as conn:
            tache = await conn.fetchrow(
                """SELECT id, user_id, webhook_secret, enabled
                   FROM agent_tasks
                   WHERE id = $1::uuid AND trigger_kind = 'webhook'""", task_id)
    except Exception:
        raise _refus()

    if not tache or not tache["webhook_secret"] or not tache["enabled"]:
        raise _refus()

    # Anti-rejeu : hors fenêtre, la requête est refusée même si sa signature est
    # correcte — c'est ce qui rend une capture réseau inexploitable plus tard.
    try:
        ecart = abs(time.time() - float(x_timestamp))
    except (TypeError, ValueError):
        raise _refus()
    if ecart > FENETRE_S:
        await log_action(action="task_triggered", success=False, trigger_type="webhook",
                         trigger_id=str(task_id), metadata={"motif": "horodatage hors fenêtre"})
        raise _refus()

    attendu = hmac.new(tache["webhook_secret"].encode("utf-8"),
                       x_timestamp.encode("utf-8") + b"." + corps,
                       hashlib.sha256).hexdigest()
    if not hmac.compare_digest(attendu, x_signature):
        await log_action(action="task_triggered", success=False, trigger_type="webhook",
                         trigger_id=str(task_id), metadata={"motif": "signature"})
        raise _refus()

    # Idempotence : une même clé ne crée qu'une exécution (contrainte UNIQUE).
    async with get_db() as conn:
        run = await conn.fetchrow(
            """INSERT INTO agent_task_runs (task_id, user_id, status, trigger_kind, idempotency_key)
               VALUES ($1::uuid, $2, 'pending', 'webhook', $3)
               ON CONFLICT (idempotency_key) DO NOTHING
               RETURNING id""",
            task_id, tache["user_id"], x_idempotency_key)

    if run is None:
        logger.info("Webhook %s : rejeu ignoré (clé d'idempotence déjà vue)", task_id)
        return {"ok": True, "run_id": None, "message": "Déclenchement déjà enregistré."}

    await log_action(action="task_triggered", on_behalf_of=str(tache["user_id"]),
                     trigger_type="webhook", trigger_id=str(run["id"]),
                     metadata={"task": str(task_id)})
    return {"ok": True, "run_id": str(run["id"])}
