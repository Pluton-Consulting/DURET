"""
Optimisation des tokens — boîte à outils transverse (réduction coût + latence).

- estimate_tokens : estimation rapide (heuristique, aucune dépendance tokenizer).
- trim_chunks     : borne le nb de chunks RAG + le volume total de contexte envoyé.
- compact_messages: fenêtre glissante sur l'historique de conversation.
- tier_max_tokens : plafond de sortie par palier (LIGHT court → COMPLEX large).
- ResponseCache   : cache exact (palier|requête|contexte) avec TTL+LRU → évite les
                    appels LLM répétés. Clés/valeurs anonymisées (aucune PII).
"""
import hashlib
import time
from collections import OrderedDict

from config import settings


def estimate_tokens(text: str) -> int:
    """~ 1 token ≈ 4 caractères (fr/en). Suffisant pour borner/mesurer sans tokenizer."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def trim_chunks(chunks, max_chunks: int | None = None, max_total_chars: int | None = None) -> list[str]:
    """Borne le contexte RAG : au plus `max_chunks`, tronqué à un budget de caractères."""
    max_chunks = settings.optim_max_rag_chunks if max_chunks is None else max_chunks
    max_total_chars = settings.optim_max_context_chars if max_total_chars is None else max_total_chars
    out: list[str] = []
    used = 0
    for c in list(chunks or [])[:max_chunks]:
        c = str(c)
        if used >= max_total_chars:
            break
        remaining = max_total_chars - used
        if len(c) > remaining:
            c = c[:remaining] + " …[tronqué]"
        out.append(c)
        used += len(c)
    return out


def compact_messages(messages, keep_recent: int | None = None):
    """Garde les messages système + les N plus récents (limite la croissance de l'historique)."""
    keep_recent = settings.optim_history_keep if keep_recent is None else keep_recent
    if not messages or len(messages) <= keep_recent:
        return messages
    systems = [m for m in messages if getattr(m, "type", None) == "system"][:2]
    tail = list(messages[-keep_recent:])
    seen = set(id(m) for m in systems)
    return systems + [m for m in tail if id(m) not in seen]


def tier_max_tokens(tier: str) -> int:
    """Plafond de tokens de sortie selon le palier — évite de payer une génération trop longue."""
    return {
        "light": settings.optim_max_tokens_light,
        "standard": settings.optim_max_tokens_standard,
        "complex": settings.optim_max_tokens_complex,
    }.get(tier, settings.optim_max_tokens_standard)


class ResponseCache:
    """Cache exact-match (LRU + TTL) des réponses LLM. Clé = sha256(palier|requête|contexte)."""

    def __init__(self) -> None:
        self._store: "OrderedDict[str, tuple]" = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _key(tier: str, query: str, context: str) -> str:
        return hashlib.sha256(f"{tier}\x00{query}\x00{context}".encode("utf-8")).hexdigest()

    def get(self, tier: str, query: str, context: str):
        if not settings.optim_cache_enabled:
            return None
        key = self._key(tier, query, context)
        item = self._store.get(key)
        if not item:
            self._misses += 1
            return None
        value, expires = item
        if time.monotonic() > expires:
            self._store.pop(key, None)
            self._misses += 1
            return None
        self._store.move_to_end(key)
        self._hits += 1
        return value

    def set(self, tier: str, query: str, context: str, value) -> None:
        if not settings.optim_cache_enabled or value is None:
            return
        key = self._key(tier, query, context)
        self._store[key] = (value, time.monotonic() + settings.optim_cache_ttl_s)
        self._store.move_to_end(key)
        while len(self._store) > settings.optim_cache_max:
            self._store.popitem(last=False)

    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
            "size": len(self._store),
            "enabled": settings.optim_cache_enabled,
        }


# Singleton partagé par les agents.
response_cache = ResponseCache()
