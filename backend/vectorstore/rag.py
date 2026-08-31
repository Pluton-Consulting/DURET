"""
Couche RAG — recherche sémantique filtrée par rôle

Orchestre : calcul de l'embedding de la requête (vectorstore.embeddings)
puis recherche hybride filtrée par rôle (vectorstore.client.search_hybrid).

Le filtrage d'accès (access_level selon le rôle) est entièrement délégué à
`vectorstore.search_hybrid` — cette couche ne fait qu'assembler embedding +
recherche et formater le résultat pour injection dans un prompt.

DEUX VOIES, TOUJOURS (31/08/2026) : la vectorielle (quand l'embedding de la
question existe) ET la lexicale (plein texte français + trigrammes de mots),
fusionnées par rang réciproque. La moitié du corpus n'a pas d'embedding
(quota Gemini) : elle n'existait pas pour l'ancienne recherche, vectorielle
seule. Si la recherche échoue, on retourne une liste vide et on logge un
warning — jamais d'exception propagée aux agents.

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


# Types de documents issus d'une boîte mail. Leur `source_id` suit la convention
# « <type>:<boîte>:<id_message> », ce qui permet de savoir à qui ils appartiennent.
TYPES_MAIL = ("email", "email_sent")


def _boite_du_chunk(chunk: dict) -> Optional[str]:
    """Boîte d'origine d'un chunk de mail, ou None si indéterminable."""
    parties = (chunk.get("source_id") or "").split(":")
    return parties[1].strip().lower() if len(parties) >= 3 and parties[1].strip() else None


def _filtrer_mails(chunks: list[dict], mailboxes: Optional[list[str]]) -> list[dict]:
    """Ne conserve que les mails des boîtes autorisées.

    FAIL-CLOSED : sans liste de boîtes, AUCUN mail n'est retourné. Le filtrage
    par rôle ne suffit pas ici — deux collègues partagent le même rôle mais pas
    leurs messages. Un document dont la boîte est indéterminable (ingéré par une
    version antérieure, sans préfixe) est également écarté : mieux vaut le
    rendre invisible jusqu'à resynchronisation que risquer de l'exposer.
    """
    autorisees = {(m or "").strip().lower() for m in (mailboxes or []) if m}
    if "*" in autorisees:
        return chunks        # accès administrateur : tous les mails sont visibles
    retenus = []
    for c in chunks:
        if c.get("source_type") in TYPES_MAIL:
            boite = _boite_du_chunk(c)
            if not boite or boite not in autorisees:
                continue
        retenus.append(c)
    return retenus


async def retrieve(
    query: str,
    user_role: str,
    source_types: Optional[list[str]] = None,
    top_k: int = 5,
    mailboxes: Optional[list[str]] = None,
) -> list[dict]:
    """
    Recherche hybride filtrée par rôle et renvoie les chunks bruts.

    Args:
        query: requête en langage naturel.
        user_role: rôle de l'utilisateur (super_admin, direction, commercial…),
            utilisé par le vectorstore pour filtrer les niveaux d'accès.
        source_types: si fourni, ne conserve que les chunks dont le
            `source_type` figure dans la liste — filtré DANS la requête
            depuis le 31/08 (avant, un post-filtre vidait la page).
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
        # Embedding optionnel : None => la voie lexicale seule (search_hybrid).
        embedding = await embed_query(query)

        # On sur-échantillonne pour le cloisonnement des boîtes (post-filtre) :
        # sans marge on renverrait moins que `top_k` alors que des documents
        # pertinents existent.
        marge = 3 if mailboxes is not None else 1
        chunks = await vectorstore.search_hybrid(
            query, embedding, user_role, top_k=top_k * marge,
            source_types=list(source_types) if source_types else None) or []

        # Cloisonnement des boîtes mail (fail-closed).
        chunks = _filtrer_mails(chunks, mailboxes)[:top_k]

        logger.debug(
            "RAG retrieve : rôle=%s, embedding=%s, résultats=%d",
            user_role, "oui" if embedding else "non (lexical seul)", len(chunks),
        )
        return chunks

    except Exception as e:
        logger.warning(
            "Échec RAG retrieve (rôle=%s, %s) : %s",
            user_role, type(e).__name__, e,
        )
        return []


