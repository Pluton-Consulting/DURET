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
import asyncio
import json
import logging
from typing import Any, AsyncIterator, Optional

from langgraph.types import Command

from agents.checkpointer import get_checkpointer, close_checkpointer
from agents.router import build_main_graph
from database.connection import get_db
from config import settings
from agents.journal import libelle

logger = logging.getLogger("symbiose.runtime")

_graph = None


class FilOccupe(RuntimeError):
    """Un tour tourne déjà sur ce fil, ou il attend une décision humaine."""


# ── UN SEUL TOUR À LA FOIS PAR FIL ───────────────────────────────────
#
# Deux exécutions simultanées sur un même `thread_id` écrivent leurs
# checkpoints l'une sur l'autre : l'historique se corrompt en silence, et une
# reprise ultérieure repart d'un état qui n'a jamais existé. Tout le reste du
# système suppose cet interdit — un fil par tâche différée, un fil par tâche
# planifiée — mais rien ne le FAISAIT respecter.
#
# Les chemins qui pouvaient l'enfreindre, tous vérifiés en revue :
#   - le repli POST du chat, déclenché par un WebSocket lent alors que le tour
#     WS continue côté serveur (le serveur ne voit la déconnexion qu'au prochain
#     envoi, donc pas avant la fin de l'appel au modèle en cours) ;
#   - un nouveau message envoyé sur un fil suspendu au `human_gate`, qui jetait
#     l'interruption et rendait l'approbation ultérieure incohérente ;
#   - deux approbations concurrentes de la même validation.
#
# Le verrou est EN MÉMOIRE, donc mono-processus : c'est déjà l'hypothèse de
# `_VIVANTES` dans la file d'attente. Un déploiement multi-workers demanderait
# un verrou partagé (Postgres advisory lock) — à traiter le jour où il arrive,
# pas à simuler aujourd'hui.
_FILS_EN_COURS: set[str] = set()


class _Verrou:
    """Réserve un fil pour la durée d'un tour. Lève `FilOccupe` s'il est pris."""

    def __init__(self, thread_id: str):
        self.fil = thread_id

    def __enter__(self):
        if self.fil in _FILS_EN_COURS:
            raise FilOccupe(
                "Un traitement est déjà en cours sur cette conversation. "
                "Attendez qu'il se termine, ou lancez votre demande en file "
                "d'attente.")
        _FILS_EN_COURS.add(self.fil)
        return self

    def __exit__(self, *exc):
        _FILS_EN_COURS.discard(self.fil)
        return False


def fil_occupe(thread_id: str) -> bool:
    """Un tour tourne-t-il en ce moment sur ce fil ?"""
    return thread_id in _FILS_EN_COURS


async def fil_suspendu(thread_id: str) -> bool:
    """Le fil attend-il une décision humaine (interrompu au `human_gate`) ?

    Un nouveau tour lancé dessus écraserait l'interruption : la validation
    resterait « en attente » pour toujours, et l'approuver plus tard reprendrait
    un graphe qui n'est plus au point où il s'était arrêté.
    """
    graph = await get_graph()
    try:
        snapshot = await graph.aget_state(_graph_config(thread_id))
    except Exception as e:  # noqa: BLE001
        # ON NE SAIT PAS — donc on REFUSE. Un fil inconnu ne passe pas par ici :
        # `aget_state` rend alors un instantané vide. Ce qui atterrit là, c'est
        # une PANNE de lecture du checkpoint (pool saturé, délai, connexion
        # refusée). Conclure « pas suspendu » lancerait un tour sur un fil arrêté
        # au `human_gate`, jetterait l'interruption, et rendrait l'approbation
        # d'après incohérente — exactement l'interdit que ce garde-fou existe
        # pour faire respecter. Il serait fail-open précisément au moment où il
        # sert : quand l'infrastructure vacille.
        logger.error("Lecture du checkpoint impossible pour %s (%s) — tour refusé",
                     thread_id, e)
        raise FilOccupe(
            "Impossible de vérifier l'état de cette conversation pour le "
            "moment. Réessayez dans quelques instants.") from e
    return bool(getattr(snapshot, "next", None))


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


# UN SEUL GRAPHE, MÊME SOUS UNE RAFALE. `if _graph is None:` suivi d'un `await`
# rend la main à la boucle avant l'affectation : N requêtes concurrentes
# passaient toutes le test et construisaient N graphes et N checkpointers.
#
# Ce n'est pas théorique : `main.py` avale volontairement l'échec de
# l'initialisation au démarrage (« le graphe ne doit pas empêcher l'API de
# démarrer »), donc `_graph` reste à None quand Postgres n'est pas encore prêt —
# et la première rafale de requêtes initialise en parallèle. Conséquences
# mesurées : plusieurs pools ouverts et jamais fermés, et si le repli mémoire
# joue, des historiques de conversation séparés selon le graphe attrapé.
_init = asyncio.Lock()


