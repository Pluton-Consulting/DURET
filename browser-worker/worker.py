"""
Service worker navigateur — FastAPI INTERNE (non exposé publiquement).

Le backend appelle POST /run (non bloquant) ; la tâche s'exécute en fond
(asyncio) et écrit son état dans `browser_tasks`. Le suivi se fait par le backend
directement en base ; /jobs/{id} et /health sont fournis pour debug/monitoring.
"""
import asyncio
import logging

from fastapi import FastAPI
from pydantic import BaseModel

import db
import wconfig
from browser_agent import run_task

logger = logging.getLogger("browser-worker")

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
def _readonly_effectif(demande: bool) -> bool:
    """Le reglage du DEPLOIEMENT est un plafond, pas une valeur par defaut.

    BROWSER_READONLY etait lu (wconfig.py) puis jamais consulte : le worker
    suivait la requete, et la requete vient d'une case a cocher de l'ecran.
    Un administrateur qui posait BROWSER_READONLY=true croyait avoir verrouille
    l'ecriture ; n'importe quel utilisateur la rouvrait d'un clic. Un garde-fou
    qui ne garde rien est pire qu'un garde-fou absent, parce qu'on cesse de
    surveiller ce qu'il est cense proteger.

    Desormais : si le deploiement dit lecture seule, il l'emporte. S'il ne le
    dit pas, la requete decide, comme avant.
    """
    if wconfig.READONLY and not demande:
        logger.warning("Mode ecriture DEMANDE mais refuse : BROWSER_READONLY est actif "
                       "sur ce deploiement. Poser BROWSER_READONLY=false pour l'autoriser.")
        return True
    return demande


async def run(req: RunRequest):
    async def _job():
        try:
            await run_task(
                req.job_id, req.task_prompt, req.allowed_domains,
                req.user_id, ingest=req.ingest, readonly=_readonly_effectif(req.readonly),
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
