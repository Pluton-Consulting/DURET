-- Archivage automatique avant toute modification : aucune version existante perdue.
CREATE TABLE IF NOT EXISTS skill_versions (
 id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL,
 code TEXT, description TEXT, prompt_template TEXT, status TEXT,
 cree_le TIMESTAMPTZ NOT NULL DEFAULT NOW(), UNIQUE(name,version)
);
CREATE TABLE IF NOT EXISTS skill_evaluations (
 id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, code_sha256 TEXT NOT NULL,
 passed BOOLEAN NOT NULL, sandbox TEXT NOT NULL, cas JSONB NOT NULL,
 resultats JSONB NOT NULL, cree_le TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_skill_evaluations_code ON skill_evaluations(name,code_sha256,cree_le DESC);
CREATE OR REPLACE FUNCTION archiver_skill_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.code IS DISTINCT FROM NEW.code OR OLD.prompt_template IS DISTINCT FROM NEW.prompt_template OR OLD.description IS DISTINCT FROM NEW.description THEN
   INSERT INTO skill_versions(name,version,code,description,prompt_template,status)
   VALUES(OLD.name,OLD.version,OLD.code,OLD.description,OLD.prompt_template,OLD.status)
   ON CONFLICT(name,version) DO NOTHING;
   NEW.version := GREATEST(NEW.version,OLD.version+1);
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS skills_archive_version ON skills;
CREATE TRIGGER skills_archive_version BEFORE UPDATE ON skills FOR EACH ROW EXECUTE FUNCTION archiver_skill_version();