async def init_runtime() -> None:
    """Compile le graph principal avec le checkpointer (appelé au startup)."""
    global _graph
    if _graph is not None:
        return
    async with _init:
        if _graph is not None:      # re-vérification SOUS le verrou
            return
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
        "versements": 0,
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
    """Exécute un tour de conversation. Peut suspendre (pending_validation).

    Lève `FilOccupe` si un tour tourne déjà sur ce fil, ou s'il attend une
    décision humaine : deux exécutions sur un même fil corrompent l'historique.
    """
    graph = await get_graph()
    config = _graph_config(thread_id, user_id)

    if await fil_suspendu(thread_id):
        raise FilOccupe(
            "Cette conversation attend une décision de votre part sur une "
            "action précédente. Tranchez-la, ou lancez votre demande en file "
            "d'attente.")

    with _Verrou(thread_id):
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
    """Reprend un graph suspendu au human_gate avec la décision humaine.

    Lève `FilOccupe` si un tour tourne déjà sur ce fil : reprendre pendant
    qu'une exécution écrit ses checkpoints donnerait deux graphes concurrents
    sur le même historique.
    """
    graph = await get_graph()
    config = _graph_config(thread_id, validated_by, extra_tags=["resume"])

    # LA DÉCISION S'ENREGISTRE AVANT DE REPRENDRE LE GRAPHE. L'ordre inverse a
    # annulé une action pourtant approuvée : `execute_action_node` s'exécute
    # PENDANT `ainvoke` et relit la base pour y trouver l'empreinte approuvée —
    # or la ligne était encore `pending`, sa mise à jour n'arrivant qu'après la
    # reprise. Vu dans les traces : les deux empreintes identiques dans l'état,
    # la décision bien à « approved », et le nœud qui annule quand même.
    #
    # Écrire d'abord ne fragilise rien : le point d'entrée a déjà vérifié que la
    # ligne était `pending` (409 sinon), et le verrou d'exécution reste
    # l'empreinte — une ligne approuvée dont le payload ne correspond pas
    # n'exécute rien.
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

    # L'identifiant traverse la reprise : `execute_action_node` cible ainsi LA
    # ligne résolue, au lieu de « la dernière approuvée du fil » — un fil de
    # test en porte plusieurs, et la plus récente n'est pas forcément la bonne.
    with _Verrou(thread_id):
        result = await graph.ainvoke(
            Command(resume={"approved": approved, "validated_by": validated_by,
                            "validation_id": str(validation_id) if validation_id else None}),
            config,
        )

        snapshot = await graph.aget_state(config)
    state = snapshot.values if isinstance(snapshot.values, dict) else result

    commun = {
        "thread_id": thread_id,
        "response": _response_from_state(state),
        "agent_used": state.get("target_agent", "agent1"),
        "tokens_in": state.get("tokens_in", 0) or 0,
        "tokens_out": state.get("tokens_out", 0) or 0,
        "cost_eur": state.get("cost_eur", 0.0) or 0.0,
        "model_used": state.get("model_used"),
        "validation_status": "approved" if approved else "rejected",
    }

    # LE GRAPHE S'EST-IL DE NOUVEAU ARRÊTÉ ? Aujourd'hui non : après la porte,
    # le graphe est terminal, aucun nœud atteignable ne peut lever une seconde
    # interruption. Mais l'appelant, lui, a une branche pour ce cas — et une
    # branche qu'aucun code ne peut atteindre finit par être crue vraie. On
    # LIT donc l'état réel plutôt que de retourner « terminé » par principe :
    # si le graphe change un jour, la validation suivante sera persistée au
    # lieu d'être perdue en silence.
    if getattr(snapshot, "next", None):
        suivante = await _persist_validation(
            thread_id, validated_by or "", state, _extract_interrupt(result))
        logger.info("Reprise de %s : une NOUVELLE validation attend (%s)",
                    thread_id, suivante)
        return {"status": "pending_validation", "validation_id": suivante, **commun}

    return {"status": "completed", **commun}


async def stream_turn(*, query: str, user_id: str, user_role: str,
                      has_attachment: bool, thread_id: str,
                      attachment_b64: Optional[str] = None, attachment_mime: Optional[str] = None,
                      attachment_name: Optional[str] = None, attachment_text: Optional[str] = None) -> AsyncIterator[dict]:
    """Streame l'exécution nœud-par-nœud (pour push WebSocket temps réel).

    Lève `FilOccupe` si un tour tourne déjà sur ce fil, ou s'il attend une
    décision humaine — même interdit que `run_turn`, même raison.
    """
    graph = await get_graph()
    config = _graph_config(thread_id, user_id)

    if await fil_suspendu(thread_id):
        raise FilOccupe(
            "Cette conversation attend une décision de votre part sur une "
            "action précédente. Tranchez-la, ou lancez votre demande en file "
            "d'attente.")

    with _Verrou(thread_id):
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
        # CE QUI est en attente, pas seulement QU'IL Y A une attente. L'écran
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
              "final_response", "llm_response", "model_used", "tool_iterations",
              # CE QUE LE SERVEUR SAVAIT ET GARDAIT POUR LUI.
              #
              # Cette liste est une AUTORISATION, pas une dépense : elle ne
              # déclenche aucun calcul et n'ajoute rien au prompt. Chacune de
              # ces valeurs était déjà produite, puis jetée à la porte.
              #
              # `sources_memoire` : les documents d'où vient la réponse. Sans
              #   eux, l'assistant affirme et il faut le croire.
              # `browser_sources` : les pages réellement consultées sur le web.
              # `browser_was_filtered` : une adresse a été écartée par le garde
              #   de sécurité, ce qui explique une réponse incomplète.
              # `tokens_in` / `tokens_out` : le coût réel du tour, jusqu'ici
              #   invisible alors qu'il est mesuré à chaque appel.
              "sources_memoire", "browser_sources", "browser_was_filtered",
              "tokens_in", "tokens_out"):
        if k in update and update[k] is not None:
            out[k] = update[k]
    return out
