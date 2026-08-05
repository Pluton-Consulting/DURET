"""
Client pgvector — interface de recherche sémantique
Gère la recherche hybride (vecteur + filtres métadonnées) et l'insertion de documents.

Note : la vectorisation (génération des embeddings) est intentionnellement
absente — elle sera implémentée dans le pipeline d'ingestion (prochaine itération).
"""
from typing import List, Optional
from uuid import UUID
from database.connection import get_db


def _vec_literal(vec: List[float]) -> str:
    """
    Formate un vecteur au format texte pgvector ('[0.1,0.2,…]').
    asyncpg n'enregistre pas le type `vector` : on passe une chaîne + cast ::vector,
    robuste sur toutes les versions de pgvector.
    """
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"

# Échelle des accès : définie dans `security/acces.py`, source unique partagée
# avec le catalogue de skills. Réexportée ici pour ne rien casser des appelants.
from security.acces import ROLE_ACCESS_LEVELS  # noqa: F401


class VectorStoreClient:
    """Interface principale pour les opérations pgvector. Singleton — instancier une fois au démarrage."""

    async def search(
        self,
        query_embedding: List[float],
        user_role: str,
        source_types: Optional[List[str]] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.3,
    ) -> List[dict]:
        """
        Recherche sémantique avec filtres d'accès par rôle.
        Retourne uniquement des chunks is_anonymized=true.
        """
        allowed_levels = ROLE_ACCESS_LEVELS.get(user_role, ["all"])

        async with get_db() as conn:
            source_filter = ""
            params: list = [_vec_literal(query_embedding), allowed_levels, top_k, similarity_threshold]

            if source_types:
                source_filter = "AND source_type = ANY($5::text[])"
                params.append(source_types)

            rows = await conn.fetch(f"""
                SELECT
                    id,
                    content,
                    source_type,
                    source_id,
                    source_filename,
                    chunk_index,
                    chunk_total,
                    1 - (embedding <=> $1::vector) AS similarity
                FROM documents
                WHERE access_level = ANY($2::text[])
                  AND is_anonymized = true
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> $1::vector) >= $4
                  {source_filter}
                ORDER BY embedding <=> $1::vector
                LIMIT $3
            """, *params)

            return [dict(row) for row in rows]

    async def search_hybrid(
        self,
        query_text: str,
        query_embedding: Optional[List[float]],
        user_role: str,
        top_k: int = 5,
    ) -> List[dict]:
        """
        Recherche hybride : vecteur si embedding disponible,
        fallback pg_trgm full-text sinon.
        """
        if query_embedding:
            return await self.search(query_embedding, user_role, top_k=top_k)

        allowed_levels = ROLE_ACCESS_LEVELS.get(user_role, ["all"])
        async with get_db() as conn:
            rows = await conn.fetch("""
                SELECT id, content, source_type, source_id,
                       similarity(content, $1) AS similarity
                FROM documents
                WHERE access_level = ANY($2::text[])
                  AND is_anonymized = true
                  AND content % $1
                ORDER BY similarity DESC
                LIMIT $3
            """, query_text, allowed_levels, top_k)
            return [dict(row) for row in rows]

    async def insert_document_chunk(
        self,
        content: str,
        source_type: str,
        source_id: str,
        access_level: str = "all",
        source_filename: Optional[str] = None,
        chunk_index: int = 0,
        chunk_total: int = 1,
        embedding: Optional[List[float]] = None,
        contains_pii: bool = False,
        is_anonymized: bool = False,
    ) -> UUID:
        """
        Insère un chunk de document.
        Si embedding est None, crée un embedding_job pour vectorisation différée.
        """
        async with get_db() as conn:
            async with conn.transaction():
                doc_id = await conn.fetchval("""
                    INSERT INTO documents (
                        content, embedding, source_type, source_id,
                        source_filename, access_level, chunk_index, chunk_total,
                        contains_pii, is_anonymized,
                        content_tokens
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                              array_length(string_to_array($1, ' '), 1))
                    RETURNING id
                """,
                    content,
                    embedding,
                    source_type, source_id, source_filename,
                    access_level, chunk_index, chunk_total,
                    contains_pii, is_anonymized,
                )

                if embedding is None:
                    await conn.execute("""
                        INSERT INTO embedding_jobs (document_id, status)
                        VALUES ($1, 'pending')
                    """, doc_id)

                return doc_id

    async def delete_by_source(self, source_id: str, source_type: str) -> int:
        """Supprime tous les chunks d'une source (pour ré-ingestion après modification)."""
        async with get_db() as conn:
            result = await conn.execute("""
                DELETE FROM documents WHERE source_id = $1 AND source_type = $2
            """, source_id, source_type)
            return int(result.split()[-1])

    async def get_pending_embedding_jobs(self, limit: int = 50) -> List[dict]:
        """Récupère les jobs de vectorisation en attente (appelé par le pipeline d'ingestion)."""
        async with get_db() as conn:
            rows = await conn.fetch("""
                SELECT ej.id AS job_id, ej.document_id, ej.attempts,
                       d.content, d.source_type
                FROM embedding_jobs ej
                JOIN documents d ON d.id = ej.document_id
                WHERE ej.status = 'pending'
                  AND ej.attempts < ej.max_attempts
                ORDER BY ej.created_at ASC
                LIMIT $1
            """, limit)
            return [dict(row) for row in rows]

    async def mark_job_completed(self, job_id: UUID, embedding: List[float]) -> None:
        async with get_db() as conn:
            async with conn.transaction():
                await conn.execute("""
                    UPDATE embedding_jobs
                    SET status = 'completed', processed_at = NOW()
                    WHERE id = $1
                """, job_id)
                await conn.execute("""
                    UPDATE documents
                    SET embedding = $1::vector, updated_at = NOW()
                    WHERE id = (SELECT document_id FROM embedding_jobs WHERE id = $2)
                """, _vec_literal(embedding), job_id)

    async def mark_job_failed(self, job_id: UUID, error: str) -> None:
        async with get_db() as conn:
            await conn.execute("""
                UPDATE embedding_jobs
                SET status = CASE
                        WHEN attempts + 1 >= max_attempts THEN 'failed'
                        ELSE 'pending'
                    END,
                    attempts = attempts + 1,
                    error_message = $2
                WHERE id = $1
            """, job_id, error)


# Singleton — importé par les agents
vectorstore = VectorStoreClient()
