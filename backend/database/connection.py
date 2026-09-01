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


def schema_incomplet(e: BaseException) -> bool:
    """L'erreur vient-elle d'une migration NON APPLIQUÉE (table ou colonne
    absente), plutôt que d'une vraie panne ?

    POURQUOI CETTE FONCTION EXISTE (01/09). Le code part sur le VPS par
    `pluton deployer`, les migrations s'appliquent à la main : entre les deux,
    le backend tourne du code neuf sur une base ancienne. Une route qui lit une
    colonne pas encore créée rendait alors un HTTP 500 nu — l'écran affichait
    « HTTP 500 » sans dire lequel des deux gestes manquait, et la personne
    devant l'écran n'avait aucun moyen de le deviner.

    Ce n'est PAS une excuse pour avaler l'erreur : l'appelant doit répondre en
    NOMMANT la migration qui manque. Une dégradation muette serait pire que le
    500, parce qu'elle ferait croire à une absence de données.
    """
    try:
        import asyncpg
        if isinstance(e, (asyncpg.UndefinedColumnError,
                          asyncpg.UndefinedTableError)):
            return True
    except ImportError:
        # Le pilote n'est pas là (un banc hors conteneur) : la reconnaissance
        # par le TEXTE suffit, et c'est elle qui compte de toute façon — le
        # pool enveloppe parfois l'erreur dans un autre type.
        pass
    texte = str(e).lower()
    return ("does not exist" in texte
            and ("column" in texte or "relation" in texte or "table" in texte))
