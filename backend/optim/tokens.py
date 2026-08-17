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


def compact_messages(messages, keep_recent: int | None = None, max_chars: int | None = None):
    """Fenêtre glissante sur l'historique de conversation (hors messages système).

    Double bornage : au plus `keep_recent` messages ET `max_chars` caractères, en
    repartant des plus récents. La fenêtre est recalée sur une frontière de PAIRE
    (elle commence toujours par un message utilisateur) : une liste débutant par
    une réponse assistant est rejetée par certaines API LLM, et prive de toute
    façon le modèle de la question à laquelle cette réponse correspondait.
    """
    keep_recent = settings.optim_history_keep if keep_recent is None else keep_recent
    max_chars = settings.optim_max_history_chars if max_chars is None else max_chars

    msgs = [m for m in (messages or []) if getattr(m, "type", None) != "system"]
    if not msgs:
        return []

    tail = msgs[-keep_recent:] if keep_recent > 0 else []

    # Budget caractères, en partant de la fin (les tours récents priment).
    out, used = [], 0
    for m in reversed(tail):
        size = len(str(getattr(m, "content", "") or ""))
        if out and used + size > max_chars:
            break
        out.append(m)
        used += size
    out.reverse()

    # Recale sur une frontière de paire.
    while out and getattr(out[0], "type", None) != "human":
        out.pop(0)

    # UN ÉCHANGE SURVIT TOUJOURS AU BUDGET.
    #
    # Les deux règles ci-dessus se retournaient l'une contre l'autre. Le budget
    # laisse entrer le DERNIER message sans condition (`if out and ...` : la
    # liste est encore vide au premier tour de boucle), quelle qu'en soit la
    # taille. Une réponse d'assistant un peu longue mangeait donc tout le
    # budget à elle seule, la question qui l'avait produite ne passait plus, et
    # le recalage ci-dessus supprimait cette réponse orpheline : la fonction
    # rendait une liste VIDE alors que le fil était plein.
    #
    # Mesuré sur les réglages livrés (8 messages, 4000 caractères) : une
    # réponse de 3 900 caractères efface la totalité de la mémoire du tour
    # suivant. Or une réponse de cette taille est ordinaire ici — un devis
    # complet, une arborescence Drive, une liste de mails. L'assistant
    # répondait alors « je ne comprends pas » à un « oui » ou à un « 1 », sans
    # que rien ne signale l'amnésie.
    #
    # Le budget existe pour économiser des jetons, pas pour effacer la
    # mémoire : on rend donc le dernier échange coûte que coûte. Le
    # dépassement est borné à une paire, et il ne se produit que dans le cas
    # où l'alternative était de tout perdre.
    if not out and len(tail) >= 2 and getattr(tail[-2], "type", None) == "human":
        return list(tail[-2:])
    return out


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
    def _key(tier: str, query: str, context: str, scope: str = "") -> str:
        return hashlib.sha256(
            f"{tier}\x00{query}\x00{context}\x00{scope}".encode("utf-8")
        ).hexdigest()

    def get(self, tier: str, query: str, context: str, scope: str = ""):
        if not settings.optim_cache_enabled:
            return None
        key = self._key(tier, query, context, scope)
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

    def set(self, tier: str, query: str, context: str, value, scope: str = "") -> None:
        if not settings.optim_cache_enabled or value is None:
            return
        key = self._key(tier, query, context, scope)
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
