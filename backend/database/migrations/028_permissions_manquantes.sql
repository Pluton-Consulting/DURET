-- 028 — LES PERMISSIONS APPARUES APRÈS LA MIGRATION 011 N'ONT JAMAIS ÉTÉ SEMÉES.
--
-- Trouvé par l'audit de pré-déploiement du 01/09. La 011 fait un
-- `DELETE FROM roles_permissions` puis réinsère une liste FIGÉE ; et
-- `seed_permissions_if_empty` ne rejoue rien sur une table non vide. Trois
-- permissions ajoutées au code depuis sont donc absentes de la base — et c'est
-- la BASE qui fait foi (`reload_permissions`). En production, la direction se
-- retrouve sans `manage_mailboxes` (elle ne peut pas déléguer une boîte,
-- routers/mail.py rend 403), sans `import_documents` ni `run_browser_agent`.
--
-- Le super_admin, lui, n'a jamais été affecté : `has_permission` lui rend True
-- en dur. Migration idempotente : elle peut être rejouée sans risque.
INSERT INTO roles_permissions (role, feature, allowed) VALUES
    ('super_admin', 'manage_mailboxes', true),
    ('super_admin', 'import_documents', true),
    ('super_admin', 'run_browser_agent', true),
    ('direction',   'manage_mailboxes', true),
    ('direction',   'import_documents', true),
    ('direction',   'run_browser_agent', true)
ON CONFLICT (role, feature) DO UPDATE SET allowed = EXCLUDED.allowed;
