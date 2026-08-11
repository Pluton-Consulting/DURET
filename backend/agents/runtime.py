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
from agents.journal import libelle

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
                   attachment_b64: Optional[str] = None, attachment_mime: Optional[str] = None,
                   attachment_name: Optional[str] = None, attachment_text: Optional[str] = None,
                   trigger_kind: str = "chat") -> dict:
    _mime = attachment_mime or ""
    return {
        "query": query,
        "user_id": user_id,
        "user_role": user_role,
        "has_attachment": has_attachment,
        "attachment_type": ("pdf" if "pdf" in _mime else "image" if _mime.startswith("image") else None),
        "attachment_b64": attachment_b64,
        "attachment_mime": attachment_mime,
        "attachment_name": attachment_name,
        "attachment_text": attachment_text,
        "trigger_kind": trigger_kind,
        "thread_id": thread_id,
        "session_id": thread_id,
        "raw_chunks": [],
        "anonymized_chunks": [],
        # `entity_map` n'est VOLONTAIREMENT pas réinitialisé : la map est cumulative sur
        # le fil (checkpointer), pour qu'une même valeur garde le même placeholder d'un
        # tour à l'autre. La remettre à {} ferait redémarrer la numérotation à 1 et
        # rendrait l'historique masqué incohérent (cf. anonymize_node).
        # Ces deux-là, en revanche, DOIVENT repartir à zéro : sans ça, un tour qui
        # échoue avant le LLM (RGPD fail-closed, erreur RAG) laisse la réponse du tour
        # PRÉCÉDENT dans l'état, et elle est renvoyée comme réponse à la question courante.
        "llm_response": None,
        "final_response": None,
        "turn_placeholders": None,
        # Boucle d'outils : remise à zéro obligatoire à chaque tour, sinon le garde
        # anti-boucle et les résultats du tour précédent survivraient.
        "tool_results": [],
        "tool_iterations": 0,
        "tool_repair_used": False,
        "tools_finished": False,
        "pending_action": None,
        # LE DRAPEAU DE RELANCE AUSSI. Il manquait ici, et c'est ce qui gelait
        # l'assistant : posé lors d'un tour où le modèle avait annoncé sans agir,
        # il SURVIVAIT au tour via le checkpointer. Or `route_apres_llm` ne
        # relance que si le drapeau est bas — donc une fois levé et non
        # redescendu (tour terminé sans action aboutie), le fil entier perdait
        # définitivement sa reprise : le modèle annonçait, personne ne le
        # reprenait, l'utilisateur relisait la même promesse à chaque essai.
        # Vu dans les traces : `relance_annonce: True` dès l'entrée du tour,
        # avant que le modèle ait écrit quoi que ce soit.
        "relance_annonce": False,
        # Idem pour la décision du routeur et la raison d'une sortie de boucle :
        # ces canaux sont en « dernière valeur » et survivent au tour. Sans remise
        # à zéro, un tour hérite du « contexte » de sortie du précédent — et le
        # modèle explique à l'utilisateur une limite qui n'a pas été atteinte.
        "note_sortie": None,
        "besoin_memoire": None,
        "requete_memoire": None,
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
    payload = intr.get("payload") or state.get("validation_payload") or {}
    # L'empreinte du payload est enregistrée AVEC la décision : c'est elle qui
    # permettra à `execute_action` de vérifier que l'action exécutée est bien
    # celle qui a été montrée à l'humain, et pas une autre.
    empreinte = payload.get("payload_hash") if isinstance(payload, dict) else None

    async with get_db() as conn:
        vid = await conn.fetchval(
            """INSERT INTO validations
                   (thread_id, user_id, agent, reason, payload, draft, status, payload_hash)
               VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
               RETURNING id""",
            thread_id,
            user_id,
            intr.get("agent") or state.get("target_agent"),
            intr.get("reason") or state.get("validation_reason"),
            json.dumps(payload),
            intr.get("draft") or _response_from_state(state),
            empreinte,
        )
    return str(vid)


async def run_turn(*, query: str, user_id: str, user_role: str, has_attachment: bool, thread_id: str,
                   attachment_b64: Optional[str] = None, attachment_mime: Optional[str] = None,
                   attachment_name: Optional[str] = None, attachment_text: Optional[str] = None,
                   trigger_kind: str = "chat") -> dict:
    """Exécute un tour de conversation. Peut suspendre (pending_validation)."""
    graph = await get_graph()
    config = _graph_config(thread_id, user_id)

    result = await graph.ainvoke(
        _initial_state(query, user_id, user_role, has_attachment, thread_id,
                       attachment_b64, attachment_mime, attachment_name, attachment_text,
                       trigger_kind), config
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

    # Met à jour la ligne validations. On cible par ID quand on l'a : un même fil
    # peut porter plusieurs validations en attente (une action par tour), et le
    # filtre par thread_id seul en résoudrait plusieurs d'un coup avec UNE décision.
    async with get_db() as conn:
        if validation_id:
            await conn.execute(
                """UPDATE validations
                   SET status = $1, validated_by = $2, resolved_at = NOW()
                   WHERE id = $3::uuid AND status = 'pending'""",
                "approved" if approved else "rejected", validated_by, str(validation_id),
            )
        else:   # compatibilité : anciens appels sans identifiant
            await conn.execute(
                """UPDATE validations
                   SET status = $1, validated_by = $2, resolved_at = NOW()
                   WHERE thread_id = $3 AND status = 'pending'""",
                "approved" if approved else "rejected", validated_by, thread_id,
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
                      attachment_b64: Optional[str] = None, attachment_mime: Optional[str] = None,
                      attachment_name: Optional[str] = None, attachment_text: Optional[str] = None) -> AsyncIterator[dict]:
    """Streame l'exécution nœud-par-nœud (pour push WebSocket temps réel)."""
    graph = await get_graph()
    config = _graph_config(thread_id, user_id)

    # subgraphs=True : remonte AUSSI les sous-étapes internes des agents (recherche mémoire,
    # anonymisation, rédaction, vision…) et pas seulement les gros nœuds (agent1/agent2).
    _flux = graph.astream(
        _initial_state(query, user_id, user_role, has_attachment, thread_id,
                       attachment_b64, attachment_mime, attachment_name, attachment_text),
        config,
        stream_mode="updates",
        subgraphs=True,
    )
    interruption = None
    async for ns, chunk in _flux:
        for node_name, update in chunk.items():
            if node_name == "__interrupt__":
                # Avec subgraphs=True, l'interruption remonte DEUX fois (espace de noms
                # du sous-graphe puis du parent). On ne la signale qu'une seule fois,
                # sinon le front afficherait deux demandes pour une seule décision.
                if interruption is None:
                    interruption = _extract_interrupt({"__interrupt__": update})
                    yield {"type": "validation_required", "node": "human_gate", "data": interruption}
            else:
                # `libelle` dit CE QUE l'assistant fait, en francais. Sans lui
                # l'ecran n'affiche qu'un nom d'etape, et « redaction » pendant
                # quarante secondes n'apprend rien a personne.
                yield {"type": "node", "node": node_name, "data": _safe(update),
                       "libelle": libelle(node_name, update if isinstance(update, dict) else {})}

    snapshot = await graph.aget_state(config)
    state = snapshot.values if isinstance(snapshot.values, dict) else {}
    if snapshot.next:
        # run_turn persiste la validation, pas stream_turn : une demande levée par le
        # WebSocket n'atteignait donc JAMAIS la file de validation. On comble ici.
        validation_id = await _persist_validation(thread_id, user_id, state, interruption)
        # CE QUI EST EN ATTENTE, pas seulement QU'IL Y A une attente. L'écran
        # n'affichait qu'un « ⏳ en attente de validation humaine » : la personne
        # ne savait ni ce qu'elle validait, ni où le faire. On envoie donc le
        # motif et l'action, pour que la décision se prenne dans la conversation
        # où elle a été demandée.
        intr = interruption or {}
        charge = intr.get("payload") or state.get("validation_payload") or {}
        yield {"type": "pending_validation", "thread_id": thread_id,
               "validation_id": validation_id,
               "reason": intr.get("reason") or state.get("validation_reason"),
               "skill": charge.get("skill") if isinstance(charge, dict) else None,
               "args": charge.get("args") if isinstance(charge, dict) else None}
    else:
        yield {"type": "final", "thread_id": thread_id, "response": _response_from_state(state)}


def _safe(update: Any) -> dict:
    """Réduit un update de nœud à un dict JSON-sérialisable minimal."""
    if not isinstance(update, dict):
        return {}
    out = {}
    for k in ("target_agent", "llm_tier", "requires_validation", "out_of_scope",
              "final_response", "llm_response", "model_used", "tool_iterations"):
        if k in update and update[k] is not None:
            out[k] = update[k]
    return out
