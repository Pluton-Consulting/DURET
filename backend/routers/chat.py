import time
import secrets
import uuid
import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from auth.dependencies import get_current_user
from auth.jwt_handler import decode_access_token
from database.models import User
from database.connection import get_db, get_rls_db
from security.rbac import has_permission, SCHEDULE_EXEMPT_ROLES
from security.audit import log_action
from agents import runtime
from config import settings

router = APIRouter()


class ChatRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None
    has_attachment: bool = False
    attachment_type: Optional[str] = None
    attachment_b64: Optional[str] = None      # image/PDF encodé base64 (Agent 2 vision)
    attachment_mime: Optional[str] = None      # 'image/jpeg', 'application/pdf', ...


async def _check_schedule(current_user: User) -> None:
    """Vérifie la plage horaire. Lève 403 si hors plage."""
    if current_user.role in SCHEDULE_EXEMPT_ROLES:
        return

    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT bypass_schedule, schedule_start_hour, schedule_end_hour FROM users WHERE id = $1",
            current_user.id,
        )
        gc = await conn.fetchrow("SELECT schedule_start_hour, schedule_end_hour FROM global_config WHERE id = 1")

    if row and row["bypass_schedule"]:
        return

    g_start = gc["schedule_start_hour"] if gc else settings.access_start_hour
    g_end   = gc["schedule_end_hour"]   if gc else settings.access_end_hour
    start_hour = row["schedule_start_hour"] if (row and row["schedule_start_hour"] is not None) else g_start
    end_hour   = row["schedule_end_hour"]   if (row and row["schedule_end_hour"]   is not None) else g_end

    now = datetime.datetime.now()
    if not (start_hour <= now.hour < end_hour):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Accès refusé — {now.hour}h{now.minute:02d}. Plage autorisée : {start_hour}h00–{end_hour}h00.",
        )


async def _check_quota(current_user: User) -> None:
    """Vérifie le quota mensuel via connexion RLS-aware. Lève 429 si dépassé."""
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        limit_row = await conn.fetchrow(
            "SELECT monthly_limit FROM role_quota_config WHERE role = $1",
            current_user.role,
        )
        monthly_limit = limit_row["monthly_limit"] if limit_row else None
        if monthly_limit is None:
            return
        used = await conn.fetchval(
            """SELECT COALESCE(SUM(request_count), 0)
               FROM api_usage_daily
               WHERE user_id = $1 AND date >= date_trunc('month', CURRENT_DATE)""",
            current_user.id,
        )

    if used >= monthly_limit:
        await log_action(
            action="quota_exceeded",
            user_id=str(current_user.id),
            metadata={"monthly_limit": monthly_limit, "used": int(used)},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Quota mensuel atteint ({monthly_limit} requêtes). Contactez votre responsable.",
        )


async def _increment_usage(current_user: User, tokens: int = 0, cost: float = 0.0) -> None:
    """Incrémente api_usage_daily avec contexte RLS."""
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        await conn.execute(
            """INSERT INTO api_usage_daily (user_id, date, request_count, tokens_total, cost_eur)
               VALUES ($1, CURRENT_DATE, 1, $2, $3)
               ON CONFLICT (user_id, date) DO UPDATE
                   SET request_count = api_usage_daily.request_count + 1,
                       tokens_total  = api_usage_daily.tokens_total  + $2,
                       cost_eur      = api_usage_daily.cost_eur      + $3""",
            current_user.id, tokens, cost,
        )


async def _claim_thread(current_user: User, thread_id: str, query: str,
                        agent_used: str = "agent1") -> str:
    """Réserve le thread pour cet utilisateur et retourne sa clé primaire.

    Fait AUSSI office de contrôle d'appartenance, et doit donc être appelé AVANT
    d'exécuter le tour : le `thread_id` vient du client (localStorage / URL du
    WebSocket) et les tables de checkpoint LangGraph n'ont ni RLS ni `user_id`.
    Sans ce contrôle, n'importe quel compte authentifié pourrait faire charger le
    checkpoint d'autrui — et depuis que l'historique de conversation y est
    persisté, en lire le contenu.

    Distingue les trois cas sans dépendre de la sémantique d'erreur RLS :
      * fil inexistant        -> l'INSERT réussit et renvoie l'id ;
      * fil existant et mien  -> conflit, puis le SELECT sous RLS le retrouve ;
      * fil d'un autre        -> conflit, et le SELECT sous RLS ne voit rien -> 403.
    """
    title = (query[:60] + "…") if len(query) > 60 else query
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        pk = await conn.fetchval(
            """INSERT INTO threads (langgraph_thread_id, user_id, title, agent_type)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (langgraph_thread_id) DO NOTHING
               RETURNING id""",
            thread_id, current_user.id, title, agent_used,
        )
        if pk is None:
            # Filtre explicite sur user_id : la policy RLS de `threads` accorde la
            # visibilité de TOUS les fils aux rôles super_admin/direction. Sans ce
            # AND, un tel compte passerait le contrôle sur le fil de n'importe qui,
            # reprendrait sa conversation et lirait sa mémoire. La visibilité
            # administrative (lecture via /threads) reste inchangée : ici, on décide
            # qui a le droit de POURSUIVRE un fil, et ce n'est que son propriétaire.
            pk = await conn.fetchval(
                "SELECT id FROM threads WHERE langgraph_thread_id = $1 AND user_id = $2",
                thread_id, current_user.id,
            )
            if pk is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Ce fil de conversation ne vous appartient pas.",
                )
            await conn.execute("UPDATE threads SET updated_at = NOW() WHERE id = $1", pk)
    return str(pk)


