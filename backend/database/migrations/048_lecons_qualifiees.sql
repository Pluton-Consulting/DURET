-- 048 — CE QU'ON A APPRIS, ET CE QUE ÇA VAUT (16/09, audit D-14, Duret).
--
-- Une leçon était un texte (situation, erreur, conduite) avec une portée. Rien
-- ne disait sa NATURE — préférence de formulation, fait sur l'entreprise, ou
-- procédure à suivre —, ni ce qu'elle vaut : tirée d'une correction explicite
-- ou devinée d'une panne d'outil passagère. Tout était injecté pareil.
--
--   · `type_lecon` : preference | fait | procedure — on ne traite pas une
--     tournure de politesse comme une règle de facturation ;
--   · `confiance` : 0 à 1, fondée sur la preuve (correction explicite > déduction) ;
--   · `statut`    : brouillon | active | retiree — une leçon peut être mise de
--     côté sans être effacée (rien ne se supprime sans le mot « supprime ») ;
--   · `version` et `preuve` : de quoi relire d'où elle vient.
--
-- Les leçons existantes deviennent des procédures actives de confiance moyenne :
-- le comportement d'aujourd'hui, explicité. Idempotente.

ALTER TABLE lecons ADD COLUMN IF NOT EXISTS type_lecon VARCHAR(20) NOT NULL DEFAULT 'procedure';
ALTER TABLE lecons ADD COLUMN IF NOT EXISTS confiance  REAL        NOT NULL DEFAULT 0.6;
ALTER TABLE lecons ADD COLUMN IF NOT EXISTS statut     VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE lecons ADD COLUMN IF NOT EXISTS version    INTEGER     NOT NULL DEFAULT 1;
ALTER TABLE lecons ADD COLUMN IF NOT EXISTS preuve     TEXT;

CREATE INDEX IF NOT EXISTS idx_lecons_actives_rang
    ON lecons (statut, confiance DESC, derniere_maj DESC);

COMMENT ON COLUMN lecons.confiance IS
  'Ce que vaut la leçon : 0,9 pour une correction explicite de la personne, 0,6 pour une '
  'déduction, plus bas pour une observation isolée. Sert à trancher entre deux leçons '
  'contradictoires — jamais à inventer une certitude.';
