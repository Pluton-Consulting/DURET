-- Créé au premier démarrage PostgreSQL sur le VPS.
-- Sur un container déjà existant, exécuter manuellement :
--   docker compose exec postgres psql -U $POSTGRES_USER -c "CREATE DATABASE langfuse;"

SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'langfuse'
)\gexec
