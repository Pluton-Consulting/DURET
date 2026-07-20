-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- TABLES MÉTIER
-- ============================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'terrain',
    -- Rôles: 'direction', 'commercial', 'bureau_etudes', 'conducteur', 'administratif', 'terrain', 'admin'
    actif BOOLEAN NOT NULL DEFAULT true,
    quota_mensuel INTEGER NOT NULL DEFAULT 50,
    -- Quotas par défaut selon rôle (peut être overridé)
    -- direction: NULL (illimité), commercial: 200, bureau_etudes: 150
    -- conducteur: 100, administratif: 100, terrain: 50
    bypass_schedule BOOLEAN NOT NULL DEFAULT false,
    -- Si true : accès hors plage horaire autorisé (direction uniquement)
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login TIMESTAMPTZ
);

CREATE TABLE roles_permissions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role VARCHAR(50) NOT NULL,
    feature VARCHAR(100) NOT NULL,
    -- Features: 'chat_agent1', 'chat_agent2', 'chat_agent3',
    -- 'view_dashboard_global', 'view_own_stats', 'validate_skills',
    -- 'manage_users', 'configure_agents', 'view_costs_global',
    -- 'view_own_costs', 'view_audit_log'
    allowed BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(role, feature)
);

CREATE TABLE threads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(255),
    -- Généré automatiquement depuis les premiers mots de la première requête
    agent_type VARCHAR(20) NOT NULL DEFAULT 'agent1',
    -- 'agent1', 'agent2', 'agent3', 'multi'
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    -- 'active', 'paused', 'completed', 'error'
    langgraph_thread_id VARCHAR(255) UNIQUE,
    -- thread_id utilisé par LangGraph pour le checkpointing
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    -- 'user', 'assistant', 'system'
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    -- Stocke: agent_used, tokens_in, tokens_out, model_used, duration_ms
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    -- NULL si action système
    action VARCHAR(100) NOT NULL,
    -- 'chat_request', 'login', 'logout', 'skill_created',
    -- 'skill_validated', 'user_created', 'user_deactivated', 'quota_exceeded'
    agent_id VARCHAR(20),
    -- 'agent1', 'agent2', 'agent3', NULL si hors agent
    model_used VARCHAR(100),
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_eur DECIMAL(10, 6) DEFAULT 0,
    duration_ms INTEGER,
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Immuable : pas d'UPDATE, pas de DELETE sur cette table
);

CREATE TABLE skills (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) UNIQUE NOT NULL,
    -- snake_case ex: 'calcul_surface_terrasse'
    description TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    code TEXT NOT NULL,
    -- Le code Python du skill généré par l'Agent 3
    prompt_template TEXT,
    -- Le prompt associé au skill
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    -- 'draft', 'testing', 'validated', 'stable', 'deprecated'
    confidence_score DECIMAL(3, 2),
    -- Score 0.00 à 1.00 calculé par les tests Daytona
    usage_count INTEGER NOT NULL DEFAULT 0,
    avg_quality_score DECIMAL(3, 2),
    created_by VARCHAR(20) DEFAULT 'agent3',
    validated_by UUID REFERENCES users(id),
    validated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE api_usage_daily (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    request_count INTEGER NOT NULL DEFAULT 0,
    tokens_total INTEGER NOT NULL DEFAULT 0,
    cost_eur DECIMAL(10, 4) NOT NULL DEFAULT 0,
    UNIQUE(user_id, date)
);

-- ============================================================
-- TABLES RAG / VECTORSTORE
-- ============================================================

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    content TEXT NOT NULL,
    content_tokens INTEGER,

    embedding vector(1536),
    -- Dimension 1536 = text-embedding-3-small compatible
    -- NULL si pas encore vectorisé

    source_type VARCHAR(50) NOT NULL,
    -- 'devis', 'chantier', 'client', 'plan_pdf', 'photo',
    -- 'email', 'catalogue_fournisseur', 'methode_interne',
    -- 'sketchup', 'planning', 'document_admin'
    source_id VARCHAR(255),
    source_filename VARCHAR(500),

    access_level VARCHAR(50) NOT NULL DEFAULT 'all',
    -- 'all', 'commercial_plus', 'bureau_etudes_plus', 'direction_only', 'admin_only'

    contains_pii BOOLEAN DEFAULT false,
    is_anonymized BOOLEAN DEFAULT false,

    chunk_index INTEGER DEFAULT 0,
    chunk_total INTEGER DEFAULT 1,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ
);

CREATE TABLE document_metadata (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL,

    title VARCHAR(500),
    date_document DATE,

    data JSONB DEFAULT '{}',
    -- Exemples:
    -- devis : { "client_id": "...", "montant_ht": null, "statut": "signé" }
    -- chantier : { "ville": "Arcachon", "type": "terrasse_bois", "surface_m2": 85 }

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source_id, source_type)
);

