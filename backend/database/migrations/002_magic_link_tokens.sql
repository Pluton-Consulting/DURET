-- Table des tokens de connexion Magic Link
-- Chaque token est à usage unique et expire après 15 minutes

CREATE TABLE verification_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_verification_tokens_token ON verification_tokens(token);
CREATE INDEX idx_verification_tokens_email ON verification_tokens(email);

-- Nettoyage automatique des tokens expirés (optionnel — à lancer via cron)
-- DELETE FROM verification_tokens WHERE expires_at < NOW() - INTERVAL '1 day';
