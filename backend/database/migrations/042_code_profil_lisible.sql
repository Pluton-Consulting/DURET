-- 042 — Le code d'une carte se RELIT en administration (14/09, Duret).
--
-- Demande de Noa : « les codes PIN, on doit pouvoir les configurer depuis
-- l'admin quand on crée les utilisateurs, et pouvoir les voir et les modifier
-- après ». La 041 ne gardait que l'empreinte — un code oublié ne pouvait être
-- que remplacé, jamais relu.
--
-- * `code_pin_chiffre` : le code CHIFFRÉ (Fernet, clé dérivée du secret JWT du
--   serveur), relu par l'écran Utilisateurs pour les profils que
--   l'administrateur gère, et par la personne elle-même dans son espace ;
-- * la VÉRIFICATION reste sur l'empreinte (`code_pin_hash`) : changer le secret
--   JWT rend le code illisible à l'écran, il continue d'ouvrir la carte.
-- Un code posé avant cette migration n'a pas de version chiffrée : l'écran le
-- dit (« posé, illisible ») et un nouveau code le remplace. Idempotente.

ALTER TABLE users ADD COLUMN IF NOT EXISTS code_pin_chiffre TEXT;

COMMENT ON COLUMN users.code_pin_chiffre IS
  'Code de la carte chiffré (Fernet, clé dérivée de JWT_SECRET_KEY), relu en administration. '
  'La vérification se fait sur code_pin_hash. NULL = pas de code, ou code posé avant la 042.';
