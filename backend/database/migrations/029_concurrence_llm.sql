-- 029 — COMBIEN D'APPELS DE MODÈLE PARTENT EN MÊME TEMPS.
--
-- L'abonnement du fournisseur autorise un nombre fixe d'appels de front ; au
-- delà, il met en file puis refuse, et un refus coûte cinq minutes de
-- quarantaine dans le disjoncteur (llm/router.py). Le plafond doit donc se
-- régler sans redéploiement : globalement (réglages), par rôle (ici), et par
-- compte (ici) — un seul utilisateur ne doit pas prendre tous les créneaux.
--
-- NULL n'est PAS zéro : un plafond nul empêcherait la personne de se servir de
-- l'assistant. NULL veut dire « prends le plafond du rang au-dessus » —
-- compte, puis rôle, puis défaut du code (llm_simultanes_personne).
--
-- `users.quota_mensuel` existe déjà mais porte un autre sens (volume mensuel) :
-- la réutiliser lui ferait dire deux choses. Idempotente : rejouable sans risque.
ALTER TABLE role_quota_config ADD COLUMN IF NOT EXISTS concurrent_limit INTEGER;
ALTER TABLE users            ADD COLUMN IF NOT EXISTS llm_simultanes  INTEGER;

-- Un défaut par rôle, pour que l'écran montre des valeurs plutôt que des vides.
-- La direction et l'administration système en ont davantage : ce sont eux qui
-- lancent les gros traitements.
UPDATE role_quota_config SET concurrent_limit = CASE role
    WHEN 'super_admin' THEN 5
    WHEN 'direction'   THEN 4
    ELSE 3 END
 WHERE concurrent_limit IS NULL;
