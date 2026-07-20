"""
Agent 3 — Superviseur / Auto-apprentissage
Rôle : détecte les requêtes hors champ, génère des skills Python,
       les teste dans un sandbox Daytona, les soumet à validation humaine.
Pipeline : analyze_gap → search_docs → [browser?] → generate_skill → test_skill → submit_validation
Cas d'usage : À implémenter dans une prochaine itération
"""
from langgraph.graph import StateGraph, END
from agents.state import AgentState
from llm.router import get_llm, LLMTier
from sandbox.daytona_client import sandbox_client, SandboxTestResult


# ── Nœuds ────────────────────────────────────────────────────────────

async def analyze_gap_node(state: AgentState) -> dict:
    """Analyse ce qui manque pour répondre à la requête"""
    # TODO: Utiliser Claude Sonnet pour identifier le gap de connaissance
    llm = get_llm(LLMTier.COMPLEX)
    return {"out_of_scope": True}


async def search_existing_docs_node(state: AgentState) -> dict:
    """Recherche RAG des documents métier servant de base au skill à générer."""
    from vectorstore.rag import retrieve_as_context

    contexts = await retrieve_as_context(
        query=state.get("query", ""),
        user_role=state.get("user_role", "direction"),
        top_k=5,
    )
    existing = list(state.get("raw_chunks") or [])
    existing.extend(contexts)
    return {"raw_chunks": existing}


async def browser_node(state: AgentState) -> dict:
    """
    Recherche documentaire externe pour enrichir la génération du skill.
    S'intercale entre search_docs et generate_skill.
    Utilise agent3_research() — outil dédié Agent 3.
    """
    from browser.tools import agent3_research

    result = await agent3_research(
        topic=state.get("query", ""),
        user_id=state.get("user_id", ""),
    )

    existing = list(state.get("raw_chunks") or [])
    if result["success"]:
        existing.append(
            "[SOURCE WEB — documentation externe pour génération du skill]\n"
            + result["content"]
        )

    return {
        "raw_chunks": existing,
        "browser_used": True,
        "browser_sources": result.get("sources", []),
        "browser_content": result.get("content"),
        "browser_was_filtered": result.get("was_filtered", False),
    }


async def generate_skill_node(state: AgentState) -> dict:
    """Claude génère le code Python du skill"""
    # TODO: Construire le prompt avec le gap analysé + docs trouvés + contenu browser
    # Convention : le skill doit exposer run(data: dict) -> dict
    llm = get_llm(LLMTier.COMPLEX)
    return {"skill_generated": "# TODO: generated skill code\ndef run(data: dict) -> dict:\n    return {}"}


async def test_skill_node(state: AgentState) -> dict:
    """Test du skill dans sandbox isolé (Daytona ou subprocess fallback)"""
    skill_code = state.get("skill_generated", "")
    skill_name = state.get("skill_name", "unknown_skill")

    if not skill_code:
        return {
            "skill_test_result": {"passed": False, "error": "Aucun code généré"},
            "skill_confidence": 0.0,
        }

    result: SandboxTestResult = await sandbox_client.test_skill(
        skill_code=skill_code,
        skill_name=skill_name,
        max_execution_seconds=30,
    )

    return {
        "skill_test_result": {
            "passed": result.passed,
            "output": result.output,
            "error": result.error,
            "execution_time_ms": result.execution_time_ms,
            "sandbox_type": result.sandbox_type,
        },
        "skill_confidence": result.confidence_score,
    }


async def submit_for_validation_node(state: AgentState) -> dict:
    """Persiste le skill généré (status='draft') et déclenche la validation humaine."""
    from database.connection import get_db

    skill_name = state.get("skill_name") or f"skill_{(state.get('thread_id') or 'auto')[:8]}"
    skill_code = state.get("skill_generated", "")
    confidence = state.get("skill_confidence", 0.0) or 0.0
    test_result = state.get("skill_test_result") or {}

    try:
        async with get_db() as conn:
            await conn.execute(
                """INSERT INTO skills (name, description, code, status, confidence_score, created_by)
                   VALUES ($1, $2, $3, 'draft', $4, 'agent3')
                   ON CONFLICT (name) DO UPDATE
                       SET code = EXCLUDED.code,
                           confidence_score = EXCLUDED.confidence_score,
                           version = skills.version + 1,
                           status = 'draft',
                           updated_at = NOW()""",
                skill_name,
                (state.get("query") or "")[:500],
                skill_code,
                float(confidence),
            )
    except Exception:
        pass  # la persistance ne doit pas bloquer la boucle d'apprentissage

    return {
        "requires_validation": True,
        "validation_reason": "nouveau skill à valider",
        "validation_payload": {
            "skill_name": skill_name,
            "confidence": confidence,
            "passed": test_result.get("passed"),
            "sandbox_type": test_result.get("sandbox_type"),
        },
    }


# ── Edges conditionnels ───────────────────────────────────────────────

def should_use_browser(state: AgentState) -> str:
    """
    Le browser est le DERNIER RECOURS pour l'Agent 3.
    Il ne se déclenche que si le RAG interne n'a trouvé aucun document
    pouvant servir de base au skill à générer.
    """
    from config import settings

    if state.get("browser_used"):
        return "generate_skill"
    if not settings.browser_enabled:
        return "generate_skill"

    no_internal = len(state.get("raw_chunks") or []) == 0
    return "browser" if no_internal else "generate_skill"


def should_retry_or_submit(state: AgentState) -> str:
    """Edge conditionnel : soumettre si tests OK, sinon soumettre quand même (avec score bas)"""
    # TODO: Implémenter compteur de retries dans l'état (max 3 tentatives)
    return "submit"


# ── Graph ─────────────────────────────────────────────────────────────

def build_agent3_graph():
    graph = StateGraph(AgentState)

    graph.add_node("analyze_gap", analyze_gap_node)
    graph.add_node("search_docs", search_existing_docs_node)
    graph.add_node("browser", browser_node)
    graph.add_node("generate_skill", generate_skill_node)
    graph.add_node("test_skill", test_skill_node)
    graph.add_node("submit_validation", submit_for_validation_node)

    graph.set_entry_point("analyze_gap")
    graph.add_edge("analyze_gap", "search_docs")
    graph.add_conditional_edges(
        "search_docs",
        should_use_browser,
        {"browser": "browser", "generate_skill": "generate_skill"},
    )
    graph.add_edge("browser", "generate_skill")
    graph.add_edge("generate_skill", "test_skill")
    graph.add_conditional_edges(
        "test_skill",
        should_retry_or_submit,
        {"submit": "submit_validation"},
    )
    graph.add_edge("submit_validation", END)

    return graph.compile()


agent3_graph = build_agent3_graph()
