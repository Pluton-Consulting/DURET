import asyncio
import base64
import logging
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

logger = logging.getLogger("duret.chat")
router = APIRouter()


class ChatRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None
    has_attachment: bool = False
    attachment_type: Optional[str] = None
    attachment_b64: Optional[str] = None      # fichier encodé base64
    attachment_mime: Optional[str] = None      # 'image/jpeg', 'application/pdf', ...
    attachment_name: Optional[str] = None      # nom d'origine — sert à choisir le lecteur


async def _texte_piece_jointe(nom: Optional[str], b64: Optional[str],
                              mime: Optional[str]) -> Optional[str]:
    """Extrait le texte d'un fichier joint au chat (Excel, Word, CSV, PDF, texte…).

    Retourne None pour les IMAGES et les PDF sans couche texte : ceux-là partent
    vers la vision (agent2), qui sait décrire un plan ou une photo. Tout le reste
    est converti en texte et injecté dans le contexte comme un document.

    Ne lève jamais : un fichier illisible ne doit pas faire échouer le message.
    """
    if not b64:
        return None
    if (mime or "").lower().startswith("image/"):
        return None                      # une photo/un plan : c'est le travail de la vision

    try:
        brut = base64.b64decode(b64)
    except Exception:
        return None
    if len(brut) > settings.max_body_mb * 1024 * 1024:
        logger.warning("Pièce jointe trop volumineuse (%d octets) — ignorée", len(brut))
        return None

    from ingestion.parsers import analyser, ligne_en_texte, famille, FichierNonSupporte

    nom = nom or "document"
    if famille(nom) is None:
        return None                      # extension inconnue -> tentative vision en repli

    try:
        structure = await asyncio.to_thread(analyser, nom, brut)
    except FichierNonSupporte as e:
        logger.info("Pièce jointe %s non exploitable en texte (%s)", nom, e)
        return None                      # PDF scanné sans OCR, image illisible -> vision
    except Exception as e:               # noqa: BLE001
        logger.warning("Lecture de la pièce jointe %s impossible : %s", nom, e)
        return None

    # UN PLAN N'EST PAS UN DOCUMENT TEXTE. Un PDF de plan porte souvent quelques
    # étiquettes vectorielles (cotes, légendes) : sa couche texte « existe », le
    # fichier partait donc chez agent1 avec trois mots pour tout contenu — et la
    # vision, seule capable de LIRE le dessin, n'était jamais sollicitée. Sous ce
    # seuil, le texte extrait ne raconte rien : on rend None, le tour part à la
    # vision (agent2). Les vrais documents texte (CCTP, courriers) le dépassent
    # largement, et les tableaux ne sont pas concernés.
    if (structure["kind"] != "tabulaire"
            and ("pdf" in (mime or "").lower() or nom.lower().endswith(".pdf"))
            and len((structure.get("text") or "").strip()) < 300):
        return None

    if structure["kind"] == "tabulaire":
        lignes = structure["rows"]
        # Un classeur de 5 000 lignes ne tient pas dans une fenêtre de contexte :
        # on en donne un extrait représentatif et on annonce la troncature, plutôt
        # que de laisser le modèle croire qu'il a tout vu.
        extrait = [ligne_en_texte(l) for l in lignes[:40]]
        entete = f"Tableau : {len(lignes)} lignes, colonnes : {', '.join(structure['columns'])}"
        if len(lignes) > 40:
            entete += (f"\n(Seules les 40 premières lignes sont reproduites ici. Pour exploiter "
                       f"les {len(lignes)} lignes, importez le fichier via Paramètres > Import de données.)")
        return entete + "\n\n" + "\n\n".join(extrait)

    return structure["text"]


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
            detail=f"Accès refusé à {now.hour}h{now.minute:02d}. Plage autorisée : {start_hour}h00–{end_hour}h00.",
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


