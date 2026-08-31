-- ============================================================
--  027 — La recherche documentaire à l'échelle : HNSW + plein texte français
-- ============================================================
--
-- POURQUOI (31/08/2026). « Il a beaucoup de mal avec les recherches dans la
-- base s'il y a plusieurs milliers de data. » Trois causes dans l'index :
--
--   * l'index vectoriel était un ivfflat CONSTRUIT SUR UNE TABLE VIDE (001) :
--     ses 100 centroïdes ont été calculés sans aucune donnée, et pgvector ne
--     les recalcule jamais — la recherche approchée rate donc des voisins
--     évidents, d'autant plus que le corpus grossit. HNSW n'a pas de phase
--     d'apprentissage : il se construit à vide et reste juste ;
--   * aucun index PLEIN TEXTE : le seul repli lexical passait par les
--     trigrammes sur le contenu entier, qui ne rendaient rien face à un
--     morceau de 380 mots. `to_tsvector('french')` lemmatise (drainage,
--     drainages, drainé), ignore les mots vides, et tient à des centaines de
--     milliers de morceaux ;
--   * les filtres (type de source, niveau d'accès) parcouraient deux index
--     séparés : un index composé sert directement les recherches ciblées.
--
-- Idempotente ; à la première application, la construction HNSW prend
-- quelques secondes pour quelques milliers de morceaux (m=16, ef=64 : les
-- valeurs d'usage, recall > 95 % en cosinus).

DROP INDEX IF EXISTS idx_documents_embedding_cosine;

CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
    ON documents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_documents_fts_fr
    ON documents
    USING gin (to_tsvector('french', content));

CREATE INDEX IF NOT EXISTS idx_documents_type_niveau
    ON documents (source_type, access_level);

ANALYZE documents;
