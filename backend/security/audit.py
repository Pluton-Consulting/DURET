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
    metadata: Optional[dict] = None,
    on_behalf_of: Optional[str] = None,   # identité RÉELLE de l'exécution (tâche autonome)
    trigger_type: Optional[str] = None,   # 'chat' | 'schedule' | 'webhook'
    trigger_id: Optional[str] = None,     # thread, tâche planifiée, appel entrant
) -> None:
    """
    Enregistre une action dans l'audit log.
    Ne fait que des INSERT — jamais d'UPDATE.
    Ne logue jamais le contenu des messages utilisateurs, uniquement les métadonnées.
    """
    # Traçabilité des exécutions autonomes. Rangée dans `metadata` (JSONB, déjà
    # interrogeable) plutôt qu'en colonnes dédiées : aucune migration, aucun risque
    # de dérive de schéma, et la question « qui a déclenché quoi, au nom de qui »
    # se répond par un simple filtre JSONB.
    metadata = dict(metadata or {})
    for cle, valeur in (("on_behalf_of", on_behalf_of),
                        ("trigger_type", trigger_type),
                        ("trigger_id", trigger_id)):
        if valeur is not None:
            metadata[cle] = str(valeur)

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
