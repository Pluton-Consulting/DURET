-- Migration 010 : FORCE ROW LEVEL SECURITY
--
-- ENABLE ROW LEVEL SECURITY (migrations 001/006/007) ne suffit pas : le
-- PROPRIÉTAIRE des tables (noa_user, qui exécute aussi l'application) CONTOURNE
-- la RLS par défaut. Résultat : les policies étaient décoratives.
--
-- FORCE ROW LEVEL SECURITY applique les policies même au propriétaire, rendant
-- l'isolation réellement effective. L'application DOIT alors toujours passer par
-- get_rls_db() (app.current_user_id / app.current_role) pour ces tables — ce qui
-- est le cas dans chat.py et dashboard.py. Les rôles super_admin/direction
-- conservent une visibilité globale via les policies existantes.

ALTER TABLE threads          FORCE ROW LEVEL SECURITY;
ALTER TABLE messages         FORCE ROW LEVEL SECURITY;
ALTER TABLE api_usage_daily  FORCE ROW LEVEL SECURITY;
