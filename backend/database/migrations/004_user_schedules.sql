-- Migration 004 : plages horaires personnalisées par utilisateur
-- Les champs NULL = utiliser le défaut global (config access_start_hour / access_end_hour)

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS schedule_start_hour INTEGER CHECK (schedule_start_hour BETWEEN 0 AND 23),
    ADD COLUMN IF NOT EXISTS schedule_end_hour   INTEGER CHECK (schedule_end_hour   BETWEEN 1 AND 24);

COMMENT ON COLUMN users.schedule_start_hour IS 'Heure de début de plage (0-23). NULL = défaut global (8).';
COMMENT ON COLUMN users.schedule_end_hour   IS 'Heure de fin de plage (1-24). NULL = défaut global (18).';
COMMENT ON COLUMN users.bypass_schedule     IS 'Si true : aucune restriction horaire. Attribuable par admin/direction.';
