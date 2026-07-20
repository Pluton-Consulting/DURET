-- Migration 011 : configuration modifiable depuis les Paramètres
--   (a) plage horaire globale (table global_config)
--   (b) reset de la matrice de permissions RBAC aux défauts autoritatifs
--       (la base devient la source de vérité, éditable ; has_permission lit la base)

-- (a) Plage horaire globale — ligne unique id=1
CREATE TABLE IF NOT EXISTS global_config (
    id                  INTEGER      PRIMARY KEY DEFAULT 1,
    schedule_start_hour INTEGER      NOT NULL DEFAULT 8  CHECK (schedule_start_hour BETWEEN 0 AND 23),
    schedule_end_hour   INTEGER      NOT NULL DEFAULT 18 CHECK (schedule_end_hour   BETWEEN 1 AND 24),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_by          UUID         REFERENCES users(id),
    CONSTRAINT global_config_single_row CHECK (id = 1)
);
INSERT INTO global_config (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- (b) Matrice de permissions — remise à plat sur les défauts du code (rbac.ROLE_PERMISSIONS)
DELETE FROM roles_permissions;
INSERT INTO roles_permissions (role, feature) VALUES
    -- super_admin (accès total)
    ('super_admin','chat_agent1'),('super_admin','chat_agent2'),('super_admin','chat_agent3'),
    ('super_admin','view_dashboard_global'),('super_admin','view_own_stats'),
    ('super_admin','validate_skills'),('super_admin','manage_users'),('super_admin','configure_agents'),
    ('super_admin','view_costs_global'),('super_admin','view_own_costs'),('super_admin','view_audit_log'),
    ('super_admin','manage_agent3'),('super_admin','manage_system'),
    -- direction (gestion complète, hors admin système)
    ('direction','chat_agent1'),('direction','chat_agent2'),('direction','chat_agent3'),
    ('direction','view_dashboard_global'),('direction','view_own_stats'),
    ('direction','validate_skills'),('direction','manage_users'),('direction','configure_agents'),
    ('direction','view_costs_global'),('direction','view_own_costs'),('direction','view_audit_log'),
    ('direction','manage_agent3'),
    -- commercial
    ('commercial','chat_agent1'),('commercial','view_own_stats'),('commercial','view_own_costs'),
    -- bureau_etudes
    ('bureau_etudes','chat_agent1'),('bureau_etudes','chat_agent2'),
    ('bureau_etudes','view_own_stats'),('bureau_etudes','view_own_costs'),
    -- conducteur
    ('conducteur','chat_agent1'),('conducteur','view_own_stats'),('conducteur','view_own_costs'),
    -- administratif
    ('administratif','chat_agent1'),('administratif','view_own_stats'),('administratif','view_own_costs'),
    -- terrain
    ('terrain','chat_agent1')
ON CONFLICT (role, feature) DO NOTHING;
