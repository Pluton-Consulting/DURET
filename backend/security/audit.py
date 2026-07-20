"""
Système d'audit immuable — INSERT uniquement, jamais UPDATE ni DELETE.
Appelé sur chaque action significative : login, chat_request, skill_created, etc.
"""
import json
from typing import Optional
from database.connection import get_db


async def log_action(
    action: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    model_used: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_eur: float = 0.0,
    duration_ms: Optional[int] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    metadata: dict = {},
) -> None:
    """
    Enregistre une action dans l'audit log.
    Ne fait que des INSERT — jamais d'UPDATE.
    Ne logue jamais le contenu des messages utilisateurs, uniquement les métadonnées.
    """
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO audit_log (
                user_id, action, agent_id, model_used,
                tokens_in, tokens_out, cost_eur, duration_ms,
                success, error_message, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            user_id,
            action,
            agent_id,
            model_used,
            tokens_in,
            tokens_out,
            cost_eur,
            duration_ms,
            success,
            error_message,
            json.dumps(metadata),
        )
