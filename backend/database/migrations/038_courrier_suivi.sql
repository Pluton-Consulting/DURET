-- 038 — Le repère du courrier entrant (08/09).
--
-- POURQUOI. Une tâche planifiée « toutes les 10 minutes : lis les nouveaux
-- mails » tourne sur un fil neuf à chaque réveil : sans repère, elle relisait
-- les mêmes messages. Une ligne par personne et par boîte garde la date du
-- dernier message vu et ses dernières références ; `courrier_entrant` ne rend
-- que ce qui est arrivé depuis, et avance le repère. Idempotente.

CREATE TABLE IF NOT EXISTS courrier_suivi (
    user_id        UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    boite          VARCHAR(255) NOT NULL,          -- adresse, ou « @moi » pour la boîte par défaut
    dernier_vu     TIMESTAMPTZ,
    dernieres_refs JSONB        NOT NULL DEFAULT '[]',
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, boite)
);

COMMENT ON TABLE courrier_suivi IS
    'Repere du courrier entrant : dernier message vu par personne et par boite';
