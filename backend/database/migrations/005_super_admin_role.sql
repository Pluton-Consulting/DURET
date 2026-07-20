-- Migration 005 : ajout du rôle super_admin
-- super_admin = développeur, accès total à l'application

INSERT INTO roles_permissions (role, feature) VALUES
    ('super_admin', 'chat_agent1'),
    ('super_admin', 'chat_agent2'),
    ('super_admin', 'chat_agent3'),
    ('super_admin', 'view_dashboard_global'),
    ('super_admin', 'view_own_stats'),
    ('super_admin', 'validate_skills'),
    ('super_admin', 'manage_users'),
    ('super_admin', 'configure_agents'),
    ('super_admin', 'view_costs_global'),
    ('super_admin', 'view_own_costs'),
    ('super_admin', 'view_audit_log'),
    ('super_admin', 'manage_agent3'),
    ('super_admin', 'manage_system')
ON CONFLICT (role, feature) DO NOTHING;

-- Mise à jour du constraint sur users.role pour accepter super_admin
-- (si une contrainte CHECK existe — sinon cette ligne est ignorée)
DO $$
BEGIN
    ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
EXCEPTION WHEN OTHERS THEN NULL;
END $$;
