-- 035 — UN LIEN D'ACCÈS QUI SERT PLUSIEURS FOIS : PC + téléphone.
--
-- LA DEMANDE (03/09, Noa) : « quand je crée un lien magique pour un
-- utilisateur, je dois pouvoir choisir le nombre d'utilisations du lien — si
-- j'ai besoin qu'il s'en serve sur PC + téléphone, par exemple. »
--
-- CE QUI SE PASSAIT. Un lien de connexion était à usage UNIQUE par construction
-- (`used`, un booléen). Or, depuis la session d'appareil (034), chaque appareil
-- doit franchir la porte UNE fois — donc un salarié qu'on équipe d'un poste et
-- d'un téléphone avait besoin de deux liens, fabriqués et transmis
-- séparément.
--
-- CE QUE CETTE MIGRATION AJOUTE : un COMPTEUR à la place du booléen — combien
-- de fois le lien peut servir, combien de fois il a servi. `used` reste : c'est
-- lui que lit le lien envoyé par mail (toujours à usage unique), et il passe à
-- vrai quand le compteur est plein. Les deux colonnes ont un défaut qui
-- reproduit l'ancien comportement : un lien existant vaut UNE utilisation.
--
-- Idempotente : rejouable sans dommage.

ALTER TABLE verification_tokens
    ADD COLUMN IF NOT EXISTS utilisations_max INTEGER NOT NULL DEFAULT 1;
ALTER TABLE verification_tokens
    ADD COLUMN IF NOT EXISTS utilisations INTEGER NOT NULL DEFAULT 0;
