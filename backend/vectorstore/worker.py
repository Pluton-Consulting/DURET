"""
Worker de vectorisation — draine la file `embedding_jobs`.

Tourne en tâche de fond dans le backend (démarré au lifespan). Récupère les chunks
en attente, calcule leurs embeddings (fournisseur configuré), remplit
`documents.embedding` et marque les jobs terminés.

Comportement si le fournisseur d'embeddings est indisponible (clé absente / panne) :
back-off SANS consommer d'essais → le backlog se draine tout seul dès que la clé
est ajoutée. Un chunk qui échoue alors que le fournisseur marche consomme un essai
(mark_job_failed → 'failed' après max_attempts), pour ne pas bloquer la file.
"""
import asyncio
import logging

from config import settings
from vectorstore.client import vectorstore
from vectorstore.embeddings import embed_texts

logger = logging.getLogger("duret.vectorworker")

_task: asyncio.Task | None = None
_stop = False


async def _loop() -> None:
    global _stop
    interval = settings.embedding_worker_interval_s
    while not _stop:
        try:
            jobs = await vectorstore.get_pending_embedding_jobs(limit=settings.embedding_worker_batch)
            if not jobs:
                await asyncio.sleep(interval)
                continue

            vectors = await embed_texts([j["content"] for j in jobs])
            any_ok = any(v is not None for v in vectors)
            done = 0
            for job, vec in zip(jobs, vectors):
                if vec is not None:
                    await vectorstore.mark_job_completed(job["job_id"], vec)
                    done += 1
                elif any_ok:
                    # Le fournisseur répond mais ce chunk a échoué → consomme un essai.
                    await vectorstore.mark_job_failed(job["job_id"], "embedding indisponible pour ce chunk")

            if done:
                logger.info("Vectorisation : %d/%d chunks", done, len(jobs))

            if not any_ok:
                # Fournisseur indisponible : back-off long, aucun essai consommé.
                await asyncio.sleep(max(interval, 30))
            else:
                await asyncio.sleep(1)  # continue à drainer le backlog
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Worker vectorisation : %s", e)
            await asyncio.sleep(max(interval, 15))


async def start_embedding_worker() -> None:
    global _task, _stop
    if not settings.embedding_worker_enabled:
        logger.info("Worker de vectorisation désactivé (embedding_worker_enabled=false)")
        return
    _stop = False
    _task = asyncio.create_task(_loop())
    logger.info("Worker de vectorisation démarré (fournisseur=%s)", settings.embedding_provider)


async def stop_embedding_worker() -> None:
    global _stop
    _stop = True
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
