"""
Runtime d'orchestration — point d'intégration unique du graph LangGraph.

Expose :
  - init_runtime() / shutdown_runtime()  → cycle de vie (lifespan FastAPI)
  - run_turn(...)      → exécute un tour ; retourne 'completed' ou 'pending_validation'
  - resume_turn(...)   → reprend un graph suspendu (human-in-the-loop) depuis le checkpoint
  - stream_turn(...)   → générateur async d'événements nœud-par-nœud (WebSocket)

Contrat TurnResult (dict) :
  status        : 'completed' | 'pending_validation' | 'error'
  thread_id     : str
  response      : str
  agent_used    : str
  tokens_in/out : int
  cost_eur      : float
  model_used    : Optional[str]
  validation_id : Optional[str]   (si pending_validation)
  validation    : Optional[dict]  (reason/payload/draft, si pending_validation)
"""
import json
import logging
from typing import Any, AsyncIterator, Optional

from langgraph.types import Command

from agents.checkpointer import get_checkpointer, close_checkpointer
from agents.router import build_main_graph
from database.connection import get_db
from config import settings

logger = logging.getLogger("duret.runtime")

_graph = None


def _graph_config(thread_id: str, user_id: Optional[str] = None,
                  extra_tags: Optional[list] = None) -> dict:
    """
    Config d'invocation du graph : thread_id (checkpointer) + tracing Langfuse
    du TOUR COMPLET si l'observabilité est active. Le callback posé ici est propagé
    à tous les nœuds (classify, agents, LLM). La PII est protégée à deux niveaux :
    prompts déjà anonymisés en amont + masque côté client Langfuse.
    """
    cfg: dict = {"configurable": {"thread_id": thread_id}}
    try:
        from observability import trace_config
        tags = ["chat", settings.environment] + (extra_tags or [])
        cfg.update(trace_config(user_id=user_id, thread_id=thread_id, tags=tags))
    except Exception:
        pass
    return cfg


async def init_runtime() -> None:
    """Compile le graph principal avec le checkpointer (appelé au startup)."""
    global _graph
    if _graph is None:
        checkpointer = await get_checkpointer()
        _graph = await build_main_graph(checkpointer)
        logger.info("Runtime LangGraph initialisé")


async def shutdown_runtime() -> None:
    global _graph
    _graph = None
    await close_checkpointer()


async def get_graph():
    if _graph is None:
        await init_runtime()
    return _graph


def _initial_state(query: str, user_id: str, user_role: str, has_attachment: bool, thread_id: str,
                   attachment_b64: Optional[str] = None, attachment_mime: Optional[str] = None) -> dict:
    _mime = attachment_mime or ""
    return {
        "query": query,
        "user_id": user_id,
        "user_role": user_role,
        "has_attachment": has_attachment,
        "attachment_type": ("pdf" if "pdf" in _mime else "image" if _mime.startswith("image") else None),
        "attachment_b64": attachment_b64,
        "attachment_mime": attachment_mime,
        "thread_id": thread_id,
        "session_id": thread_id,
        "raw_chunks": [],
        "anonymized_chunks": [],
        "entity_map": {},
        "out_of_scope": False,
        "browser_needed": False,
        "browser_used": False,
        "browser_was_filtered": False,
        "requires_validation": False,
        "validation_status": None,
        "retry_count": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_eur": 0.0,
        "messages": [],
    }


def _extract_interrupt(result: Any):
    """Récupère le payload d'interrupt (reason/payload/draft) s'il existe."""
    if isinstance(result, dict):
        intr = result.get("__interrupt__")
        if intr:
            first = intr[0] if isinstance(intr, (list, tuple)) else intr
            return getattr(first, "value", first)
    return None


def _response_from_state(state: dict) -> str:
    return (
        state.get("final_response")
        or state.get("llm_response")
        or "Traitement effectué."
    )


async def _persist_validation(thread_id: str, user_id: str, state: dict, intr: Optional[dict]) -> str:
    """Crée une ligne validations (status=pending) et retourne son id."""
    intr = intr or {}
    async with get_db() as conn:
        vid = await conn.fetchval(
            """INSERT INTO validations
                   (thread_id, user_id, agent, reason, payload, draft, status)
               VALUES ($1, $2, $3, $4, $5, $6, 'pending')
               RETURNING id""",
            thread_id,
            user_id,
            intr.get("agent") or state.get("target_agent"),
            intr.get("reason") or state.get("validation_reason"),
            json.dumps(intr.get("payload") or state.get("validation_payload") or {}),
            intr.get("draft") or _response_from_state(state),
        )
    return str(vid)


