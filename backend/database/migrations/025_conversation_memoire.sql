-- ============================================================
--  025 — Memoire longue d'une conversation : les echanges vectorises
-- ============================================================
--
-- Troisieme etage de la memoire de conversation (agents/memoire_conversation.py).
-- Chaque echange clos d'un fil — la question et la reponse, en texte MASQUE,
-- comme tout ce que porte le fil — est vectorise ici. A chaque tour, les
-- echanges anciens les plus proches de la question du moment sont rappeles
-- au modele : c'est ce qui repond a « tu te souviens du devis dont on a parle
-- tout a l'heure ? » trente echanges plus loin.
--
-- Pas d'index vectoriel : la recherche est toujours bornee a UN fil (quelques
-- dizaines de lignes), le filtre par thread_id suffit, et un index ivfflat
-- sur une table aussi fragmentee n'apporterait rien.

CREATE TABLE IF NOT EXISTS conversation_memoire (
    id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id   TEXT        NOT NULL,
    user_id     UUID        REFERENCES users(id) ON DELETE SET NULL,
    rang        INTEGER     NOT NULL,          -- numero de l'echange dans le fil (1 = premier)
    question    TEXT        NOT NULL,          -- texte masque
    reponse     TEXT        NOT NULL DEFAULT '',
    embedding   vector(1536),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (thread_id, rang)
);

CREATE INDEX IF NOT EXISTS idx_conversation_memoire_fil ON conversation_memoire(thread_id, rang);

COMMENT ON TABLE conversation_memoire IS
    'Memoire longue des conversations : un echange (question + reponse, masques) par ligne, vectorise pour le rappel.';
