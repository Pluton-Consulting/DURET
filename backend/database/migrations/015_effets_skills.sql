-- ============================================================
--  Classement des skills par EFFET + liaison d'une validation au payload approuvé
-- ============================================================

-- Effet d'un skill GÉNÉRÉ (les natifs déclarent le leur en code, dans
-- mail/skills.py::EFFETS_NATIFS). Défaut volontairement 'externe' : un skill
-- dont l'effet n'a pas été qualifié est verrouillé, il n'est pas ouvert.
ALTER TABLE skills ADD COLUMN IF NOT EXISTS effect VARCHAR(20) NOT NULL DEFAULT 'externe';

DO $$
BEGIN
    ALTER TABLE skills ADD CONSTRAINT skills_effect_valide
        CHECK (effect IN ('lecture', 'ecriture_interne', 'externe'));
EXCEPTION
    WHEN duplicate_object THEN NULL;   -- migration rejouée
END $$;

-- Empreinte du payload EXACT présenté à l'humain. C'est elle qui empêche
-- qu'une approbation donnée pour « envoyer à Dupont » serve à envoyer ailleurs :
-- l'exécution recalcule le hash et le compare à celui qui a été validé.
ALTER TABLE validations ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(64);

COMMENT ON COLUMN skills.effect IS
    'lecture | ecriture_interne | externe. « externe » exige une validation humaine liée au payload.';
COMMENT ON COLUMN validations.payload_hash IS
    'sha256(skill + arguments canoniques) — lie l''approbation au contenu exact validé.';
