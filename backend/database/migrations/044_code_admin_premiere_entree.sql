-- 044 — Le code de PREMIÈRE ENTRÉE d'un administrateur ne sert qu'une fois
-- (16/09, audit D-19, Duret).
--
-- Depuis le 15/09, un super_admin qui n'a pas encore posé de code entre avec le
-- code de première entrée du serveur (`CODE_ADMIN_DEFAUT`). C'était un secret
-- PERMANENT : le même code ouvrait la porte indéfiniment, sur toutes les
-- installations qui n'avaient rien changé.
--
-- `code_defaut_le` retient l'instant où ce code a servi. Après, il ne vaut plus
-- rien : l'administrateur pose le sien à l'entrée (l'écran l'y oblige), et s'il
-- ne l'a pas fait, la reprise passe par le script d'exploitation
-- `backend/scripts/code_admin.py`, hors de l'interface.
--
-- Sans cette migration, le code de première entrée est REFUSÉ (fail-closed) :
-- on ne saurait pas qu'il a déjà servi. Idempotente.

ALTER TABLE users ADD COLUMN IF NOT EXISTS code_defaut_le TIMESTAMPTZ;

COMMENT ON COLUMN users.code_defaut_le IS
  'Instant où le code de première entrée (CODE_ADMIN_DEFAUT) a été utilisé pour ce profil. '
  'NULL = jamais utilisé. Renseigné, ce code est refusé : seul un vrai code ouvre la carte.';
