-- ============================================================
--  Gestion des mails : délégations de boîtes + profils de style
-- ============================================================

-- Boîtes qu'un utilisateur peut consulter EN PLUS de la sienne.
-- Sa propre adresse (users.email) est TOUJOURS autorisée et n'est jamais
-- stockée ici : c'est une règle du code, pas une donnée modifiable.
CREATE TABLE IF NOT EXISTS user_mailboxes (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    mailbox     VARCHAR(255) NOT NULL,          -- normalisée en minuscules
    can_send    BOOLEAN NOT NULL DEFAULT true,  -- false = lecture seule sur cette boîte
    granted_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, mailbox)
);

CREATE INDEX IF NOT EXISTS idx_user_mailboxes_user ON user_mailboxes(user_id);
CREATE INDEX IF NOT EXISTS idx_user_mailboxes_box  ON user_mailboxes(mailbox);

-- Profil de style rédactionnel, appris progressivement à partir des messages
-- ENVOYÉS par chaque boîte. Permet à l'assistant d'écrire « à la manière de »
-- la personne, sans réentraîner quoi que ce soit : le profil est réinjecté
-- dans le prompt au moment de la rédaction.
CREATE TABLE IF NOT EXISTS mail_style_profiles (
    mailbox        VARCHAR(255) PRIMARY KEY,    -- minuscules
    profil         TEXT NOT NULL,               -- description du style, en français
    echantillons   INTEGER NOT NULL DEFAULT 0,  -- nb de messages analysés
    derniere_maj   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE user_mailboxes IS
    'Délégations de boîtes mail. La boîte nominative de l''utilisateur est implicite.';
COMMENT ON TABLE mail_style_profiles IS
    'Style rédactionnel par boîte, distillé depuis les messages envoyés.';
