-- 043 — Les leçons tirées des corrections (15/09).
--
-- POURQUOI. Demande de Noa : « c'est mieux d'entraîner l'IA » plutôt que
-- d'ajouter une règle par défaut rencontré. Quand une personne corrige
-- l'assistant (« c'est pas ma signature ça », « tu as enlevé trop de choses »),
-- le modèle en tire une LEÇON — la situation, l'erreur, la bonne conduite — qui
-- est rappelée ensuite sur les demandes proches (learning/lecons.py).
--
-- Une leçon appartient à la personne qui a corrigé ; un administrateur peut la
-- rendre valable pour toute l'entreprise, ou la retirer (jamais effacée : `actif`).
-- Même numéro des deux côtés (Duret porte déjà 040-042). Idempotente.

CREATE TABLE IF NOT EXISTS lecons (
    id            UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       UUID         REFERENCES users(id) ON DELETE CASCADE,
    portee        VARCHAR(20)  NOT NULL DEFAULT 'personne',
    situation     TEXT         NOT NULL,
    erreur        TEXT         NOT NULL DEFAULT '',
    conduite      TEXT         NOT NULL,
    gestes        JSONB        NOT NULL DEFAULT '[]',
    source_fil    VARCHAR(200),
    occurrences   INTEGER      NOT NULL DEFAULT 1,
    rappels       INTEGER      NOT NULL DEFAULT 0,
    actif         BOOLEAN      NOT NULL DEFAULT true,
    cree_le       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    derniere_maj  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT lecons_portee_valide CHECK (portee IN ('personne', 'entreprise'))
);

CREATE INDEX IF NOT EXISTS idx_lecons_user ON lecons (user_id) WHERE actif;
CREATE INDEX IF NOT EXISTS idx_lecons_texte ON lecons
    USING GIN (to_tsvector('french', situation || ' ' || erreur || ' ' || conduite));

COMMENT ON TABLE lecons IS
    'Lecons tirees des corrections faites a l assistant, rappelees sur les demandes proches';
