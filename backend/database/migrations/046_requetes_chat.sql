-- 046 — UNE DEMANDE, UN SEUL TOUR (16/09, audit D-13, Duret).
--
-- L'écran envoie sa demande par WebSocket ; si la socket se ferme (réseau,
-- veille, changement de page), il la rejoue en HTTP. Le tour d'origine, lui,
-- continuait : deux tours pour une demande, deux appels de modèle payés, deux
-- fois les mêmes gestes — et, sur un effet externe, deux cartes d'accord.
--
-- L'écran fabrique un `request_id` AVANT d'envoyer et le garde pour toutes ses
-- reprises. L'unicité (utilisateur, request_id) fait le reste : la seconde
-- arrivée ne démarre rien, elle rejoint le tour en cours.
--
-- Rien n'est bloqué si la migration manque : le serveur retombe alors sur le
-- comportement d'avant (`agents/requetes.py` est best-effort). Idempotente.

CREATE TABLE IF NOT EXISTS requetes_chat (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- L'identifiant fabriqué par l'écran : il traverse WS, secours HTTP et file.
    request_id VARCHAR(120) NOT NULL,
    thread_id  VARCHAR(255),
    etat       VARCHAR(20) NOT NULL DEFAULT 'en_cours',   -- en_cours | terminee | echouee
    resultat   TEXT,
    cree_le    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    maj_le     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_requetes_chat_unicite
    ON requetes_chat (user_id, request_id);
CREATE INDEX IF NOT EXISTS idx_requetes_chat_age ON requetes_chat (cree_le);

COMMENT ON TABLE requetes_chat IS
  'Une ligne par demande de l''écran (request_id). Empêche qu''une reprise réseau '
  'lance un second tour pour la même intention. Purge au-delà de quelques jours.';
