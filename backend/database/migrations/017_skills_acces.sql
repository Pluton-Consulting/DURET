-- 017 — Portée d'un skill : pour tout le monde, ou pour certains profils.
--
-- Les DOCUMENTS portent déjà un `access_level` (all, commercial_plus,
-- bureau_etudes_plus, direction_only, admin_only) et le RAG filtre dessus selon
-- le rôle. Les SKILLS n'avaient pas d'équivalent : tout skill validé était
-- annoncé à tout le monde.
--
-- Or un skill n'est pas neutre. « suivi_dossier_juridique » ou
-- « analyse_marge_chantier » n'ont rien à faire dans la liste des capacités
-- présentée à un profil terrain : les annoncer, c'est déjà renseigner sur ce
-- que l'entreprise suit, et inviter à les appeler.
--
-- Même vocabulaire que les documents, à dessein : une seule échelle à
-- comprendre, et le mapping rôle → niveaux est partagé (vectorstore.client).

ALTER TABLE skills ADD COLUMN IF NOT EXISTS access_level VARCHAR(50) NOT NULL DEFAULT 'all';

DO $$
BEGIN
    ALTER TABLE skills ADD CONSTRAINT skills_access_level_valide
        CHECK (access_level IN ('all', 'commercial_plus', 'bureau_etudes_plus',
                                'direction_only', 'admin_only'));
EXCEPTION
    WHEN duplicate_object THEN NULL;   -- migration rejouée
END $$;

-- Le catalogue est relu à chaque tour de conversation : l'index évite un
-- balayage complet à chaque rafraîchissement.
CREATE INDEX IF NOT EXISTS idx_skills_expose
    ON skills (status, enabled, access_level);
