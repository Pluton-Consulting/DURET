"""
Client pgvector — interface de recherche sémantique
Gère la recherche hybride (vecteur + plein texte + trigrammes, fusionnés — voir
`vectorstore/fusion.py`), les filtres d'accès et l'insertion de documents.

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

    # ── Les filtres communs aux voies de recherche ─────────────────────────
    @staticmethod
    def _filtres(params: list, source_types: Optional[List[str]], fichier: Optional[str]) -> str:
        """`source_type` et `source_filename` : les valeurs voyagent en PARAMÈTRE,
        jamais dans le texte SQL — même règle que partout ici."""
        clauses = ""
        if source_types:
            params.append(list(source_types))
            clauses += f" AND source_type = ANY(${len(params)}::text[])"
        if fichier and str(fichier).strip():
            params.append(f"%{str(fichier).strip()}%")
            clauses += f" AND source_filename ILIKE ${len(params)}"
        return clauses

    async def search(
        self,
        query_embedding: List[float],
        user_role: str,
        source_types: Optional[List[str]] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.3,
        fichier: Optional[str] = None,
    ) -> List[dict]:
        """
        Recherche VECTORIELLE avec filtres d'accès par rôle.
        Retourne uniquement des chunks is_anonymized=true et vectorisés.

        `hnsw.ef_search` : la taille de la liste candidate de l'index HNSW
        (migration 027). À 40 par défaut, une recherche à 200 morceaux de
        profondeur en rendait 40 : on l'aligne sur ce qu'on demande. Posé en
        SET LOCAL, dans une transaction — le pool partage ses connexions.
        """
        allowed_levels = ROLE_ACCESS_LEVELS.get(user_role, ["all"])
        top_k = max(1, int(top_k))
        params: list = [_vec_literal(query_embedding), allowed_levels, top_k, similarity_threshold]
        filtres = self._filtres(params, source_types, fichier)
        requete = f"""
            SELECT
                id, content, source_type, source_id, source_filename,
                chunk_index, chunk_total,
                1 - (embedding <=> $1::vector) AS similarity
            FROM documents
            WHERE access_level = ANY($2::text[])
              AND is_anonymized = true
              AND embedding IS NOT NULL
              AND 1 - (embedding <=> $1::vector) >= $4
              {filtres}
            ORDER BY embedding <=> $1::vector
            LIMIT $3
        """
        async with get_db() as conn:
            try:
                async with conn.transaction():
                    await conn.execute(f"SET LOCAL hnsw.ef_search = {min(1000, max(40, top_k))}")
                    rows = await conn.fetch(requete, *params)
            except Exception:  # noqa: BLE001 — pgvector sans HNSW : la requête vaut sans le réglage
                rows = await conn.fetch(requete, *params)
            return [dict(row) for row in rows]

    async def search_lexical(
        self,
        query_text: str,
        user_role: str,
        source_types: Optional[List[str]] = None,
        top_k: int = 5,
        fichier: Optional[str] = None,
    ) -> List[dict]:
        """
        Recherche LEXICALE : plein texte français (index GIN de la migration
        027) puis trigrammes de MOTS pour les fautes et les formes voisines.

        C'est la voie qui atteint les morceaux SANS embedding (la moitié du
        corpus le 31/08) et qui tient à des centaines de milliers de morceaux :
        un index, pas un parcours. `word_similarity` (opérateur <%) compare la
        question au MEILLEUR passage du morceau — l'ancien `content % requête`
        comparait trois mots à trois cents et ne trouvait jamais rien.
        """
        allowed_levels = ROLE_ACCESS_LEVELS.get(user_role, ["all"])
        top_k = max(1, int(top_k))
        texte = " ".join((query_text or "").split())
        if not texte:
            return []
        params: list = [texte, allowed_levels, top_k]
        filtres = self._filtres(params, source_types, fichier)
        async with get_db() as conn:
            rows = await conn.fetch(f"""
                SELECT id, content, source_type, source_id, source_filename,
                       chunk_index, chunk_total,
                       ts_rank_cd(to_tsvector('french', content),
                                  websearch_to_tsquery('french', $1)) AS similarity
                FROM documents
                WHERE access_level = ANY($2::text[])
                  AND is_anonymized = true
                  AND to_tsvector('french', content) @@ websearch_to_tsquery('french', $1)
                  {filtres}
                ORDER BY similarity DESC
                LIMIT $3
            """, *params)
            resultats = [dict(r) for r in rows]
            if len(resultats) < top_k:
                vus = {str(r["id"]) for r in resultats}
                rows = await conn.fetch(f"""
                    SELECT id, content, source_type, source_id, source_filename,
                           chunk_index, chunk_total,
                           word_similarity($1, content) AS similarity
                    FROM documents
                    WHERE access_level = ANY($2::text[])
                      AND is_anonymized = true
                      AND $1 <% content
                      {filtres}
                    ORDER BY similarity DESC
                    LIMIT $3
                """, *params)
                resultats += [dict(r) for r in rows if str(r["id"]) not in vus]
            return resultats[:top_k]

    async def count_lexical(
        self,
        query_text: str,
        user_role: str,
        source_types: Optional[List[str]] = None,
        fichier: Optional[str] = None,
    ) -> tuple[int, int]:
        """Le COMPTE exact des morceaux et des documents qui portent les termes
        cherchés — bon marché grâce aux index, et c'est lui qu'on cite pour
        « combien de documents parlent de … »."""
        allowed_levels = ROLE_ACCESS_LEVELS.get(user_role, ["all"])
        texte = " ".join((query_text or "").split())
        if not texte:
            return 0, 0
        params: list = [texte, allowed_levels]
        filtres = self._filtres(params, source_types, fichier)
        async with get_db() as conn:
            row = await conn.fetchrow(f"""
                SELECT COUNT(*) AS morceaux, COUNT(DISTINCT (source_type, source_id)) AS documents
                FROM documents
                WHERE access_level = ANY($2::text[])
                  AND is_anonymized = true
                  AND (to_tsvector('french', content) @@ websearch_to_tsquery('french', $1)
                       OR $1 <% content)
                  {filtres}
            """, *params)
            return int(row["morceaux"] or 0), int(row["documents"] or 0)

    async def search_hybrid(
        self,
        query_text: str,
        query_embedding: Optional[List[float]],
        user_role: str,
        top_k: int = 5,
        source_types: Optional[List[str]] = None,
        fichier: Optional[str] = None,
    ) -> List[dict]:
        """
        Recherche HYBRIDE : la voie vectorielle ET la voie lexicale, TOUJOURS
        les deux, fusionnées par rang réciproque (`vectorstore.fusion`).

        Avant : vecteur seul, et le lexical uniquement si le vecteur ne rendait
        RIEN — donc jamais dans le cas courant, alors que la moitié du corpus
        n'a pas d'embedding et n'existait pas pour la voie vectorielle.
        """
        from vectorstore.fusion import fusionner
        voies: dict = {}
        if query_embedding:
            voies["vecteur"] = await self.search(query_embedding, user_role, source_types,
                                                 top_k=top_k, fichier=fichier)
        voies["texte"] = await self.search_lexical(query_text, user_role, source_types,
                                                   top_k=top_k, fichier=fichier)
        return fusionner(voies)[:max(1, int(top_k))]

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
