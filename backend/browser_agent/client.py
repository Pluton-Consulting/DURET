"""
Client HTTP (non bloquant) vers le worker navigateur interne.

Le backend ne fait que déclencher/annuler des tâches ; le suivi se lit directement
en base (`browser_tasks`). Aucune dépendance à Playwright côté backend.
"""
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger("duret.browser.client")


async def start_task(job_id: str, task_prompt: str, allowed_domains: list[str],
                     user_id: str, ingest: bool = False, readonly: bool = True,
                     output_schema: Optional[dict] = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{settings.browser_worker_url}/run",
            json={
                "job_id": job_id,
                "task_prompt": task_prompt,
                "allowed_domains": allowed_domains,
                "user_id": user_id,
                "ingest": ingest,
                "readonly": readonly,
                "output_schema": output_schema,
            },
        )
        r.raise_for_status()
        return r.json()


async def cancel_task(job_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{settings.browser_worker_url}/jobs/{job_id}/cancel")
        r.raise_for_status()
        return r.json()
