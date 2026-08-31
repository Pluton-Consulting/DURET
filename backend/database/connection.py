from contextlib import asynccontextmanager
from typing import AsyncGenerator
import asyncpg
from config import settings

_pool: asyncpg.Pool | None = None


async def init_db() -> None:
    global _pool
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    # 16 connexions : le chat, le worker d'embeddings, les campagnes et les
    # synchronisations se partagent le pool — à 10, une campagne et deux tours
    # suffisaient à faire attendre le troisième. `command_timeout` : une
    # requête qui dure trois minutes est une requête pendue, pas une grosse
    # recherche (les plus lourdes, 50 000 lignes, tiennent en secondes) ;
    # sans lui, un tour attendait pour toujours (31/08).
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=16,
                                      command_timeout=180)


@asynccontextmanager
async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    if _pool is None:
        raise RuntimeError("Database pool not initialized: init_db() not called")
    async with _pool.acquire() as conn:
        yield conn


@asynccontextmanager
async def get_rls_db(user_id: str, role: str) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Connexion avec contexte RLS initialisé (app.current_user_id + app.current_role).

    IMPORTANT : les set_config sont transaction-local (3e arg = true). En mode
    autocommit asyncpg, chaque statement est sa propre transaction — le contexte
    serait perdu avant la requête. On englobe donc tout dans UNE transaction
    explicite : le contexte persiste pour toutes les requêtes du bloc, puis se
    réinitialise automatiquement en fin de transaction (aucune fuite vers le pool).
    """
    async with get_db() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_user_id', $1, true)", user_id)
            await conn.execute("SELECT set_config('app.current_role', $1, true)", role)
            yield conn
