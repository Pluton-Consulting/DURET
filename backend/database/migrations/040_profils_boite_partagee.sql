-- 040 — Plusieurs profils sur une même adresse, et les dossiers de mail de chacun (11/09, Duret).
--
-- Demande de Noa : « tout le monde a le même mail » — la boîte de
-- l'entreprise, reliée par mot de passe d'application. Chaque PRÉNOM est
-- pourtant un utilisateur à part entière : son chat, ses consignes, ses
-- documents, ses tâches. Tout ce qui est « à quelqu'un » est déjà rangé par
-- `users.id` ; seule l'adresse unique empêchait d'avoir plusieurs comptes.
--
-- 1. L'unicité passe de l'ADRESSE au couple (adresse, nom). Deux profils
--    « Nathalie » sur la même adresse seraient indiscernables sur l'écran des
--    cartes ; deux adresses différentes restent libres de porter le même nom.
--    Insensible à la casse, comme la connexion.
-- 2. `dossiers_mail` : les dossiers de la boîte que ce profil peut lire, en
--    plus de la boîte de réception (le « mail général »). NULL = aucune
--    restriction — c'est l'état de tous les comptes existants, rien ne change
--    pour eux ; un tableau vide = la boîte de réception seule.
--
-- ⚠️ `ON CONFLICT (email)` n'a plus de contrainte à laquelle s'accrocher :
-- `deploy.sh` et `_dev_seed.sql` sont réécrits en conséquence. Idempotente.

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_nom
    ON users (lower(email), lower(coalesce(name, '')));

ALTER TABLE users ADD COLUMN IF NOT EXISTS dossiers_mail TEXT[];

COMMENT ON COLUMN users.dossiers_mail IS
  'Dossiers de la boîte partagée lisibles par ce profil, EN PLUS de la boîte de réception. '
  'NULL = aucune restriction ; tableau vide = la boîte de réception seule.';
