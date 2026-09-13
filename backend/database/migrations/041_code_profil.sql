-- 041 — Le code d'une carte de profil (13/09, Duret).
--
-- La page de connexion est un choix de prénom : un profil de la boîte de
-- l'entreprise entre d'un clic, sans lien magique. Noa veut pouvoir y mettre
-- AUSSI la direction — qui voit tout, gère les utilisateurs et délivre des
-- liens d'accès. Sa carte demande donc un code (4 à 6 chiffres), facultatif
-- pour les autres profils, obligatoire pour la direction sur la boîte.
--
-- * `code_pin_hash` : l'EMPREINTE (PBKDF2-SHA256, sel propre), jamais le code ;
-- * `code_pin_echecs` / `code_pin_bloque_jusqu` : cinq essais faux bloquent la
--   carte un quart d'heure — six chiffres se devinent sinon en une nuit.
-- Idempotente. Sans elle, aucune carte n'a de code et la direction n'a pas de
-- carte : le lien magique reste sa porte, comme avant.

ALTER TABLE users ADD COLUMN IF NOT EXISTS code_pin_hash TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS code_pin_echecs INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS code_pin_bloque_jusqu TIMESTAMPTZ;

COMMENT ON COLUMN users.code_pin_hash IS
  'Empreinte PBKDF2 du code de la carte de connexion (jamais le code). NULL = pas de code.';
