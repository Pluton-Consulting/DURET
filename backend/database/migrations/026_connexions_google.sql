-- 026 — Connexions Google PERSONNELLES.
--
-- Chaque utilisateur relie SA boîte Google depuis Paramètres > Ma boîte
-- Google : un consentement OAuth individuel, une fois. Le refresh token rendu
-- par Google ne périme pas de lui-même : la connexion tient des mois — on se
-- connecte à l'application par lien magique, et la boîte, elle, reste reliée.
--
-- Le jeton est stocké tel quel, comme les clés de `cles_api` (018) : la base
-- ne sert que l'application, derrière le VPN, et RLS n'est pas nécessaire ici
-- car seul le backend lit cette table (aucun endpoint ne rend le jeton).
--
-- `email` est l'adresse CONFIRMÉE par Google au consentement (userinfo), pas
-- celle du compte applicatif : quelqu'un peut se connecter à l'application
-- avec une adresse et relier une boîte Google différente.

CREATE TABLE IF NOT EXISTS connexions_google (
    user_id       UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    email         TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    scopes        TEXT NOT NULL DEFAULT '',
    connecte_le   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    maj_le        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Le connecteur Gmail cherche par ADRESSE (la boîte demandée), pas par
-- utilisateur : l'index suit la forme normalisée de la recherche.
CREATE INDEX IF NOT EXISTS idx_connexions_google_email
    ON connexions_google (LOWER(email));
