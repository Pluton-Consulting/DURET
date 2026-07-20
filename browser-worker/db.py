"""
Accès Postgres du worker (pool asyncpg dédié).

Tables touchées : `browser_tasks` (suivi des tâches), `validations` (demandes
d'approbation HITL, agent='browser'), `audit_log` (journal, INSERT-only).
Décorrélé du backend — aucune dépendance au code FastAPI.
"""
import json
import asyncpg

import wconfig

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    # asyncpg n'accepte que postgresql:// (pas le +asyncpg de style SQLAlchemy).
    dsn = wconfig.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=4)


async def close_pool() -> None:
    if _pool:
        await _pool.close()


# ── browser_tasks ────────────────────────────────────────────────────────
async def update_status(job_id: str, status: str) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE browser_tasks SET status=$2, updated_at=NOW() WHERE id=$1::uuid",
            job_id, status,
        )


async def set_steps(job_id: str, steps: int) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE browser_tasks SET steps=$2, updated_at=NOW() WHERE id=$1::uuid",
            job_id, steps,
        )


async def set_result(job_id: str, status: str, result: dict | None = None,
                     structured: dict | None = None, steps: int | None = None) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE browser_tasks SET status=$2, "
            "result=$3::jsonb, structured_output=$4::jsonb, "
            "steps=COALESCE($5, steps), updated_at=NOW() WHERE id=$1::uuid",
            job_id, status,
            json.dumps(result) if result is not None else None,
            json.dumps(structured) if structured is not None else None,
            steps,
        )


async def set_error(job_id: str, error: str) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE browser_tasks SET status='failed', error=$2, updated_at=NOW() WHERE id=$1::uuid",
            job_id, (error or "")[:1000],
        )


async def get_task(job_id: str) -> dict | None:
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, status, task_prompt, result, structured_output, error, steps, "
            "created_at, updated_at FROM browser_tasks WHERE id=$1::uuid",
            job_id,
        )
        return dict(row) if row else None


# ── validations (HITL, agent='browser') ──────────────────────────────────
async def insert_validation(thread_id: str, user_id: str, reason: str,
                            payload: dict, draft: str | None = None) -> str:
    async with _pool.acquire() as conn:
        vid = await conn.fetchval(
            "INSERT INTO validations (thread_id, user_id, agent, reason, payload, draft, status) "
            "VALUES ($1, $2::uuid, 'browser', $3, $4::jsonb, $5, 'pending') RETURNING id",
            thread_id, user_id, reason, json.dumps(payload), draft,
        )
        return str(vid)


async def poll_validation_status(validation_id: str) -> str | None:
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT status FROM validations WHERE id=$1::uuid", validation_id
        )


async def purge_validation_screenshot(validation_id: str) -> None:
    """Retire la capture d'écran du payload après résolution (PII)."""
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE validations SET payload = payload - 'screenshot' WHERE id=$1::uuid",
            validation_id,
        )


# ── audit_log (INSERT-only, jamais de contenu ni secret) ──────────────────
async def log_audit(action: str, user_id: str | None = None,
                    success: bool = True, metadata: dict | None = None) -> None:
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO audit_log (action, user_id, success, metadata) "
            "VALUES ($1, $2::uuid, $3, $4::jsonb)",
            action, user_id, success, json.dumps(metadata or {}),
        )
