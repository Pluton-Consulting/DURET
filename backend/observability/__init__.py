"""
Module d'observabilité — traces LLM et scoring qualité via Langfuse.

Intégration optionnelle et dégradable : si Langfuse est désactivé ou indisponible,
tous les helpers deviennent des no-op silencieux (l'app ne plante jamais).

Ré-exporte les helpers principaux :
    - get_callback_handler : CallbackHandler LangChain à passer aux appels LLM
    - score_generation     : enregistre un score qualité (0-1) sur une trace
    - is_enabled           : indique si l'observabilité est active
    - flush                : vide le buffer d'événements
"""
from observability.langfuse_client import (
    flush,
    get_callback_handler,
    trace_config,
    is_enabled,
    score_generation,
)

__all__ = [
    "get_callback_handler",
    "trace_config",
    "score_generation",
    "is_enabled",
    "flush",
]
