-- Colonnes d'origine ET vocabulaire commun, côte à côte.
--
-- `data` garde les entêtes du fichier tel qu'il a été exporté. `champs` porte la
-- même ligne ramenée au vocabulaire du type (nom, reference, montant_ht…), ce
-- qui permet d'interroger deux exports de logiciels différents avec les mêmes
-- mots.
--
-- Les deux sont conservés VOLONTAIREMENT. Sans `data`, une association ratée
-- perdrait la donnée ; sans `champs`, il faudrait connaître les entêtes de
-- chaque fichier pour filtrer. Une association se refait sans réimporter.

ALTER TABLE document_metadata
    ADD COLUMN IF NOT EXISTS champs JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_document_metadata_champs
    ON document_metadata USING GIN (champs);
