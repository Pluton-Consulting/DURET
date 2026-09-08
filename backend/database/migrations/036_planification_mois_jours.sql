-- 036 — Tous les X jours, le X du mois, et la conversation d'origine (08/09).
--
-- POURQUOI. La planification ne connaissait que trois rythmes (intervalle en
-- minutes, quotidien, hebdomadaire). Noa : « tous les X jours ou tous les X du
-- mois, à telle heure ». Et une tâche exécutée rendait son compte rendu dans
-- un fil à part (`task:<run>`) : la conversation qui l'avait créée n'en
-- voyait jamais rien. `origin_thread_id` garde ce fil : chaque exécution y
-- revient comme un nouveau message.
--
-- Idempotente : rejouable sans effet.

ALTER TABLE agent_tasks DROP CONSTRAINT IF EXISTS agent_tasks_schedule_kind_check;
ALTER TABLE agent_tasks ADD CONSTRAINT agent_tasks_schedule_kind_check
    CHECK (schedule_kind IN ('interval', 'daily', 'weekly', 'every_days', 'monthly'));

ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS interval_days INTEGER CHECK (interval_days >= 1);
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS day_of_month  INTEGER CHECK (day_of_month BETWEEN 1 AND 31);
ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS origin_thread_id VARCHAR(255);

COMMENT ON COLUMN agent_tasks.interval_days IS 'every_days : tous les N jours, a time_of_day';
COMMENT ON COLUMN agent_tasks.day_of_month IS 'monthly : le N de chaque mois (31 = dernier jour des mois courts), a time_of_day';
COMMENT ON COLUMN agent_tasks.origin_thread_id IS 'fil LangGraph de la conversation qui a cree la tache : chaque execution y revient comme un message';
