-- 016 — Apprentissage déclenché à la main (débrief de conversation).
--
-- Le débrief écrit dans `skills` (brouillon désactivé) et dans `documents`
-- (mémoire vectorielle). Trois colonnes de `skills` n'étaient créées que par
-- `scripts/seed_skills_catalogue.py`, exécuté à la main : une instance qui ne
-- l'avait jamais lancé n'a pas ces colonnes, et le routeur skills échoue.
-- On les crée ici, de façon idempotente, pour que le schéma soit complet quel
-- que soit l'historique de l'instance.

ALTER TABLE skills ADD COLUMN IF NOT EXISTS agent VARCHAR(20);
ALTER TABLE skills ADD COLUMN IF NOT EXISTS category VARCHAR(50);
ALTER TABLE skills ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT true;

-- `created_by` distingue déjà 'agent3' d'un skill issu d'un débrief
-- ('apprentissage') : pas de colonne supplémentaire, juste un index pour
-- retrouver rapidement les brouillons en attente de relecture.
CREATE INDEX IF NOT EXISTS idx_skills_status_created_by ON skills (status, created_by);

-- La mémoire acquise par débrief se range dans `documents` avec deux nouveaux
-- types de source : 'apprentissage' (un fait) et 'procedure' (une manière de
-- faire). Aucune contrainte à modifier (source_type est libre), mais l'index
-- par type accélère les recherches filtrées.
CREATE INDEX IF NOT EXISTS idx_documents_source_type ON documents (source_type);
