-- Permissions agent par utilisateur (override du rôle par défaut)
-- direction > admin > membres
-- Agent 3 : visible direction + admin, contrôle direction uniquement

CREATE TABLE IF NOT EXISTS user_agent_permissions (
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent       VARCHAR(10) NOT NULL CHECK (agent IN ('agent1', 'agent2', 'agent3')),
    has_access  BOOLEAN     NOT NULL DEFAULT true,
    granted_by  UUID        REFERENCES users(id),
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, agent)
);

CREATE INDEX IF NOT EXISTS idx_user_agent_perms_user ON user_agent_permissions(user_id);
