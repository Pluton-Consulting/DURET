"""
Observabilité LLM — client Langfuse (SDK v3, Langfuse Cloud ou self-hosted).

Intégration *optionnelle* et *dégradable* :
- Active si `settings.langfuse_enabled` ET clés réelles (pas des placeholders `dev-langfuse-*`).
- Sinon (désactivé, clés placeholder, import/réseau en échec) : tout devient no-op silencieux.
  L'absence ou la panne de Langfuse ne casse JAMAIS une requête chat.

SDK v3 : le CallbackHandler LangChain ne prend plus les identifiants au constructeur ;
user_id / session_id / tags se passent via les métadonnées de l'appel LangChain
(`config={"metadata": {"langfuse_user_id": ...}}`). Le helper `trace_config()` assemble
directement le dict `config` à passer à `llm.ainvoke(...)`.

CONFIDENTIALITÉ (RGPD) :
- On ne transmet que des identifiants techniques : `user_id` = UUID PSEUDONYMISÉ (jamais email/nom).
- Le contenu capturé par le handler reste la responsabilité de l'appelant ; ici les prompts
  passés au LLM sont déjà anonymisés en amont (agent1) avant tout envoi.
"""
import logging
from typing import Any, Optional

from config import settings

logger = logging.getLogger("duret.observability")

_PLACEHOLDER_PREFIX = "dev-langfuse-"
_UNSET = object()
_client: Any = _UNSET


def _host() -> str:
    """URL Langfuse : base_url prioritaire (ex. cloud), sinon host."""
    return settings.langfuse_base_url or settings.langfuse_host


def _is_placeholder(value: Optional[str]) -> bool:
    return (not value) or value.strip().startswith(_PLACEHOLDER_PREFIX)


def _mask_pii(data: Any) -> Any:
    """
    Masque Langfuse (défense en profondeur RGPD) : re-anonymise tout contenu
    envoyé au cloud. Le pipeline agent1 anonymise déjà les prompts LLM ; ce masque
    couvre en plus l'état brut du graphe (ex. la requête utilisateur non masquée)
    capturé par le tracing niveau-graphe, afin qu'AUCUNE PII ne quitte le système.
    Ne lève jamais : en cas de doute, renvoie une valeur neutralisée.
    """
    from security.anonymizer import anonymizer

    def walk(x: Any, depth: int = 0) -> Any:
        if depth > 6:
            return "[tronqué]"
        if isinstance(x, str):
            if not x:
                return x
            try:
                return anonymizer.anonymize(x)[0]
            except Exception:
                return "[masqué]"
        if isinstance(x, dict):
            return {k: walk(v, depth + 1) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [walk(v, depth + 1) for v in x]
        return x

    try:
        return walk(data)
    except Exception:
        return "[masqué]"


def is_enabled() -> bool:
    """Actif si l'observabilité est activée et les deux clés réellement configurées."""
    return bool(
        settings.langfuse_enabled
        and not _is_placeholder(settings.langfuse_public_key)
        and not _is_placeholder(settings.langfuse_secret_key)
    )


def _get_client() -> Optional[Any]:
    """Client Langfuse (singleton paresseux), ou None si indisponible."""
    global _client
    if _client is not _UNSET:
        return _client

    if not is_enabled():
        _client = None
        return None

    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=_host(),
            mask=_mask_pii,          # défense en profondeur RGPD — aucune PII vers le cloud
            environment=settings.environment,
        )
        logger.info("Observabilité Langfuse activée (host=%s, masque PII actif)", _host())
    except Exception as e:
        logger.warning("Langfuse indisponible — observabilité désactivée : %s", e)
        _client = None

    return _client


def get_callback_handler(
    user_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> Optional[Any]:
    """
    Retourne un `CallbackHandler` Langfuse v3 (compatible LangChain), ou None si désactivé.
    En v3, user_id/session_id/tags NE sont PAS passés ici mais via les métadonnées d'appel
    (cf. `trace_config`). Les paramètres restent acceptés pour compatibilité.
    """
    if _get_client() is None:
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as e:
        logger.warning("CallbackHandler Langfuse indisponible : %s", e)
        return None


def trace_config(
    user_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> dict:
    """
    Assemble le `config` LangChain à passer à `llm.ainvoke(messages, config=...)` :
    callbacks Langfuse + métadonnées (user pseudonymisé, session=thread, tags).
    Retourne `{}` si l'observabilité est désactivée (dans ce cas passer `None` à ainvoke).
    """
    handler = get_callback_handler(user_id, thread_id, tags)
    if handler is None:
        return {}
    meta: dict = {}
    if user_id:
        meta["langfuse_user_id"] = user_id       # UUID pseudonymisé
    if thread_id:
        meta["langfuse_session_id"] = thread_id  # regroupe les traces d'un même fil
    if tags:
        meta["langfuse_tags"] = tags
    return {"callbacks": [handler], "metadata": meta}


async def score_generation(
    trace_id: str,
    name: str,
    value: float,
    comment: Optional[str] = None,
) -> None:
    """Enregistre un score qualité [0,1] sur une trace. No-op si désactivé."""
    client = _get_client()
    if client is None:
        return
    try:
        bounded = max(0.0, min(1.0, float(value)))
        client.create_score(trace_id=trace_id, name=name, value=bounded, comment=comment)
    except Exception as e:
        logger.warning("Échec enregistrement du score Langfuse '%s' : %s", name, e)


def flush() -> None:
    """Vide le buffer d'événements Langfuse. No-op si désactivé."""
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as e:
        logger.warning("Échec du flush Langfuse : %s", e)