CREATE TABLE embedding_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- 'pending', 'processing', 'completed', 'failed'
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

-- ============================================================
-- INDEX DE PERFORMANCE
-- ============================================================

-- Users
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_actif ON users(actif);

-- Threads
CREATE INDEX idx_threads_user_id ON threads(user_id);
CREATE INDEX idx_threads_status ON threads(status);
CREATE INDEX idx_threads_langgraph ON threads(langgraph_thread_id);

-- Messages
CREATE INDEX idx_messages_thread_id ON messages(thread_id);
CREATE INDEX idx_messages_created ON messages(created_at);

-- Audit
CREATE INDEX idx_audit_user_id ON audit_log(user_id);
CREATE INDEX idx_audit_created ON audit_log(created_at);
CREATE INDEX idx_audit_action ON audit_log(action);

-- Skills
CREATE INDEX idx_skills_status ON skills(status);
CREATE INDEX idx_skills_name ON skills(name);

-- API Usage
CREATE INDEX idx_usage_user_date ON api_usage_daily(user_id, date);

-- Documents / RAG
-- IVFFlat : à créer APRÈS 1 000+ chunks (recalculer lists = sqrt(nb_chunks))
-- < 1 000 chunks  : pas d'index (recherche exacte suffisante)
-- 1 000 - 10 000  : lists = 100
-- 10 000 - 100 000: lists = 316
-- > 100 000       : lists = 1000
CREATE INDEX idx_documents_embedding_cosine
    ON documents
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX idx_documents_source_type ON documents(source_type);
CREATE INDEX idx_documents_access_level ON documents(access_level);
CREATE INDEX idx_documents_source_id ON documents(source_id);
CREATE INDEX idx_documents_contains_pii ON documents(contains_pii);

-- Recherche full-text hybride via pg_trgm (fallback si embedding absent)
CREATE INDEX idx_documents_content_trgm
    ON documents
    USING gin (content gin_trgm_ops);

CREATE INDEX idx_embedding_jobs_status ON embedding_jobs(status);
CREATE INDEX idx_embedding_jobs_document ON embedding_jobs(document_id);

CREATE INDEX idx_doc_metadata_source ON document_metadata(source_id, source_type);
CREATE INDEX idx_doc_metadata_data ON document_metadata USING gin(data);

-- ============================================================
-- ROW-LEVEL SECURITY
-- ============================================================

ALTER TABLE threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_usage_daily ENABLE ROW LEVEL SECURITY;

CREATE POLICY threads_user_isolation ON threads
    USING (user_id = current_setting('app.current_user_id')::UUID
           OR current_setting('app.current_role') IN ('admin', 'direction'));

CREATE POLICY messages_user_isolation ON messages
    USING (thread_id IN (
        SELECT id FROM threads
        WHERE user_id = current_setting('app.current_user_id')::UUID
    ) OR current_setting('app.current_role') IN ('admin', 'direction'));

-- ============================================================
-- TRIGGERS updated_at
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_threads_updated_at BEFORE UPDATE ON threads
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_skills_updated_at BEFORE UPDATE ON skills
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- PERMISSIONS PAR DÉFAUT
-- ============================================================

INSERT INTO roles_permissions (role, feature) VALUES
    -- direction
    ('direction', 'chat_agent1'),
    ('direction', 'chat_agent2'),
    ('direction', 'chat_agent3'),
    ('direction', 'view_dashboard_global'),
    ('direction', 'view_own_stats'),
    ('direction', 'validate_skills'),
    ('direction', 'manage_users'),
    ('direction', 'configure_agents'),
    ('direction', 'view_costs_global'),
    ('direction', 'view_own_costs'),
    ('direction', 'view_audit_log'),
    -- admin
    ('admin', 'chat_agent1'),
    ('admin', 'chat_agent2'),
    ('admin', 'chat_agent3'),
    ('admin', 'manage_users'),
    ('admin', 'configure_agents'),
    ('admin', 'view_audit_log'),
    ('admin', 'view_costs_global'),
    ('admin', 'validate_skills'),
    -- commercial
    ('commercial', 'chat_agent1'),
    ('commercial', 'view_own_stats'),
    ('commercial', 'view_own_costs'),
    -- bureau_etudes
    ('bureau_etudes', 'chat_agent1'),
    ('bureau_etudes', 'chat_agent2'),
    ('bureau_etudes', 'view_own_stats'),
    ('bureau_etudes', 'view_own_costs'),
    -- conducteur
    ('conducteur', 'chat_agent1'),
    ('conducteur', 'view_own_stats'),
    ('conducteur', 'view_own_costs'),
    -- administratif
    ('administratif', 'chat_agent1'),
    ('administratif', 'view_own_stats'),
    ('administratif', 'view_own_costs'),
    -- terrain
    ('terrain', 'chat_agent1');
