-- ============================================================
--  Tâches d'agent : définition (agent_tasks) ≠ exécutions (agent_task_runs)
--  Trois déclencheurs : manuel (ou délégué par le chat), planifié, webhook.
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_tasks (
    id               UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Identité d'EXÉCUTION : la tâche agit au nom de son créateur, dont les droits
    -- sont RECHARGÉS à chaque run (jamais figés à la création).
    user_id          UUID         REFERENCES users(id) ON DELETE CASCADE,
    agent            VARCHAR(20)  NOT NULL DEFAULT 'agent1',
    title            VARCHAR(255) NOT NULL,
    task_prompt      TEXT         NOT NULL,
    params           JSONB        NOT NULL DEFAULT '{}',

    trigger_kind     VARCHAR(20)  NOT NULL DEFAULT 'manual',   -- manual | schedule | webhook
    schedule_kind    VARCHAR(10)  CHECK (schedule_kind IN ('interval', 'daily', 'weekly')),
    interval_minutes INTEGER      CHECK (interval_minutes >= 5),  -- plancher anti-emballement
    time_of_day      TIME,
    days_of_week     INTEGER[],                                -- ISO : 1 = lundi … 7 = dimanche
    next_run_at      TIMESTAMPTZ,                              -- NULL = jamais réveillée

    enabled          BOOLEAN      NOT NULL DEFAULT TRUE,
    -- Clé HMAC du webhook. Stockée en clair par NÉCESSITÉ : vérifier une signature
    -- exige la clé. Elle n'est affichée qu'à la création et ne transite jamais
    -- ensuite ; la protection tient à la signature, à l'anti-rejeu et au fait que
    -- le périmètre de la tâche est figé à la création.
    webhook_secret   VARCHAR(96),

    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Index PARTIEL : c'est exactement la requête de réveil, donc le balayage ne
-- parcourt jamais les tâches désactivées ou sans échéance.
CREATE INDEX IF NOT EXISTS idx_agent_tasks_due ON agent_tasks(next_run_at)
    WHERE enabled AND next_run_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_tasks_user ON agent_tasks(user_id);


CREATE TABLE IF NOT EXISTS agent_task_runs (
    id              UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID         REFERENCES agent_tasks(id) ON DELETE CASCADE,
    user_id         UUID         REFERENCES users(id) ON DELETE CASCADE,
    status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
    -- pending | running | awaiting_approval | completed | failed | cancelled
    trigger_kind    VARCHAR(20)  NOT NULL,
    -- Anti-rejeu du webhook : une même clé ne peut créer qu'une seule exécution.
    idempotency_key VARCHAR(128) UNIQUE,
    -- 'task:<run_id>' : relie l'exécution au checkpointer LangGraph ET aux
    -- validations, ce qui permet de reprendre une tâche suspendue après un
    -- redémarrage du backend.
    thread_id       VARCHAR(255),
    result          JSONB,
    error           TEXT,                                      -- message sans PII
    started_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_task_runs_task   ON agent_task_runs(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_task_runs_status ON agent_task_runs(status);

COMMENT ON TABLE agent_tasks IS
    'Définition d''une tâche d''agent. L''identité d''exécution est user_id, dont les droits sont revalidés à chaque run.';
COMMENT ON TABLE agent_task_runs IS
    'Exécutions d''une tâche. thread_id = task:<run_id> pour reprendre une exécution suspendue.';
