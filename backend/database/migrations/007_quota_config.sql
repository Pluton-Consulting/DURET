-- Migration 007 : quotas par rôle, RLS api_usage_daily, immutabilité audit_log

-- 1. Table de configuration des quotas par rôle
CREATE TABLE IF NOT EXISTS role_quota_config (
    role          VARCHAR(50)  PRIMARY KEY,
    monthly_limit INTEGER,     -- NULL = illimité
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_by    UUID         REFERENCES users(id)
);

-- Valeurs de test par défaut
INSERT INTO role_quota_config (role, monthly_limit) VALUES
    ('super_admin',   NULL),
    ('direction',     NULL),
    ('commercial',    200),
    ('bureau_etudes', 150),
    ('conducteur',    100),
    ('administratif', 100),
    ('terrain',       50)
ON CONFLICT (role) DO NOTHING;

-- 2. Politique RLS sur api_usage_daily
-- (RLS déjà activé en migration 001 — ALTER TABLE api_usage_daily ENABLE ROW LEVEL SECURITY)
DROP POLICY IF EXISTS api_usage_user_isolation ON api_usage_daily;
CREATE POLICY api_usage_user_isolation ON api_usage_daily
    USING (
        user_id = current_setting('app.current_user_id', true)::UUID
        OR current_setting('app.current_role', true) IN ('super_admin', 'direction')
    );

-- 3. Trigger d'immutabilité sur audit_log
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is immutable — UPDATE and DELETE are forbidden';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log;
CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();
