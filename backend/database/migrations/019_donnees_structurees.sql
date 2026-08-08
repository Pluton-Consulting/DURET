-- Rendre `document_metadata` réellement utilisable.
--
-- La table existait depuis 001 mais n'a JAMAIS été écrite : à l'import d'un
-- fichier tabulaire, chaque ligne était aplatie en texte, vectorisée, et sa
-- structure perdue. Conséquence : impossible de répondre exactement à
-- « combien de chantiers à Arcachon » ou « le total des devis signés en 2025 ».
-- La recherche sémantique approxime ; sur des chiffres, approximer c'est faux.
--
-- On conserve donc les colonnes d'origine à côté du texte vectorisé. Le texte
-- sert à RETROUVER, la donnée structurée sert à COMPTER et FILTRER.

-- Cloisonnement. Sans ce niveau ici, une requête structurée contournerait le
-- filtrage par rôle appliqué aux documents : on répondrait « 14 devis » à
-- quelqu'un qui n'a le droit d'en voir aucun.
ALTER TABLE document_metadata
    ADD COLUMN IF NOT EXISTS access_level VARCHAR(50) NOT NULL DEFAULT 'all';

-- Traçabilité : de quel fichier et de quelle ligne vient cet enregistrement.
ALTER TABLE document_metadata
    ADD COLUMN IF NOT EXISTS source_filename VARCHAR(500);
ALTER TABLE document_metadata
    ADD COLUMN IF NOT EXISTS ligne INTEGER;

-- Un import rejoué doit CORRIGER, pas empiler. La contrainte UNIQUE
-- (source_id, source_type) existe déjà : elle porte l'idempotence, à condition
-- que l'import fournisse une colonne identifiant stable.
ALTER TABLE document_metadata
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Recherche par valeur de colonne : `data @> '{"ville":"Arcachon"}'`.
CREATE INDEX IF NOT EXISTS idx_document_metadata_data
    ON document_metadata USING GIN (data);

CREATE INDEX IF NOT EXISTS idx_document_metadata_type
    ON document_metadata (source_type, access_level);
