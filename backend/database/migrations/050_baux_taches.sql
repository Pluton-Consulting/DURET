-- Additive : les exécutions historiques restent intactes.
ALTER TABLE agent_task_runs ADD COLUMN IF NOT EXISTS lease_owner UUID;
ALTER TABLE agent_task_runs ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_agent_task_runs_lease ON agent_task_runs(lease_until) WHERE status='running';
