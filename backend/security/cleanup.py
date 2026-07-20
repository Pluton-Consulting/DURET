"""
Balayage périodique de sécurité (tâche de fond) :
retire les captures d'écran (PII) restées dans `validations.payload` au-delà du TTL
— filet de sécurité pour les lignes orphelines (worker tué/redémarré pendant l'attente
d'approbation, où la purge en `try/finally` n'a pas pu s'exécuter).
"""
import asyncio
import logging

from config import settings
from database.connection import get_db

logger = logging.getLogger("duret.cleanup")

_task: asyncio.Task | None = None
_stop = False


async def _loop() -> None:
    while not _stop:
        try:
            async with get_db() as conn:
                result = await conn.execute(
                    "UPDATE validations SET payload = payload - 'screenshot' "
                    "WHERE payload ? 'screenshot' "
                    "AND created_at < NOW() - make_interval(mins => $1)",
                    settings.screenshot_ttl_minutes,
                )
            purged = int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0
            if purged:
                logger.info("Balayage TTL : %d capture(s) orpheline(s) purgée(s)", purged)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Balayage TTL captures : %s", e)
        await asyncio.sleep(settings.screenshot_cleanup_interval_s)


async def start_validation_cleanup() -> None:
    global _task, _stop
    _stop = False
    _task = asyncio.create_task(_loop())
    logger.info("Balayage TTL des captures démarré (TTL=%d min)", settings.screenshot_ttl_minutes)


async def stop_validation_cleanup() -> None:
    global _stop
    _stop = True
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
