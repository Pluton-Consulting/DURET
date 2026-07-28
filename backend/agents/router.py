"""
Routeur LangGraph principal
Analyse la requête entrante et dispatche vers le bon agent (A1/A2/A3).
Human-in-the-loop : nœud `human_gate` qui suspend le graph via interrupt()
quand une validation humaine est requise — l'état est persisté par le checkpointer,
reprise via runtime.resume_turn().
"""
import datetime
import logging

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt

from agents.state import AgentState
from agents.agent1 import agent1_graph
from agents.agent2 import agent2_graph
from agents.agent3 import agent3_graph
from llm.router import classify_request_tier, LLMTier
from database.connection import get_db
from security.rbac import SCHEDULE_EXEMPT_ROLES
from config import settings
from fastapi import HTTPException

logger = logging.getLogger("duret.router")


async def classify_node(state: AgentState) -> dict:
    """Nœud 1 : classification — quel agent, quel palier LLM."""
    query = state["query"]
    has_attachment = state.get("has_attachment", False)
    tier = classify_request_tier(query, has_attachment)

    # La vision (agent2) ne sert qu'aux IMAGES et aux PDF sans texte (plans, photos,
    # scans). Un Excel, un Word ou un CSV a déjà été converti en texte en amont :
    # l'envoyer à un modèle de vision n'aurait aucun sens. Il part donc chez agent1,
    # son contenu étant injecté dans le contexte comme un document de la mémoire.
    if has_attachment and not state.get("attachment_text"):
        target = "agent2"
        tier = LLMTier.COMPLEX
    else:
        target = "agent1"

    return {"target_agent": target, "llm_tier": tier.value}


async def check_schedule_node(state: AgentState) -> dict:
    """
    Nœud 2 : vérification plage horaire (8h–18h par défaut).
    super_admin / direction exemptés ; bypass_schedule individuel ; plage par user.
    """
    user_role = state.get("user_role", "")
    if user_role in SCHEDULE_EXEMPT_ROLES:
        return {}

    user_id = state.get("user_id")
    start_hour = settings.access_start_hour
    end_hour = settings.access_end_hour
    bypass = False

    if user_id:
        async with get_db() as conn:
            row = await conn.fetchrow(
                """SELECT bypass_schedule, schedule_start_hour, schedule_end_hour
                   FROM users WHERE id = $1::uuid""",
                user_id,
            )
            gc = await conn.fetchrow("SELECT schedule_start_hour, schedule_end_hour FROM global_config WHERE id = 1")
        if gc:
            start_hour = gc["schedule_start_hour"]
            end_hour = gc["schedule_end_hour"]
        if row:
            bypass = bool(row["bypass_schedule"])
            if row["schedule_start_hour"] is not None:
                start_hour = row["schedule_start_hour"]
            if row["schedule_end_hour"] is not None:
                end_hour = row["schedule_end_hour"]

    if bypass:
        return {}

    now = datetime.datetime.now()
    if not (start_hour <= now.hour < end_hour):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Accès refusé — {now.hour}h{now.minute:02d}. "
                f"Plage autorisée : {start_hour}h00–{end_hour}h00."
            ),
        )
    return {}


async def dispatch_agent1(state: AgentState, config=None) -> dict:
    # config propagé => l'exécution du sous-graphe (et son appel LLM) est tracée
    # dans le MÊME arbre Langfuse que le tour complet.
    return await agent1_graph.ainvoke(state, config)


async def dispatch_agent2(state: AgentState, config=None) -> dict:
    return await agent2_graph.ainvoke(state, config)


async def dispatch_agent3(state: AgentState, config=None) -> dict:
    return await agent3_graph.ainvoke(state, config)


async def human_gate_node(state: AgentState) -> dict:
    """
    Human-in-the-loop : si une validation est requise, suspend le graph.
    `interrupt()` persiste l'état et rend la main ; la reprise fournit la décision
    {"approved": bool, "validated_by": str} via runtime.resume_turn().
    """
    if not state.get("requires_validation"):
        return {}

    decision = interrupt({
        "reason": state.get("validation_reason"),
        "payload": state.get("validation_payload"),
        "agent": state.get("target_agent"),
        "draft": state.get("final_response") or state.get("llm_response"),
    })

    approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
    validated_by = decision.get("validated_by") if isinstance(decision, dict) else None

    return {
        "validation_status": "approved" if approved else "rejected",
        "validated_by": validated_by,
        "requires_validation": False,
    }


def route_to_agent(state: AgentState) -> str:
    """Edge conditionnel principal — out_of_scope force l'Agent 3."""
    if state.get("out_of_scope", False):
        return "agent3"
    target = state.get("target_agent", "agent1")
    return "agent2" if target == "agent2" else "agent1"


async def build_main_graph(checkpointer):
    """Construit le graph principal avec checkpointing (persistance par thread_id)."""
    graph = StateGraph(AgentState)

    graph.add_node("classify", classify_node)
    graph.add_node("check_schedule", check_schedule_node)
    graph.add_node("agent1", dispatch_agent1)
    graph.add_node("agent2", dispatch_agent2)
    graph.add_node("agent3", dispatch_agent3)
    graph.add_node("human_gate", human_gate_node)

    graph.set_entry_point("classify")
    graph.add_edge("classify", "check_schedule")
    graph.add_conditional_edges(
        "check_schedule",
        route_to_agent,
        {"agent1": "agent1", "agent2": "agent2", "agent3": "agent3"},
    )
    graph.add_edge("agent1", "human_gate")
    graph.add_edge("agent2", "human_gate")
    graph.add_edge("agent3", "human_gate")
    graph.add_edge("human_gate", END)

    return graph.compile(checkpointer=checkpointer)
