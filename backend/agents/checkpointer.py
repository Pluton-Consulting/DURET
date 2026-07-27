"""
Checkpointer LangGraph — persistance de l'état des conversations par thread_id.

AsyncPostgresSaver (psycopg3 pool) en prod : reprise sur erreur, human-in-the-loop
durable même après redémarrage du process.
Fallback automatique sur MemorySaver si le setup Postgres échoue (dép/clé/DB absente).
"""
import logging
from typing import Optional

from config import settings

logger = logging.getLogger("duret.checkpointer")

_checkpointer = None
_pool = None


def _psycopg_dsn() -> str:
    """DSN compatible psycopg3 (retire le préfixe SQLAlchemy +asyncpg)."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def get_checkpointer():
    """
    Retourne le checkpointer partagé (singleton).
    Tente AsyncPostgresSaver ; retombe sur MemorySaver en cas d'échec.
    """
    global _checkpointer, _pool
    if _checkpointer is not None:
        return _checkpointer

    if settings.checkpointer_postgres:
        try:
            from psycopg_pool import AsyncConnectionPool
            from psycopg.rows import dict_row
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            _pool = AsyncConnectionPool(
                conninfo=_psycopg_dsn(),
                max_size=10,
                open=False,
                kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
            )
            await _pool.open(wait=True, timeout=10)
            saver = AsyncPostgresSaver(_pool)
            await saver.setup()
            _checkpointer = saver
            logger.info("Checkpointer : AsyncPostgresSaver actif")
            return _checkpointer
        except Exception as e:
            # CRITICAL et non warning : l'historique de conversation vit dans le
            # checkpoint. Sur MemorySaver, il est perdu à chaque redémarrage du
            # conteneur ET n'est pas partagé entre workers uvicorn — l'assistant
            # « oublie tout » sans autre symptôme visible. Ce message est le seul
            # moyen de diagnostiquer ce mode dégradé.
            logger.critical(
                "AsyncPostgresSaver INDISPONIBLE (%s) — repli sur MemorySaver : la mémoire "
                "de conversation ne survivra PAS à un redémarrage. Vérifiez DATABASE_URL "
                "et la dépendance langgraph-checkpoint-postgres.", e,
            )
            if _pool is not None:
                try:
                    await _pool.close()
                except Exception:
                    pass
                _pool = None

    from langgraph.checkpoint.memory import MemorySaver
    _checkpointer = MemorySaver()
    logger.critical("Checkpointer : MemorySaver — mémoire de conversation NON persistante")
    return _checkpointer


async def close_checkpointer() -> None:
    """Ferme le pool psycopg au shutdown de l'app."""
    global _pool, _checkpointer
    if _pool is not None:
        try:
            await _pool.close()
        except Exception:
            pass
        _pool = None
    _checkpointer = None
