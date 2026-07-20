-- Migration 009 : file d'attente human-in-the-loop
-- Chaque suspension du graph (validation_check → interrupt) crée une ligne pending.
-- La reprise (POST /api/validations/{id}/resolve) passe le statut à approved/rejected.

CREATE TABLE IF NOT EXISTS validations (
    id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id    VARCHAR(255) NOT NULL,
    user_id      UUID        REFERENCES users(id) ON DELETE CASCADE,
    agent        VARCHAR(20),                 -- agent1 / agent2 / agent3
    reason       VARCHAR(255),                -- 'chiffrage', 'email', 'nouveau skill'...
    payload      JSONB       NOT NULL DEFAULT '{}',
    draft        TEXT,                        -- brouillon présenté à l'humain
    status       VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / approved / rejected
    validated_by UUID        REFERENCES users(id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_validations_status ON validations(status);
CREATE INDEX IF NOT EXISTS idx_validations_thread ON validations(thread_id);
CREATE INDEX IF NOT EXISTS idx_validations_user   ON validations(user_id);
