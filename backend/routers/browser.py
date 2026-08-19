"""
Router de l'agent de navigation agentique (browser-use).

- POST /api/browser/run    : lance une tâche (perm `run_browser_agent`), après
  validation stricte des domaines contre l'allowlist `BROWSER_ALLOWED_DOMAINS`.
- GET  /api/browser/tasks  : liste les tâches de l'utilisateur (toutes si dashboard global).
- GET  /api/browser/tasks/{id} : détail d'une tâche.
- POST /api/browser/tasks/{id}/cancel : annule une tâche.

L'exécution réelle se fait dans le worker dédié. Par défaut en lecture seule ; en mode
écriture, les actions sensibles passent par la file de validation (HITL, table
`validations`, agent='browser') — garde-fou best-effort, voir browser-worker/README §Sécurité.
"""
import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import has_permission
from security.audit import log_action
from config import settings
from browser_agent import client

logger = logging.getLogger("symbiose.browser.api")
router = APIRouter()


def _row(r) -> dict:
    """Ligne → dict en désérialisant les colonnes JSONB (asyncpg les renvoie en str)."""
    d = dict(r)
    for k in ("result", "structured_output", "payload"):
        if isinstance(d.get(k), str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                d[k] = None
    return d


class RunTaskRequest(BaseModel):
    task: str
    allowed_domains: list[str] = []
    ingest: bool = False
    readonly: bool = True   # False = mode écriture (saisie/clic/soumission) pour cette tâche
    output_schema: Optional[dict] = None


def _allowlist() -> set[str]:
    return {d.strip().lower() for d in settings.browser_allowed_domains.split(",") if d.strip()}


@router.post("/run")
async def run_task(body: RunTaskRequest, current_user: User = Depends(get_current_user)):
    if not settings.browser_agent_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Agent navigateur désactivé (BROWSER_AGENT_ENABLED=false)")
    if not has_permission(current_user.role, "run_browser_agent"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Permission 'run_browser_agent' requise")

    task = (body.task or "").strip()
    if not task:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tâche vide")

    domains = [d.strip().lower() for d in body.allowed_domains if d.strip()]
    if not domains:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Au moins un domaine autorisé est requis")
    allow = _allowlist()
    forbidden = [d for d in domains if d not in allow]
    if forbidden:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Domaines hors allowlist : {', '.join(forbidden)}")

    async with get_db() as conn:
        job_id = await conn.fetchval(
            "INSERT INTO browser_tasks (user_id, status, task_prompt, allowed_domains) "
            "VALUES ($1, 'pending', $2, $3) RETURNING id",
            current_user.id, task, domains,
        )

    try:
        await client.start_task_sur(str(job_id), task, domains, str(current_user.id),
                                    ingest=body.ingest, readonly=body.readonly,
                                    output_schema=body.output_schema)
    except client.NavigateurCoupe as e:
        # COUPÉ N'EST PAS EN PANNE. Que la navigation soit désactivée par
        # réglage ou que le conteneur soit arrêté, c'est une décision
        # d'exploitation : on la dit en français, et on rend 503 (« pas
        # maintenant ») plutôt que 502 (« quelque chose est cassé »).
        async with get_db() as conn:
            await conn.execute(
                "UPDATE browser_tasks SET status='failed', error=$2, updated_at=NOW() WHERE id=$1",
                job_id, "navigation coupée",
            )
        logger.info("Navigation coupée, tâche %s refusée", job_id)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(e))
    except Exception as e:
        async with get_db() as conn:
            await conn.execute(
                "UPDATE browser_tasks SET status='failed', error=$2, updated_at=NOW() WHERE id=$1",
                job_id, f"worker indisponible: {type(e).__name__}",
            )
        logger.warning("Worker navigateur injoignable (job %s) : %s", job_id, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Worker navigateur injoignable")

    await log_action(action="browser_task_started", user_id=str(current_user.id),
                     metadata={"job_id": str(job_id), "domains": domains})
    return {"job_id": str(job_id), "status": "running"}


@router.get("/tasks")
async def list_tasks(current_user: User = Depends(get_current_user)):
    if not has_permission(current_user.role, "run_browser_agent"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    see_all = has_permission(current_user.role, "view_dashboard_global")
    async with get_db() as conn:
        if see_all:
            rows = await conn.fetch(
                "SELECT id, user_id, status, task_prompt, allowed_domains, steps, error, result, "
                "created_at, updated_at FROM browser_tasks ORDER BY created_at DESC LIMIT 100"
            )
        else:
            rows = await conn.fetch(
                "SELECT id, user_id, status, task_prompt, allowed_domains, steps, error, result, "
                "created_at, updated_at FROM browser_tasks WHERE user_id=$1 "
                "ORDER BY created_at DESC LIMIT 100",
                current_user.id,
            )
    return [_row(r) for r in rows]


@router.get("/tasks/{job_id}")
async def get_task(job_id: UUID, current_user: User = Depends(get_current_user)):
    if not has_permission(current_user.role, "run_browser_agent"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM browser_tasks WHERE id=$1", job_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tâche introuvable")
    if row["user_id"] != current_user.id and not has_permission(current_user.role, "view_dashboard_global"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé")
    return _row(row)


@router.post("/tasks/{job_id}/cancel")
async def cancel_task(job_id: UUID, current_user: User = Depends(get_current_user)):
    if not has_permission(current_user.role, "run_browser_agent"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT user_id FROM browser_tasks WHERE id=$1", job_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tâche introuvable")
    if row["user_id"] != current_user.id and not has_permission(current_user.role, "view_dashboard_global"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé")
    try:
        await client.cancel_task(str(job_id))
    except Exception as e:
        logger.warning("Annulation worker échouée (%s) : %s", job_id, e)
        async with get_db() as conn:
            await conn.execute("UPDATE browser_tasks SET status='cancelled', updated_at=NOW() WHERE id=$1", job_id)
    await log_action(action="browser_task_cancelled", user_id=str(current_user.id),
                     metadata={"job_id": str(job_id)})
    return {"job_id": str(job_id), "status": "cancelled"}


@router.get("/apercu/{cle}")
async def apercu_page(cle: str, current_user: User = Depends(get_current_user)):
    """L'aperçu PNG d'une page lue par le navigateur (voir browser/apercus.py)."""
    from fastapi.responses import Response
    from browser.apercus import lire
    octets = lire(cle)
    if not octets:
        raise HTTPException(status_code=404, detail="Aperçu expiré ou inconnu")
    return Response(content=octets, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=3600"})