async def _persist_messages(current_user: User, thread_pk: str,
                            user_content: str, assistant_content: str) -> None:
    """Enregistre l'échange dans `messages` (historique rechargeable côté frontend).

    `messages.thread_id` est une FK vers `threads.id` (UUID), pas vers
    `langgraph_thread_id` : on passe donc la clé primaire renvoyée par
    `_claim_thread`. RLS forcée sur la table -> connexion RLS obligatoire.
    Best-effort : une écriture d'historique ne doit jamais faire échouer la réponse.
    """
    try:
        async with get_rls_db(str(current_user.id), current_user.role) as conn:
            await conn.executemany(
                "INSERT INTO messages (thread_id, role, content) VALUES ($1, $2, $3)",
                [(uuid.UUID(thread_pk), "user", user_content or ""),
                 (uuid.UUID(thread_pk), "assistant", assistant_content or "")],
            )
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("duret.chat").warning("Persistance des messages échouée : %s", e)


@router.post("/")
async def chat(body: ChatRequest, current_user: User = Depends(get_current_user)):
    if not has_permission(current_user.role, "chat_agent1"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    await _check_schedule(current_user)
    await _check_quota(current_user)

    start = time.monotonic()
    thread_id = body.thread_id or str(uuid.uuid4())
    # Réservation + contrôle d'appartenance AVANT le tour : run_turn charge le
    # checkpoint LangGraph (qui contient désormais l'historique de conversation).
    thread_pk = await _claim_thread(current_user, thread_id, body.query)
    success = True
    error_msg: Optional[str] = None

    try:
        result = await runtime.run_turn(
            query=body.query,
            user_id=str(current_user.id),
            user_role=current_user.role,
            has_attachment=body.has_attachment or bool(body.attachment_b64),
            thread_id=thread_id,
            attachment_b64=body.attachment_b64,
            attachment_mime=body.attachment_mime,
        )
    except HTTPException:
        raise
    except Exception as e:
        success = False
        error_msg = str(e)
        result = {
            "status": "error", "thread_id": thread_id,
            "response": "Une erreur est survenue — veuillez réessayer.",
            "agent_used": "agent1", "tokens_in": 0, "tokens_out": 0,
            "cost_eur": 0.0, "model_used": None, "validation_id": None,
        }

    tokens_in = result.get("tokens_in", 0)
    tokens_out = result.get("tokens_out", 0)
    cost_eur = result.get("cost_eur", 0.0)
    agent_used = result.get("agent_used", "agent1")
    duration_ms = int((time.monotonic() - start) * 1000)

    await _persist_messages(current_user, thread_pk, body.query, result.get("response") or "")
    await _increment_usage(current_user, tokens=tokens_in + tokens_out, cost=cost_eur)
    await log_action(
        action="chat_request",
        user_id=str(current_user.id),
        agent_id=agent_used,
        model_used=result.get("model_used"),
        success=success,
        error_message=error_msg,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_eur=cost_eur,
    )

    return {
        "thread_id": thread_id,
        "response": result.get("response"),
        "agent_used": agent_used,
        "status": result.get("status", "completed"),
        "validation_id": result.get("validation_id"),
        "validation": result.get("validation"),
    }


@router.get("/threads")
async def list_threads(current_user: User = Depends(get_current_user)):
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch(
            "SELECT * FROM threads WHERE user_id = $1 ORDER BY updated_at DESC",
            current_user.id,
        )
        return [dict(row) for row in rows]


@router.get("/threads/{thread_id}/messages")
async def get_thread_messages(thread_id: str, current_user: User = Depends(get_current_user)):
    """Historique des messages d'un thread (RLS : uniquement les siens)."""
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch(
            """SELECT m.id, m.role, m.content, m.metadata, m.created_at
               FROM messages m
               JOIN threads t ON t.id = m.thread_id
               WHERE t.langgraph_thread_id = $1
               ORDER BY m.created_at ASC""",
            thread_id,
        )
        return [dict(row) for row in rows]


# ── Tickets WebSocket éphémères (évitent de passer le JWT dans l'URL du WS) ──
# Le JWT en query string finit dans les logs (uvicorn/nginx) et devient rejouable.
# À la place : le client échange son JWT (en-tête Authorization) contre un ticket
# court à usage unique (~30 s) via POST /ws-ticket, puis ouvre le WS avec ?ticket=.
# Store en mémoire (OK car uvicorn mono-worker ; à externaliser si scaling multi-worker).
_WS_TICKETS: dict[str, tuple[str, float]] = {}   # ticket -> (user_id, expiry_monotonic)
_WS_TICKET_TTL_S = 30


@router.post("/ws-ticket")
async def create_ws_ticket(current_user: User = Depends(get_current_user)):
    """Émet un ticket éphémère à usage unique pour ouvrir le WebSocket chat."""
    now = time.monotonic()
    for k in [k for k, (_, exp) in _WS_TICKETS.items() if exp < now]:  # purge opportuniste
        _WS_TICKETS.pop(k, None)
    ticket = secrets.token_urlsafe(24)
    _WS_TICKETS[ticket] = (str(current_user.id), now + _WS_TICKET_TTL_S)
    return {"ticket": ticket}


async def _ws_authenticate(websocket: WebSocket) -> Optional[User]:
    """Authentifie le WebSocket via un ticket éphémère à usage unique (?ticket=)."""
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        return None
    entry = _WS_TICKETS.pop(ticket, None)   # usage unique : consommé quoi qu'il arrive
    if not entry:
        return None
    user_id, exp = entry
    if time.monotonic() > exp:
        return None
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1::uuid AND actif = true", user_id)
    return User(**dict(row)) if row else None


@router.websocket("/ws/{thread_id}")
async def chat_ws(websocket: WebSocket, thread_id: str):
    """
    Streaming temps réel : le client envoie une requête JSON {query, has_attachment},
    le serveur pousse les événements nœud-par-nœud puis la réponse finale.
    Auth via ?ticket=<ticket éphémère> (obtenu par POST /api/chat/ws-ticket).
    """
    await websocket.accept()
    user = await _ws_authenticate(websocket)
    if user is None:
        await websocket.send_json({"type": "error", "detail": "Non authentifié"})
        await websocket.close(code=1008)
        return

    if not has_permission(user.role, "chat_agent1"):
        await websocket.send_json({"type": "error", "detail": "Permission refusée"})
        await websocket.close(code=1008)
        return

    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("query", "")
            if not query:
                continue

            try:
                await _check_schedule(user)
                await _check_quota(user)
            except HTTPException as e:
                await websocket.send_json({"type": "error", "detail": e.detail})
                continue

            start = time.monotonic()
            tokens = 0
            agent_used = "agent1"
            # Réservation + contrôle d'appartenance AVANT le tour : le thread_id vient
            # de l'URL du WebSocket, et stream_turn charge le checkpoint (historique).
            try:
                thread_pk = await _claim_thread(user, thread_id, query)
            except HTTPException as e:
                await websocket.send_json({"type": "error", "detail": e.detail})
                continue

            final_response = ""
            try:
                async for event in runtime.stream_turn(
                    query=query,
                    user_id=str(user.id),
                    user_role=user.role,
                    has_attachment=data.get("has_attachment", False) or bool(data.get("attachment_b64")),
                    thread_id=thread_id,
                    attachment_b64=data.get("attachment_b64"),
                    attachment_mime=data.get("attachment_mime"),
                ):
                    if event.get("node") == "classify":
                        agent_used = (event.get("data") or {}).get("target_agent", agent_used)
                    if event.get("type") == "final":
                        final_response = event.get("response") or ""
                    await websocket.send_json(event)
            except Exception as e:
                await websocket.send_json({"type": "error", "detail": str(e)})
                continue

            duration_ms = int((time.monotonic() - start) * 1000)
            await _persist_messages(user, thread_pk, query, final_response)
            await _increment_usage(user, tokens=tokens, cost=0.0)
            await log_action(
                action="chat_request", user_id=str(user.id), agent_id=agent_used,
                success=True, duration_ms=duration_ms,
            )
    except WebSocketDisconnect:
        pass