async def run_turn(*, query: str, user_id: str, user_role: str, has_attachment: bool, thread_id: str,
                   attachment_b64: Optional[str] = None, attachment_mime: Optional[str] = None) -> dict:
    """Exécute un tour de conversation. Peut suspendre (pending_validation)."""
    graph = await get_graph()
    config = _graph_config(thread_id, user_id)

    result = await graph.ainvoke(
        _initial_state(query, user_id, user_role, has_attachment, thread_id,
                       attachment_b64, attachment_mime), config
    )

    snapshot = await graph.aget_state(config)
    paused = bool(snapshot.next)

    state = snapshot.values if isinstance(snapshot.values, dict) else result
    tokens_in = state.get("tokens_in", 0) or 0
    tokens_out = state.get("tokens_out", 0) or 0
    cost_eur = state.get("cost_eur", 0.0) or 0.0
    agent_used = state.get("target_agent", "agent1")
    model_used = state.get("model_used")

    if paused:
        intr = _extract_interrupt(result)
        validation_id = await _persist_validation(thread_id, user_id, state, intr)
        return {
            "status": "pending_validation",
            "thread_id": thread_id,
            "response": (intr or {}).get("draft") or _response_from_state(state),
            "agent_used": agent_used,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_eur": cost_eur,
            "model_used": model_used,
            "validation_id": validation_id,
            "validation": intr,
        }

    return {
        "status": "completed",
        "thread_id": thread_id,
        "response": _response_from_state(state),
        "agent_used": agent_used,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_eur": cost_eur,
        "model_used": model_used,
        "validation_id": None,
        "validation": None,
    }


async def resume_turn(*, thread_id: str, approved: bool, validated_by: Optional[str] = None,
                      validation_id: Optional[str] = None) -> dict:
    """Reprend un graph suspendu au human_gate avec la décision humaine."""
    graph = await get_graph()
    config = _graph_config(thread_id, validated_by, extra_tags=["resume"])

    result = await graph.ainvoke(
        Command(resume={"approved": approved, "validated_by": validated_by}), config
    )

    snapshot = await graph.aget_state(config)
    state = snapshot.values if isinstance(snapshot.values, dict) else result

    # Met à jour la ligne validations
    async with get_db() as conn:
        await conn.execute(
            """UPDATE validations
               SET status = $1, validated_by = $2, resolved_at = NOW()
               WHERE thread_id = $3 AND status = 'pending'""",
            "approved" if approved else "rejected",
            validated_by,
            thread_id,
        )

    return {
        "status": "completed",
        "thread_id": thread_id,
        "response": _response_from_state(state),
        "agent_used": state.get("target_agent", "agent1"),
        "tokens_in": state.get("tokens_in", 0) or 0,
        "tokens_out": state.get("tokens_out", 0) or 0,
        "cost_eur": state.get("cost_eur", 0.0) or 0.0,
        "model_used": state.get("model_used"),
        "validation_status": "approved" if approved else "rejected",
    }


async def stream_turn(*, query: str, user_id: str, user_role: str,
                      has_attachment: bool, thread_id: str,
                      attachment_b64: Optional[str] = None, attachment_mime: Optional[str] = None) -> AsyncIterator[dict]:
    """Streame l'exécution nœud-par-nœud (pour push WebSocket temps réel)."""
    graph = await get_graph()
    config = _graph_config(thread_id, user_id)

    # subgraphs=True : remonte AUSSI les sous-étapes internes des agents (recherche mémoire,
    # anonymisation, rédaction, vision…) et pas seulement les gros nœuds (agent1/agent2).
    async for ns, chunk in graph.astream(
        _initial_state(query, user_id, user_role, has_attachment, thread_id,
                       attachment_b64, attachment_mime),
        config,
        stream_mode="updates",
        subgraphs=True,
    ):
        for node_name, update in chunk.items():
            if node_name == "__interrupt__":
                yield {"type": "validation_required", "node": "human_gate", "data": _extract_interrupt({"__interrupt__": update})}
            else:
                yield {"type": "node", "node": node_name, "data": _safe(update)}

    snapshot = await graph.aget_state(config)
    state = snapshot.values if isinstance(snapshot.values, dict) else {}
    if snapshot.next:
        yield {"type": "pending_validation", "thread_id": thread_id}
    else:
        yield {"type": "final", "thread_id": thread_id, "response": _response_from_state(state)}


def _safe(update: Any) -> dict:
    """Réduit un update de nœud à un dict JSON-sérialisable minimal."""
    if not isinstance(update, dict):
        return {}
    out = {}
    for k in ("target_agent", "llm_tier", "requires_validation", "out_of_scope",
              "final_response", "llm_response", "model_used"):
        if k in update and update[k] is not None:
            out[k] = update[k]
    return out
