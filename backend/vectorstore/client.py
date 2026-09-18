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
from config import settings


# Le filet par trigrammes (fautes, formes voisines) : seulement quand le plein texte
# trouve moins de SEUIL morceaux, et jamais plus de DELAI ms (18/09).
SEUIL_FILET_TRIGRAMMES = 5
DELAI_FILET_TRIGRAMMES_MS = 10000


class VectorStoreClient:
    """Interface principale pour les opérations pgvector. Singleton — instancier une fois au démarrage."""

    # ── Les filtres communs aux voies de recherche ─────────────────────────
    @staticmethod
    def _filtres(params: list, source_types: Optional[List[str]], fichier: Optional[str],
                 boites: Optional[List[str]] = None) -> str:
        """`source_type`, `source_filename` et les BOÎTES autorisées : les
        valeurs voyagent en PARAMÈTRE, jamais dans le texte SQL.

        LES DROITS AVANT LE TOP_K (16/09, audit D-09/S-09). Le cloisonnement des
        boîtes mail se faisait APRÈS la recherche : on demandait trois fois
        plus de morceaux « pour avoir de la marge », puis on jetait ceux des
        boîtes fermées. Deux conséquences : de bons documents restaient dehors
        quand la marge ne suffisait pas, et les COMPTES (« 12 documents parlent
        de… ») comptaient ce que la personne n'a pas le droit de voir. Le
        filtre est donc dans la requête ; le post-filtre reste, en défense.
        """
        clauses = ""
        if source_types:
            params.append(list(source_types))
            clauses += f" AND source_type = ANY(${len(params)}::text[])"
        if fichier and str(fichier).strip():
            params.append(f"%{str(fichier).strip()}%")
            clauses += f" AND source_filename ILIKE ${len(params)}"
        clauses += VectorStoreClient._clause_boites(params, boites)
        return clauses

    # Les types de documents qui viennent d'une boîte mail : eux seuls sont
    # soumis au filtre des boîtes (un devis du NAS n'a pas de boîte).
    TYPES_MAIL = ("email", "email_sent")

    @staticmethod
    def _clause_boites(params: list, boites: Optional[List[str]]) -> str:
        """FAIL-CLOSED : sans liste de boîtes, aucun mail ne sort. « * » = accès
        administrateur (tous), « !email_sent » retire les envoyés."""
        if boites is None:
            return ""
        autorisees = {(b or "").strip().lower() for b in boites if b}
        clauses = ""
        if "!email_sent" in autorisees:
            params.append("email_sent")
            clauses += f" AND source_type <> ${len(params)}"
            autorisees.discard("!email_sent")
        if "*" in autorisees:
            return clauses                    # administrateur : toutes les boîtes
        params.append(list(VectorStoreClient.TYPES_MAIL))
        types_mail = f"${len(params)}::text[]"
        if not autorisees:
            return clauses + f" AND source_type <> ALL({types_mail})"
        params.append(sorted(autorisees))
        # `source_id` d'un mail : « email:<boîte>:<identifiant> ». Une boîte
        # indéterminable (ingestion d'une version antérieure) reste écartée.
        return (clauses + f" AND (source_type <> ALL({types_mail})"
                f" OR lower(split_part(source_id, ':', 2)) = ANY(${len(params)}::text[]))")

    async def search(
        self,
        query_embedding: List[float],
        user_role: str,
        source_types: Optional[List[str]] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.3,
        fichier: Optional[str] = None,
        boites: Optional[List[str]] = None,
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
        filtres = self._filtres(params, source_types, fichier, boites)
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
                    if getattr(query_embedding, 'modele', None):
                        from vectorstore.generation import verifier_vecteur
                        await conn.execute('LOCK TABLE documents IN ACCESS SHARE MODE')
                        if not await verifier_vecteur(conn, query_embedding): return []
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
        boites: Optional[List[str]] = None,
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
        filtres = self._filtres(params, source_types, fichier, boites)
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
            # LE FILET DES TRIGRAMMES EST UN FILET, PAS UNE SECONDE RECHERCHE (18/09, mesuré en
            # production sur 130 893 morceaux) : le plein texte répond en 53 ms, mais « date limite
            # de remise des offres La Teste » faisait rouvrir 89 881 morceaux par l'index trigramme
            # — 64 s — parce que le plein texte avait trouvé 29 morceaux « seulement » sur 60
            # demandés. Chaque `rechercher_documents` coûtait trois minutes. Le filet ne part plus
            # que si le plein texte ne trouve presque RIEN (fautes, formes voisines), et jamais
            # plus de 10 s : au-delà il cède, les résultats du plein texte restent.
            if len(resultats) < min(top_k, SEUIL_FILET_TRIGRAMMES):
                vus = {str(r["id"]) for r in resultats}
                try:
                    async with conn.transaction():
                        await conn.execute(f"SET LOCAL statement_timeout = '{DELAI_FILET_TRIGRAMMES_MS}'")
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
                except Exception as e:  # noqa: BLE001 — délai dépassé : le plein texte suffit
                    import logging
                    logging.getLogger(__name__).info("Filet trigramme écarté (%s) : plein texte seul", type(e).__name__)
            return resultats[:top_k]

    async def count_lexical(
        self,
        query_text: str,
        user_role: str,
        source_types: Optional[List[str]] = None,
        fichier: Optional[str] = None,
        boites: Optional[List[str]] = None,
    ) -> tuple[int, int]:
        """Le COMPTE exact des morceaux et des documents qui portent les termes
        cherchés — bon marché grâce aux index, et c'est lui qu'on cite pour
        « combien de documents parlent de … »."""
        allowed_levels = ROLE_ACCESS_LEVELS.get(user_role, ["all"])
        texte = " ".join((query_text or "").split())
        if not texte:
            return 0, 0
        params: list = [texte, allowed_levels]
        filtres = self._filtres(params, source_types, fichier, boites)
        # LE COMPTE SE FAIT PAR LE PLEIN TEXTE (18/09) : l'alternative trigramme dans la même requête forçait la relecture
        # trigramme de tout le corpus — 125 s mesurées en production pour un compte. Les trigrammes
        # ne comptent que si le plein texte ne trouve rien, et cèdent au bout de 10 s.
        async with get_db() as conn:
            row = await conn.fetchrow(f"""
                SELECT COUNT(*) AS morceaux, COUNT(DISTINCT (source_type, source_id)) AS documents
                FROM documents
                WHERE access_level = ANY($2::text[])
                  AND is_anonymized = true
                  AND to_tsvector('french', content) @@ websearch_to_tsquery('french', $1)
                  {filtres}
            """, *params)
            if int(row["morceaux"] or 0) == 0:
                try:
                    async with conn.transaction():
                        await conn.execute(f"SET LOCAL statement_timeout = '{DELAI_FILET_TRIGRAMMES_MS}'")
                        row = await conn.fetchrow(f"""
                            SELECT COUNT(*) AS morceaux, COUNT(DISTINCT (source_type, source_id)) AS documents
                            FROM documents
                            WHERE access_level = ANY($2::text[])
                              AND is_anonymized = true
                              AND $1 <% content
                              {filtres}
                        """, *params)
                except Exception:  # noqa: BLE001 — délai dépassé : le compte du plein texte (zéro) reste
                    pass
            return int(row["morceaux"] or 0), int(row["documents"] or 0)

    async def search_hybrid(
        self,
        query_text: str,
        query_embedding: Optional[List[float]],
        user_role: str,
        top_k: int = 5,
        source_types: Optional[List[str]] = None,
        fichier: Optional[str] = None,
        boites: Optional[List[str]] = None,
        diagnostic: Optional[dict] = None,
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
            # LA VOIE VECTORIELLE A SON FILET (16/09, audit D-06/S-06) : un vecteur de
            # la mauvaise dimension ou un index en panne ne doit pas emporter la
            # voie plein texte avec lui.
            try:
                voies["vecteur"] = await self.search(query_embedding, user_role, source_types,
                                                     top_k=top_k, fichier=fichier, boites=boites)
            except Exception as e:  # noqa: BLE001
                if diagnostic is not None:
                    diagnostic["erreur_vecteur"] = type(e).__name__
                import logging
                logging.getLogger(__name__).warning(
                    "Voie vectorielle écartée (%s) : plein texte seul", type(e).__name__)
        voies["texte"] = await self.search_lexical(query_text, user_role, source_types,
                                                   top_k=top_k, fichier=fichier, boites=boites)
        if diagnostic is not None:
            diagnostic["voies"] = list(voies)
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

    async def remplacer_source(self, chunks: List[str], source_type: str, source_id: str,
                               source_filename: Optional[str] = None, access_level: str = "all",
                               contains_pii: bool = True, is_anonymized: bool = True,
                               embeddings: Optional[List[Optional[List[float]]]] = None) -> int:
        """Remplace TOUS les morceaux d'une source par les nouveaux, en UNE
        transaction (16/09, audit D-08/S-08).

        Avant : `delete_by_source` puis N insertions séparées. Une coupure au
        milieu — redémarrage, base qui ferme, plafond atteint — laissait le
        document ABSENT de la mémoire, ou à moitié réindexé, alors que
        l'ancienne version était parfaitement lisible une seconde plus tôt.
        Ici, l'ancienne génération reste lisible jusqu'à la bascule : si la
        transaction échoue, rien n'a bougé.

        Rend le nombre de morceaux écrits. Ne supprime jamais sur une liste
        vide : un texte vide après une extraction défaillante ne remplace pas
        une version valide.
        """
        if not chunks:
            return 0
        total = len(chunks)
        async with get_db() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM documents WHERE source_id = $1 AND source_type = $2",
                                   source_id, source_type)
                a_vectoriser = []
                for i, contenu in enumerate(chunks):
                    vecteur = (embeddings or [None] * total)[i] if embeddings else None
                    doc_id = await conn.fetchval("""
                        INSERT INTO documents (
                            content, embedding, source_type, source_id,
                            source_filename, access_level, chunk_index, chunk_total,
                            contains_pii, is_anonymized, content_tokens
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                                  array_length(string_to_array($1, ' '), 1))
                        RETURNING id
                    """, contenu, _vec_literal(vecteur) if vecteur else None, source_type, source_id,
                        source_filename, access_level, i, total, contains_pii, is_anonymized)
                    if vecteur is None:
                        a_vectoriser.append(doc_id)
                if a_vectoriser:
                    await conn.execute(
                        "INSERT INTO embedding_jobs (document_id, status) "
                        "SELECT unnest($1::uuid[]), 'pending'", a_vectoriser)
                return total

    async def copier_source(self, source_id_origine: str, source_type: str, source_id: str,
                            source_filename: Optional[str] = None, access_level: str = "all") -> int:
        """Reprend les morceaux d'une source au contenu IDENTIQUE sous une autre
        source (16/09, audit D-27/S-27) : même texte et mêmes vecteurs, mais le nom
        de fichier et le NIVEAU D'ACCÈS de la copie — un même CCTP dans deux
        affaires ne fusionne pas leurs droits. Un morceau pas encore vectorisé
        reçoit son job. Rend le nombre de morceaux repris ; 0 si l'original n'en
        a plus (l'appelant relit alors le fichier)."""
        if not source_id_origine or source_id_origine == source_id:
            return 0
        async with get_db() as conn:
            async with conn.transaction():
                existe = await conn.fetchval(
                    "SELECT count(*) FROM documents WHERE source_id = $1 AND source_type = $2",
                    source_id_origine, source_type)
                if not existe:
                    return 0
                await conn.execute("DELETE FROM documents WHERE source_id = $1 AND source_type = $2",
                                   source_id, source_type)
                lignes = await conn.fetch("""
                    INSERT INTO documents (
                        content, content_tokens, embedding, source_type, source_id,
                        source_filename, access_level, contains_pii, is_anonymized,
                        chunk_index, chunk_total
                    )
                    SELECT content, content_tokens, embedding, source_type, $3,
                           $4, $5, contains_pii, is_anonymized, chunk_index, chunk_total
                      FROM documents
                     WHERE source_id = $1 AND source_type = $2
                     ORDER BY chunk_index
                    RETURNING id, (embedding IS NULL) AS a_vectoriser
                """, source_id_origine, source_type, source_id, source_filename, access_level)
                a_vectoriser = [l["id"] for l in lignes if l["a_vectoriser"]]
                if a_vectoriser:
                    await conn.execute(
                        "INSERT INTO embedding_jobs (document_id, status) "
                        "SELECT unnest($1::uuid[]), 'pending'", a_vectoriser)
                return len(lignes)

    async def requalifier_drive(self, source_id: str, niveau: str) -> None:
        """Un changement de dossier/droits ne dépend pas d'une nouvelle extraction."""
        async with get_db() as conn:
            await conn.execute("UPDATE documents SET access_level = $2 WHERE source_type = 'drive' AND source_id = $1",
                               source_id, niveau)

    async def reconcilier_drive(self, presents) -> int:
        """À appeler UNIQUEMENT après un inventaire global complet et autorisé."""
        async with get_db() as conn:
            resultat = await conn.execute(
                "DELETE FROM documents WHERE source_type = 'drive' AND NOT (source_id = ANY($1::text[]))",
                list(presents))
        return int(resultat.split()[-1])

    async def delete_by_source(self, source_id: str, source_type: str) -> int:
        """Supprime tous les chunks d'une source (pour ré-ingestion après modification)."""
        async with get_db() as conn:
            result = await conn.execute("""
                DELETE FROM documents WHERE source_id = $1 AND source_type = $2
            """, source_id, source_type)
            return int(result.split()[-1])

    async def get_pending_embedding_jobs(self, limit: int = 50, preneur: Optional[str] = None,
                                         bail_s: int = 300) -> List[dict]:
        """Réclame un lot de jobs de vectorisation, AVEC UN BAIL (16/09, audit D-17/S-17).

        Avant : un simple SELECT des jobs « en attente ». Deux workers — ou un
        redémarrage en plein lot — pouvaient travailler le MÊME job : le
        fournisseur était payé deux fois, et le résultat le plus lent écrasait
        le plus récent. `FOR UPDATE SKIP LOCKED` fait que deux preneurs ne
        prennent jamais la même ligne ; le bail fait qu'un worker mort ne
        bloque pas la file (passé l'heure, le job revient).

        Sans la migration 047, on retombe sur l'ancienne requête : la file
        continue de tourner, sans la garantie.
        """
        import os as _os
        preneur = preneur or f"worker-{_os.getpid()}"
        async with get_db() as conn:
            try:
                async with conn.transaction():
                    rows = await conn.fetch("""
                        WITH pris AS (
                            SELECT ej.id
                              FROM embedding_jobs ej
                             WHERE ej.status = 'pending'
                               AND ej.attempts < ej.max_attempts
                               AND (ej.lease_until IS NULL OR ej.lease_until < NOW())
                               AND (ej.next_attempt_at IS NULL OR ej.next_attempt_at <= NOW())
                             ORDER BY ej.created_at ASC
                             LIMIT $1
                               FOR UPDATE SKIP LOCKED
                        )
                        UPDATE embedding_jobs ej
                           SET claimed_by = $2, lease_until = NOW() + ($3::int * INTERVAL '1 second')
                          FROM pris, documents d
                         WHERE ej.id = pris.id AND d.id = ej.document_id
                     RETURNING ej.id AS job_id, ej.document_id, ej.attempts,
                               d.content, d.source_type
                    """, limit, preneur, max(30, int(bail_s)))
                    return [dict(row) for row in rows]
            except Exception as e:  # noqa: BLE001
                from database.connection import schema_incomplet
                if not schema_incomplet(e):
                    raise
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

    async def mark_job_completed(self, job_id: UUID, embedding: List[float],
                                 modele: Optional[str] = None, preneur: Optional[str] = None) -> None:
        # LA DIMENSION EST VÉRIFIÉE AVANT D'ÉCRIRE, et c'est ce qui empêche une
        # boucle infinie. La colonne est `vector(1536)` : un vecteur d'une autre
        # longueur fait échouer le cast, ce qui annule la TRANSACTION ENTIÈRE —
        # donc le job reste 'pending' et son compteur d'essais n'est PAS
        # incrémenté. Le worker le reprend au tour suivant, repaie l'appel au
        # fournisseur, et recommence indéfiniment. Un modèle d'embedding mal
        # choisi (bge-m3 rend 1024) suffisait à le déclencher, et rien à
        # l'écran ne l'aurait dit.
        #
        # On marque donc le job en ÉCHEC, avec sa raison : il consomme un essai,
        # s'arrête après le troisième, et la cause est lisible.
        # 02/09 : la dimension vient de la COLONNE, pas de la configuration.
        # Après une re-vectorisation, une valeur figée dans le fichier aurait
        # fait refuser tous les vecteurs du nouveau modèle, en accusant le
        # modèle alors que la base était d'accord avec lui.
        from vectorstore.revectorisation import dimension_attendue
        attendue = await dimension_attendue()
        if embedding is not None and len(embedding) != attendue:
            await self.mark_job_failed(
                job_id,
                f"dimension {len(embedding)} au lieu de {attendue} : le modèle "
                "d'embedding ne correspond pas au schéma de la base. Changer de "
                "modèle exige de re-vectoriser tout le corpus.", preneur=preneur)
            return
        async with get_db() as conn:
            async with conn.transaction():
                if modele:
                    await conn.execute('LOCK TABLE documents IN ROW EXCLUSIVE MODE')
                    actif = await conn.fetchval('SELECT modele FROM embedding_actif WHERE id=1')
                    if actif and actif != modele: return
                # LE BAIL EST VÉRIFIÉ AVANT D'ÉCRIRE (audit D-17/S-17) : un worker
                # dont le bail a expiré — parce qu'il a été long — ne doit pas
                # écraser le travail de celui qui a repris le job entre-temps.
                try:
                    async with conn.transaction():
                        pris = await conn.fetchval("""
                            UPDATE embedding_jobs
                               SET status = 'completed', processed_at = NOW(), lease_until = NULL
                             WHERE id = $1
                               AND status = 'pending'
                               AND (($2::text IS NULL AND claimed_by IS NULL)
                                    OR (claimed_by = $2 AND lease_until > NOW()))
                         RETURNING document_id
                        """, job_id, preneur)
                except Exception as e:  # noqa: BLE001
                    from database.connection import schema_incomplet
                    if not schema_incomplet(e):
                        raise
                    pris = await conn.fetchval("""
                        UPDATE embedding_jobs SET status = 'completed', processed_at = NOW()
                         WHERE id = $1 RETURNING document_id
                    """, job_id)
                if pris is None:
                    logger = __import__("logging").getLogger("duret.vectorstore")
                    logger.info("Job %s : bail perdu, résultat ignoré (un autre l'a repris)", str(job_id)[:8])
                    return
                try:
                    async with conn.transaction():
                        await conn.execute("""
                            UPDATE documents
                            SET embedding = $1::vector, embedding_modele = COALESCE($3, embedding_modele),
                                updated_at = NOW()
                            WHERE id = $2
                        """, _vec_literal(embedding), pris, modele)
                except Exception as e:  # noqa: BLE001
                    from database.connection import schema_incomplet
                    if not schema_incomplet(e):
                        raise
                    await conn.execute("""
                        UPDATE documents SET embedding = $1::vector, updated_at = NOW() WHERE id = $2
                    """, _vec_literal(embedding), pris)

    async def mark_job_failed(self, job_id: UUID, error: str, preneur: Optional[str] = None) -> None:
        async with get_db() as conn:
            await conn.execute("""
                UPDATE embedding_jobs
                SET status = CASE
                        WHEN attempts + 1 >= max_attempts THEN 'failed'
                        ELSE 'pending'
                    END,
                    attempts = attempts + 1,
                    error_message = $2,
                    lease_until = NULL,
                    claimed_by = NULL
                WHERE id = $1
                  AND status = 'pending'
                  AND (($3::text IS NULL AND claimed_by IS NULL)
                       OR (claimed_by = $3 AND lease_until > NOW()))
            """, job_id, error, preneur)


# Singleton — importé par les agents
vectorstore = VectorStoreClient()
