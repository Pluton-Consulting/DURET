"""
Service worker navigateur — FastAPI INTERNE (non exposé publiquement).

Le backend appelle POST /run (non bloquant) ; la tâche s'exécute en fond
(asyncio) et écrit son état dans `browser_tasks`. Le suivi se fait par le backend
directement en base ; /jobs/{id} et /health sont fournis pour debug/monitoring.
"""
import asyncio

from fastapi import FastAPI
from pydantic import BaseModel

import db
from browser_agent import run_task

app = FastAPI(title="Duret & Sols Browser Worker")

_running: dict[str, asyncio.Task] = {}


class RunRequest(BaseModel):
    job_id: str
    task_prompt: str
    allowed_domains: list[str]
    user_id: str
    ingest: bool = False
    readonly: bool = True
    output_schema: dict | None = None


@app.on_event("startup")
async def _startup():
    await db.init_pool()


@app.on_event("shutdown")
async def _shutdown():
    await db.close_pool()


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/run")
async def run(req: RunRequest):
    async def _job():
        try:
            await run_task(
                req.job_id, req.task_prompt, req.allowed_domains,
                req.user_id, ingest=req.ingest, readonly=req.readonly,
                output_schema=req.output_schema,
            )
        except asyncio.CancelledError:
            await db.update_status(req.job_id, "cancelled")
        except Exception as e:
            await db.set_error(req.job_id, type(e).__name__)  # message générique (pas de fuite d'URL/hôte)
        finally:
            _running.pop(req.job_id, None)

    _running[req.job_id] = asyncio.create_task(_job())
    return {"job_id": req.job_id, "status": "running"}


@app.get("/jobs/{job_id}")
async def job(job_id: str):
    return await db.get_task(job_id) or {"error": "introuvable"}


@app.post("/jobs/{job_id}/cancel")
async def cancel(job_id: str):
    task = _running.get(job_id)
    if task and not task.done():
        task.cancel()
    await db.update_status(job_id, "cancelled")
    return {"job_id": job_id, "status": "cancelled"}
