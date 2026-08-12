-- File d'attente du chat : les taches lancees pendant qu'une autre tourne.
--
-- POURQUOI UNE TABLE. Une tache differee survit a tout : l'utilisateur ferme
-- l'onglet, revient le lendemain, le backend redemarre entre-temps. Son etat,
-- sa reponse finale et son eventuelle validation en attente doivent se relire
-- depuis le disque, jamais depuis la memoire d'un processus.
--
-- Chaque tache tourne sur SON PROPRE fil LangGraph (thread_id = file:<id>) :
-- deux executions simultanees sur un meme fil se disputeraient le checkpointer
-- et corrompraient l'historique. C'est ce qui permet d'en mener plusieurs de
-- front sans aucun verrou.

CREATE TABLE IF NOT EXISTS taches_differees (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- La demande telle que tapee. Meme regime que `conversations` : donnee
    -- interne, jamais envoyee a un modele sans passer par l'anonymisation.
    query TEXT NOT NULL,
    -- en_cours | terminee | echec | interrompue | attente_validation
    status VARCHAR(24) NOT NULL DEFAULT 'en_cours',
    -- Derniere activite affichable (« je produis le document »). Persistee par
    -- moments seulement : la valeur vivante est en memoire du processus.
    progress TEXT,
    response TEXT,
    error TEXT,
    validation_id UUID,
    thread_id VARCHAR(64),
    -- La carte a ete fermee a l'ecran : on ne la remontre plus, mais la ligne
    -- reste (audit, et « qu'avait repondu la tache de mardi ? »).
    vue BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_taches_differees_user
    ON taches_differees(user_id, created_at DESC);

COMMENT ON TABLE taches_differees IS
    'Taches de chat lancees en file d''attente, une par fil LangGraph (file:<id>)';
COMMENT ON COLUMN taches_differees.status IS
    'en_cours | terminee | echec | interrompue | attente_validation';
