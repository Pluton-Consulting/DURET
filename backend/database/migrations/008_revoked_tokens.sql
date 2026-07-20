-- Migration 008 : blacklist JWT pour logout propre
-- Chaque token révoqué (logout) est stocké jusqu'à son expiration naturelle.

CREATE TABLE IF NOT EXISTS revoked_tokens (
    jti        UUID        PRIMARY KEY,           -- JWT ID (claim "jti")
    user_id    UUID        REFERENCES users(id) ON DELETE CASCADE,
    revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL               -- = exp du JWT, pour nettoyage
);

CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires ON revoked_tokens(expires_at);

-- Fonction de nettoyage des tokens expirés (appeler manuellement ou en cron)
CREATE OR REPLACE FUNCTION cleanup_revoked_tokens() RETURNS INTEGER AS $$
DECLARE
    cnt INTEGER;
BEGIN
    DELETE FROM revoked_tokens WHERE expires_at < NOW();
    GET DIAGNOSTICS cnt = ROW_COUNT;
    RETURN cnt;
END;
$$ LANGUAGE plpgsql;
