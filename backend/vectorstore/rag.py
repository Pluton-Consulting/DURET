"""
Couche RAG — recherche sémantique filtrée par rôle

Orchestre : calcul de l'embedding de la requête (vectorstore.embeddings)
puis recherche hybride filtrée par rôle (vectorstore.client.search_hybrid).

Le filtrage d'accès (access_level selon le rôle) est entièrement délégué à
`vectorstore.search_hybrid` — cette couche ne fait qu'assembler embedding +
recherche et formater le résultat pour injection dans un prompt.

DÉGRADATION PROPRE : si l'embedding échoue (clé OpenAI absente / erreur API),
`search_hybrid` retombe automatiquement sur pg_trgm (full-text). Si la
recherche elle-même échoue, on retourne une liste vide et on logge un warning
— jamais d'exception propagée aux agents.

On ne logge jamais le contenu de la requête ni des chunks, uniquement des
métadonnées (rôle, nombre de résultats, type d'erreur).
"""
import logging
import time
from typing import Optional

from vectorstore.client import vectorstore
from vectorstore.embeddings import embed_query

logger = logging.getLogger("duret.rag")

# Cache léger : la mémoire a-t-elle au moins un document ? Évite d'embedder (Gemini)
# et de chercher à CHAQUE requête tant que la base est vide (gros gain de latence + quota).
_corpus_cache = {"has_docs": None, "ts": 0.0}
_CORPUS_TTL = 60.0  # re-vérifie au plus une fois par minute


async def _corpus_has_documents() -> bool:
    now = time.monotonic()
    cached = _corpus_cache["has_docs"]
    if cached is not None and (now - _corpus_cache["ts"]) < _CORPUS_TTL:
        return cached
    has = True  # en cas de doute, ne PAS bloquer le RAG
    try:
        from database.connection import get_db
        async with get_db() as conn:
            row = await conn.fetchval("SELECT 1 FROM documents LIMIT 1")
        has = row is not None
    except Exception:
        has = True
    _corpus_cache["has_docs"] = has
    _corpus_cache["ts"] = now
    return has


async def retrieve(
    query: str,
    user_role: str,
    source_types: Optional[list[str]] = None,
    top_k: int = 5,
) -> list[dict]:
    """
    Recherche sémantique filtrée par rôle et renvoie les chunks bruts.

    Args:
        query: requête en langage naturel.
        user_role: rôle de l'utilisateur (super_admin, direction, commercial…),
            utilisé par le vectorstore pour filtrer les niveaux d'accès.
        source_types: si fourni, ne conserve que les chunks dont le
            `source_type` figure dans la liste (post-filtre appliqué ici,
            `search_hybrid` ne filtrant que sur le rôle).
        top_k: nombre maximum de chunks à retourner.

    Returns:
        Liste de dicts (chunks) — chaque dict contient au moins `content`,
        `source_type`, `source_id`, `similarity`. Liste vide en cas d'échec
        ou d'absence de résultat. Ne lève jamais.
    """
    query = (query or "").strip()
    if not query:
        return []

    # Mémoire vide → inutile d'embedder (Gemini) puis de chercher : on gagne ~2 s/requête
    # et on préserve le quota, sans changer le résultat (il n'y a rien à trouver).
    if not await _corpus_has_documents():
        return []

    try:
        # Embedding optionnel : None => search_hybrid dégrade sur pg_trgm.
        embedding = await embed_query(query)

        chunks = await vectorstore.search_hybrid(
            query,
            embedding,
            user_role,
            top_k=top_k,
        ) or []

        # Post-filtre par type de source si demandé (search_hybrid ne le gère pas).
        if source_types:
            allowed = set(source_types)
            chunks = [c for c in chunks if c.get("source_type") in allowed]

        logger.debug(
            "RAG retrieve : rôle=%s, embedding=%s, résultats=%d",
            user_role, "oui" if embedding else "non (pg_trgm)", len(chunks),
        )
        return chunks

    except Exception as e:
        logger.warning(
            "Échec RAG retrieve (rôle=%s, %s) : %s",
            user_role, type(e).__name__, e,
        )
        return []


async def retrieve_as_context(
    query: str,
    user_role: str,
    source_types: Optional[list[str]] = None,
    top_k: int = 5,
) -> list[str]:
    """
    Comme `retrieve`, mais renvoie uniquement les contenus formatés, prêts à
    être injectés dans un prompt LLM.

    Chaque chunk est préfixé de sa provenance (`source_type` / nom de fichier)
    pour donner au modèle un ancrage de traçabilité.

    Args:
        query: requête en langage naturel.
        user_role: rôle de l'utilisateur (filtrage d'accès).
        source_types: filtre optionnel par type de source.
        top_k: nombre maximum de chunks.

    Returns:
        Liste de chaînes formatées (une par chunk). Liste vide si aucun
        résultat ou en cas d'échec. Ne lève jamais.
    """
    chunks = await retrieve(query, user_role, source_types=source_types, top_k=top_k)

    contexts: list[str] = []
    for chunk in chunks:
        content = (chunk.get("content") or "").strip()
        if not content:
            continue

        # Ancrage de provenance : nom de fichier si dispo, sinon type de source.
        source = chunk.get("source_filename") or chunk.get("source_type") or "document"
        contexts.append(f"[{source}]\n{content}")

    return contexts
