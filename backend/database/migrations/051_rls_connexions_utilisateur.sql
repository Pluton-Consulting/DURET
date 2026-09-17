-- Le pool conserve son identité existante pour les tâches système.
-- Les transactions utilisateur prennent un rôle sans BYPASSRLS, sans changer
-- le mot de passe ni l'URL. Aucun utilisateur ni historique n'est modifié.
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='infra_ia_lecteur_rls') THEN
   CREATE ROLE infra_ia_lecteur_rls NOLOGIN NOSUPERUSER NOBYPASSRLS;
 END IF;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='infra_ia_lecteur_rls' AND (rolsuper OR rolbypassrls OR rolcanlogin)) THEN
   RAISE EXCEPTION 'Le rôle infra_ia_lecteur_rls existe avec des privilèges incompatibles';
 END IF;
 EXECUTE format('GRANT infra_ia_lecteur_rls TO %I', current_user);
END $$;
GRANT USAGE ON SCHEMA public TO infra_ia_lecteur_rls;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO infra_ia_lecteur_rls;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO infra_ia_lecteur_rls;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO infra_ia_lecteur_rls;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO infra_ia_lecteur_rls;