# Profondeur maximale d'une recherche : le nombre de morceaux qu'on remonte
# avant de grouper par document. Assez pour paginer loin (20 documents par
# page × plusieurs pages), borné pour qu'une question vague ne rapatrie pas
# le corpus.
PROFONDEUR_MAX = 400


async def rechercher(
    query: str,
    user_role: str,
    source_types: Optional[list[str]] = None,
    mailboxes: Optional[list[str]] = None,
    limite: int = 6,
    page: int = 1,
    fichier: Optional[str] = None,
) -> dict:
    """UNE recherche, petite ou énorme : les DOCUMENTS qui répondent, classés,
    avec leurs meilleurs extraits, le COMPTE exact de ce qui correspond, et
    la page demandée. C'est le geste du skill `rechercher_documents`.

    La profondeur suit la page : on remonte assez de morceaux pour servir la
    page N sans recalculer les précédentes, groupés par document ensuite —
    « trente morceaux du même compte rendu » deviennent UN document qui dit
    « 30 morceaux correspondants ». Ne lève jamais : un dict vide sur échec.
    """
    from vectorstore.fusion import fusionner, grouper_par_document

    query = (query or "").strip()
    limite = max(1, int(limite or 6))
    page = max(1, int(page or 1))
    vide = {"documents": [], "total_documents": 0, "total_morceaux": 0,
            "embedding": False, "page": page, "limite": limite}
    if not query or not await _corpus_has_documents():
        return vide
    try:
        embedding = await embed_query(query)
        profondeur = min(PROFONDEUR_MAX, max(60, limite * page * 4))
        types = list(source_types) if source_types else None
        voies: dict = {}
        if embedding:
            voies["vecteur"] = await vectorstore.search(
                embedding, user_role, types, top_k=profondeur, fichier=fichier)
        voies["texte"] = await vectorstore.search_lexical(
            query, user_role, types, top_k=profondeur, fichier=fichier)
        total_morceaux, total_documents = await vectorstore.count_lexical(
            query, user_role, types, fichier=fichier)
        chunks = _filtrer_mails(fusionner(voies), mailboxes)
        documents = grouper_par_document(chunks)
        logger.debug("RAG rechercher : rôle=%s, embedding=%s, morceaux=%d, documents=%d, page=%d",
                     user_role, "oui" if embedding else "non", len(chunks), len(documents), page)
        return {"documents": documents,
                # Le compte lexical est EXACT sur le corpus ; le groupement peut
                # y ajouter des documents que seule la voie vectorielle a vus.
                "total_documents": max(len(documents), total_documents),
                "total_morceaux": max(len(chunks), total_morceaux),
                "embedding": bool(embedding), "page": page, "limite": limite,
                "profondeur_atteinte": len(chunks) >= profondeur}
    except Exception as e:  # noqa: BLE001 — une recherche en échec n'est pas une panne
        logger.warning("Échec RAG rechercher (rôle=%s, %s) : %s", user_role, type(e).__name__, e)
        return vide


async def retrieve_as_context(
    query: str,
    user_role: str,
    source_types: Optional[list[str]] = None,
    top_k: int = 5,
    mailboxes: Optional[list[str]] = None,
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
    chunks = await retrieve(query, user_role, source_types=source_types, top_k=top_k,
                            mailboxes=mailboxes)

    contexts: list[str] = []
    for chunk in chunks:
        content = (chunk.get("content") or "").strip()
        if not content:
            continue

        # Ancrage de provenance : nom de fichier si dispo, sinon type de source.
        source = chunk.get("source_filename") or chunk.get("source_type") or "document"
        contexts.append(f"[{source}]\n{content}")

    return contexts
