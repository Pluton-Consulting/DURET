-- Migration 006 : fusion du rôle admin dans direction
-- admin et direction sont le même rôle (dirigeants + gestion app)
-- Le rôle admin est supprimé, tous les admin deviennent direction.

-- 1. Migrer les utilisateurs
UPDATE users SET role = 'direction' WHERE role = 'admin';

-- 2. Supprimer les permissions du rôle admin
DELETE FROM roles_permissions WHERE role = 'admin';

-- 3. Mettre à jour les politiques RLS (remplacer 'admin' par 'super_admin')
DROP POLICY IF EXISTS threads_user_isolation ON threads;
CREATE POLICY threads_user_isolation ON threads
    USING (
        user_id = current_setting('app.current_user_id', true)::UUID
        OR current_setting('app.current_role', true) IN ('super_admin', 'direction')
    );

DROP POLICY IF EXISTS messages_user_isolation ON messages;
CREATE POLICY messages_user_isolation ON messages
    USING (
        thread_id IN (
            SELECT id FROM threads
            WHERE user_id = current_setting('app.current_user_id', true)::UUID
        ) OR current_setting('app.current_role', true) IN ('super_admin', 'direction')
    );
