-- Migration 012 : tâches de l'agent de navigation agentique (browser-use).
-- Chaque lancement crée une ligne suivie par le backend et le frontend.
-- Le HITL (approbation des actions modifiantes) réutilise la table `validations`
-- existante avec agent='browser' — pas de table d'approbation dédiée.

CREATE TABLE IF NOT EXISTS browser_tasks (
    id                UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id           UUID        REFERENCES users(id) ON DELETE CASCADE,
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- 'pending', 'running', 'awaiting_approval', 'completed', 'failed', 'cancelled'
    task_prompt       TEXT        NOT NULL,
    allowed_domains   TEXT[]      NOT NULL DEFAULT '{}',
    result            JSONB,               -- résumé final (texte) + sources
    structured_output JSONB,               -- extraction structurée (si output_model_schema)
    error             TEXT,                -- message d'erreur (sans PII)
    steps             INTEGER     NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_browser_tasks_user   ON browser_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_browser_tasks_status ON browser_tasks(status);
CREATE INDEX IF NOT EXISTS idx_browser_tasks_created ON browser_tasks(created_at DESC);