async def _actualiser_expert(current_user: User, thread_pk: str, agent_used: str) -> None:
    """Crédite le fil à l'expert qui a RÉELLEMENT travaillé ce tour.

    `threads.agent_type` était figé à « agent1 » par `_claim_thread` et jamais
    mis à jour : l'historique des autres experts (bouton « Historique » de leur
    carte) restait vide pour toujours, même après une analyse de plan ou un
    visuel. Montée seule (agent1 -> agent2/agent3), jamais l'inverse : un fil
    qui a touché à la conception reste dans l'historique conception, même si la
    conversation revient ensuite au devis. Best-effort : l'attribution ne fait
    jamais échouer une réponse.
    """
    if agent_used in (None, "", "agent1"):
        return
    try:
        async with get_rls_db(str(current_user.id), current_user.role) as conn:
            await conn.execute(
                """UPDATE threads SET agent_type = $2
                   WHERE id = $1::uuid AND agent_type IS DISTINCT FROM $2""",
                uuid.UUID(thread_pk), agent_used,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("Attribution d'expert non enregistrée : %s", e)


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
        logger.warning("Persistance des messages échouée : %s", e)


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

    texte_joint = await _texte_piece_jointe(body.attachment_name, body.attachment_b64, body.attachment_mime)

    try:
        result = await runtime.run_turn(
            query=body.query,
            user_id=str(current_user.id),
            user_role=current_user.role,
            has_attachment=body.has_attachment or bool(body.attachment_b64),
            thread_id=thread_id,
            attachment_b64=body.attachment_b64,
            attachment_mime=body.attachment_mime,
            attachment_name=body.attachment_name,
            attachment_text=texte_joint,
        )
    except HTTPException:
        raise
    except runtime.FilOccupe as e:
        # Un tour tourne déjà sur ce fil, ou il attend une décision humaine. Ce
        # n'est pas une panne : c'est le garde-fou qui empêche deux exécutions
        # d'écrire le même historique. Le message est écrit pour être lu tel
        # quel — et le 409 distingue ce refus d'une erreur de traitement, ce que
        # l'écran utilise pour proposer la file d'attente.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        success = False
        error_msg = str(e)
        result = {
            "status": "error", "thread_id": thread_id,
            "response": "Une erreur est survenue, veuillez réessayer.",
            "agent_used": "agent1", "tokens_in": 0, "tokens_out": 0,
            "cost_eur": 0.0, "model_used": None, "validation_id": None,
        }

    tokens_in = result.get("tokens_in", 0)
    tokens_out = result.get("tokens_out", 0)
    cost_eur = result.get("cost_eur", 0.0)
    agent_used = result.get("agent_used", "agent1")
    duration_ms = int((time.monotonic() - start) * 1000)

    await _persist_messages(current_user, thread_pk, body.query, result.get("response") or "")
    await _actualiser_expert(current_user, thread_pk, agent_used)
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
            # LA QUESTION AVANT SA RÉPONSE, MÊME À ÉGALITÉ DE DATE (01/09).
            # Les deux messages d'un tour sont insérés dans la MÊME transaction
            # (`_persist_messages`, executemany) : NOW() y est figé, ils portent
            # donc le MÊME created_at, et un ORDER BY sur la seule date rendait
            # leur ordre au hasard du plan d'exécution. Relevé par Noa : en
            # revenant sur la page, sa question s'affichait SOUS la réponse.
            # Le départage par rôle tranche : dans un tour, l'humain parle
            # d'abord.
            """SELECT m.id, m.role, m.content, m.metadata, m.created_at
               FROM messages m
               JOIN threads t ON t.id = m.thread_id
               WHERE t.langgraph_thread_id = $1
               ORDER BY m.created_at ASC,
                        CASE WHEN m.role = 'user' THEN 0 ELSE 1 END ASC""",
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

# Les tours dont la socket est partie mais qui finissent leur course : asyncio
# ne garde qu'une référence FAIBLE sur les tâches — sans ce set, un tour
# détaché pouvait être ramassé en plein vol, silencieusement.
_TOURS_DETACHES: set[asyncio.Task] = set()


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


async def _dire(websocket: WebSocket, payload: dict) -> bool:
    """Envoie sur la socket si elle vit encore. Une socket partie N'EST PAS une
    panne : l'utilisateur a navigué (Paramètres…), rafraîchi la page ou changé
    d'application — le tour continue pour l'historique, et l'écran se
    resynchronisera à son retour. Rendre l'échec au lieu de le lever, c'est ce
    qui permet à la boucle du tour d'aller au bout sans personne au bout du fil.
    """
    try:
        await websocket.send_json(payload)
        return True
    except Exception:  # noqa: BLE001 - socket fermée ou rompue : on continue sans elle
        return False


async def _derouler_tour(websocket: WebSocket, user: User, thread_id: str,
                         data: dict) -> None:
    """Un tour complet, dans une tâche À PART pour rester ANNULABLE.

    Ce corps vivait dans la boucle de réception. Tant qu'il tournait, plus
    personne ne lisait la socket : un « stop » envoyé par l'utilisateur
    attendait sagement dans le tampon que le tour finisse — c'est-à-dire
    exactement le moment où il ne servait plus à rien. Le sortir en tâche rend
    la boucle libre d'écouter, donc l'arrêt possible.
    """
    try:
        await _check_schedule(user)
        await _check_quota(user)
    except HTTPException as e:
        await _dire(websocket, {"type": "error", "detail": e.detail})
        return

    start = time.monotonic()
    tokens = 0
    cout = 0.0
    modele = None
    mesure: dict = {}
    agent_used = "agent1"
    # Réservation + contrôle d'appartenance AVANT le tour : le thread_id vient
    # de l'URL du WebSocket, et stream_turn charge le checkpoint (historique).
    try:
        thread_pk = await _claim_thread(user, thread_id, data.get("query", ""))
    except HTTPException as e:
        await _dire(websocket, {"type": "error", "detail": e.detail})
        return

    texte_joint = await _texte_piece_jointe(
        data.get("attachment_name"), data.get("attachment_b64"), data.get("attachment_mime")
    )

    final_response = ""
    # L'échange a-t-il déjà été écrit pendant la boucle ? Un tour qui se termine
    # sur une demande de validation n'émet PAS de `final` : il faut alors écrire
    # après coup, comme avant, sinon la question posée disparaîtrait du fil.
    persistance_faite = False
    try:
        async for event in runtime.stream_turn(
            query=data.get("query", ""),
            user_id=str(user.id),
            user_role=user.role,
            has_attachment=data.get("has_attachment", False) or bool(data.get("attachment_b64")),
            thread_id=thread_id,
            attachment_b64=data.get("attachment_b64"),
            attachment_mime=data.get("attachment_mime"),
            attachment_name=data.get("attachment_name"),
            attachment_text=texte_joint,
        ):
            # L'expert effectif se lit sur TOUS les nœuds, pas seulement sur
            # `classify` : la boucle d'outils et `execute_action` réattribuent
            # le tour quand un skill déclare son expert (un visuel = de la
            # conception, même exécuté dans le graphe d'agent1). Le dernier
            # avis du tour l'emporte.
            cible = (event.get("data") or {}).get("target_agent")
            if cible:
                agent_used = cible
            if event.get("type") == "final":
                final_response = event.get("response") or ""
                # CE QUE LE TOUR A COÛTÉ. Cette variable valait 0 depuis
                # toujours sur ce chemin — qui est pourtant le chemin nominal.
                mesure = event.get("mesure") or {}
                tokens = int(mesure.get("tokens_in", 0)) + int(mesure.get("tokens_out", 0))
                cout = float(mesure.get("cost_eur", 0.0) or 0.0)
                modele = mesure.get("modele")
                # ON ÉCRIT AVANT D'ANNONCER, ET C'EST TOUT LE CORRECTIF.
                #
                # La persistance vivait APRÈS la boucle. Or `final` est le
                # dernier événement du serveur, et le client ferme la socket
                # dès qu'il le reçoit (`finish()` appelle `closeWs()`) : le
                # serveur partait donc écrire en base pendant que la connexion
                # se fermait sous lui. Selon qui gagnait la course, le dernier
                # échange était enregistré... ou perdu. Relevé en production :
                # « le dernier message disparaît dès que je rafraîchis ».
                #
                # Une annulation de tâche n'est PAS une `Exception` en Python
                # (CancelledError descend de BaseException) : le garde-fou
                # best-effort de `_persist_messages` ne la voyait pas passer,
                # et la perte était donc parfaitement silencieuse — aucun
                # journal, aucune trace, un message évaporé.
                #
                # Écrire d'abord supprime la course au lieu de l'arbitrer :
                # quand le client apprend que c'est fini, ça l'est vraiment.
                # Le coût est une écriture avant l'affichage, quelques
                # millisecondes sur un tour qui en a pris des milliers.
                await _persist_messages(user, thread_pk,
                                        data.get("query", ""), final_response)
                persistance_faite = True
            # `_dire` et non `send_json` : une socket partie (navigation,
            # rafraîchissement) ne doit plus faire dérailler le tour — il va
            # au bout, et sa réponse attend dans l'historique.
            await _dire(websocket, event)
    except asyncio.CancelledError:
        # ARRÊT DEMANDÉ — pas une panne. Le verrou de fil se libère de lui-même
        # (`_Verrou.__exit__` s'exécute au passage de l'annulation), donc la
        # conversation reste utilisable tout de suite après.
        #
        # On l'ANNONCE, et on garde une trace : un tour interrompu qui
        # disparaîtrait sans laisser de message donnerait à l'écran l'aspect
        # d'un plantage. Ce qui a déjà été produit est écrit tel quel.
        logger.info("Tour interrompu à la demande (fil %s)", thread_id)
        # LE MÊME TEXTE À L'ÉCRAN ET EN BASE : au rechargement, la conversation
        # doit dire exactement ce qu'elle disait avant.
        mot = final_response or "Traitement interrompu à votre demande."
        # MÊME INVERSION QU'AU CHEMIN NORMAL : on écrivait APRÈS avoir annoncé,
        # et le client ferme la socket sur `arrete` comme sur `final`. Pire ici :
        # les deux appels partageaient un `try` dont l'échec du premier sautait
        # le second, si bien qu'une socket déjà fermée emportait l'écriture.
        if not persistance_faite:
            await _persist_messages(user, thread_pk, data.get("query", ""), mot)
            persistance_faite = True
        await _dire(websocket, {"type": "arrete", "detail": mot})
        await log_action(action="chat_interrompu", user_id=str(user.id),
                         agent_id=agent_used, success=True,
                         duration_ms=int((time.monotonic() - start) * 1000))
        raise
    except runtime.FilOccupe as e:
        # Refus délibéré, pas une panne : le client ne doit PAS se
        # rabattre sur le POST, qui retomberait sur le même fil occupé.
        # Un type distinct le lui dit.
        await _dire(websocket, {"type": "fil_occupe", "detail": str(e)})
        return
    except Exception as e:  # noqa: BLE001
        # UN TOUR QUI PLANTE DOIT LAISSER UNE TRACE. Cette branche rendait
        # « Une erreur est survenue » à l'écran et sortait SANS RIEN journaliser :
        # la tuile « Erreurs (24 h) » et l'onglet Erreurs du pilotage ne
        # voyaient donc jamais les pannes du chat — celles-là mêmes qu'on passe
        # ensuite des heures à chercher dans les journaux Docker.
        await log_action(
            action="chat_request", user_id=str(user.id), agent_id=agent_used,
            success=False, error_message=str(e)[:500],
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        await _dire(websocket, {"type": "error", "detail": str(e)})
        return

    duration_ms = int((time.monotonic() - start) * 1000)
    # Filet pour les tours qui n'ont pas émis de `final` : mise en attente de
    # validation, principalement. Écrire deux fois le même échange serait pire
    # que ne pas l'écrire — le fil afficherait la question en double.
    if not persistance_faite:
        await _persist_messages(user, thread_pk, data.get("query", ""), final_response)
    await _actualiser_expert(user, thread_pk, agent_used)
    await _increment_usage(user, tokens=tokens, cost=cout)
    # LE JOURNAL DISAIT « RÉUSSI » ET « MODÈLE — » À TOUS LES COUPS. Il porte
    # désormais ce qui s'est passé : le modèle qui a effectivement répondu (pas
    # celui qu'on espérait), les jetons, le coût. Un tour sans réponse finale
    # n'est pas un succès : le dire aurait rendu la tuile « Erreurs » vide par
    # construction.
    await log_action(
        action="chat_request", user_id=str(user.id), agent_id=agent_used,
        model_used=modele, success=bool(final_response),
        error_message=None if final_response else "aucune réponse finale",
        duration_ms=duration_ms,
        tokens_in=int(mesure.get("tokens_in", 0) or 0),
        tokens_out=int(mesure.get("tokens_out", 0) or 0),
        cost_eur=cout,
    )


@router.websocket("/ws/{thread_id}")
async def chat_ws(websocket: WebSocket, thread_id: str):
    """
    Streaming temps réel : le client envoie une requête JSON {query, has_attachment},
    le serveur pousse les événements nœud-par-nœud puis la réponse finale.
    Auth via ?ticket=<ticket éphémère> (obtenu par POST /api/chat/ws-ticket).

    Le tour tourne dans une tâche séparée pour que cette boucle reste
    disponible : c'est elle qui reçoit le « stop » et annule.
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

    en_cours: Optional[asyncio.Task] = None
    try:
        while True:
            data = await websocket.receive_json()

            # L'ARRÊT PASSE AVANT TOUT. C'est le seul message qui compte quand
            # un tour est en route, et il doit être traité sans rien attendre.
            if (data.get("type") or "") == "stop":
                if en_cours is not None and not en_cours.done():
                    en_cours.cancel()
                else:
                    # Rien à arrêter : on le dit plutôt que de laisser un bouton
                    # sans effet. L'écran remet la saisie à disposition.
                    await websocket.send_json(
                        {"type": "arrete", "detail": "Aucun traitement en cours."})
                continue

            query = data.get("query", "")
            if not query:
                continue

            # UN TOUR À LA FOIS SUR CE FIL. Le verrou du runtime dirait la même
            # chose, mais plus tard et en ayant déjà réservé des ressources ;
            # ici la réponse est immédiate et l'écran bascule en file d'attente.
            if en_cours is not None and not en_cours.done():
                await websocket.send_json({
                    "type": "fil_occupe",
                    "detail": "Un traitement est déjà en cours sur cette "
                              "conversation. Attendez qu'il se termine, "
                              "arrêtez-le, ou lancez votre demande en file "
                              "d'attente."})
                continue

            en_cours = asyncio.create_task(
                _derouler_tour(websocket, user, thread_id, data))
    except WebSocketDisconnect:
        pass
    finally:
        # LA FERMETURE DE LA SOCKET N'ARRÊTE PLUS LE TOUR EN PLEIN VOL.
        #
        # L'ancienne règle annulait le tour dès la déconnexion, pour ne pas
        # payer des modèles pour une socket que plus personne n'écoute. Mais
        # naviguer vers Paramètres, rafraîchir la page ou changer d'application
        # sur mobile ferment la socket SANS que quiconque ait voulu abandonner
        # — et l'annulation jetait alors les appels déjà payés du tour. Depuis
        # que la réponse est PERSISTÉE avant d'être annoncée, quelqu'un écoute
        # toujours : l'historique. Le tour va donc au bout (borné par les
        # budgets d'actions du graphe), ses envois tombent dans `_dire` qui
        # tolère la socket absente, et sa réponse attend dans la conversation.
        # L'arrêt VOULU reste le bouton « stop », traité dans la boucle
        # ci-dessus. La référence est retenue : asyncio ne garde qu'une
        # référence faible sur les tâches, un tour détaché sans ancre pouvait
        # être ramassé en plein vol.
        if en_cours is not None and not en_cours.done():
            _TOURS_DETACHES.add(en_cours)
            en_cours.add_done_callback(_TOURS_DETACHES.discard)
