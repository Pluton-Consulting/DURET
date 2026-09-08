-- 037 — Les factures sous suivi de relances (08/09).
--
-- POURQUOI UNE TABLE. Une chaîne de relances (public : maître d'œuvre, puis
-- architecte, puis l'architecte encore ; privé : le client, ton qui monte) a
-- besoin de SAVOIR où elle en est : l'étape franchie, la date de la dernière
-- relance, les contacts du dossier. Confié à la mémoire de conversation, cet
-- état se perd d'un fil à l'autre et une tâche planifiée ne le voit jamais.
-- Une facture ne se supprime pas d'ici : elle se marque réglée ou close.
--
-- Idempotente : rejouable sans effet.

CREATE TABLE IF NOT EXISTS factures_suivies (
    id               UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reference        VARCHAR(120) NOT NULL,
    client           VARCHAR(200) NOT NULL,
    chantier         VARCHAR(200),
    montant          NUMERIC(14, 2),
    echeance         DATE         NOT NULL,
    -- public | prive : la chaîne des destinataires (facturation/relances.py)
    regime           VARCHAR(10)  NOT NULL DEFAULT 'prive' CHECK (regime IN ('public', 'prive')),
    -- {"client": adresse, "maitre_oeuvre": adresse, "architecte": adresse}
    contacts         JSONB        NOT NULL DEFAULT '{}',
    -- relances déjà PARTIES (0 = aucune) ; la prochaine est etape + 1
    etape            INTEGER      NOT NULL DEFAULT 0,
    derniere_relance TIMESTAMPTZ,
    -- en_cours | reglee | close
    statut           VARCHAR(12)  NOT NULL DEFAULT 'en_cours',
    notes            TEXT,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, reference)
);

CREATE INDEX IF NOT EXISTS idx_factures_suivies_dues
    ON factures_suivies(user_id, echeance) WHERE statut = 'en_cours';

COMMENT ON TABLE factures_suivies IS
    'Factures sous suivi de relances : etape franchie, derniere relance, contacts par role';
