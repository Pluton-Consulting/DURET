-- 026 — Réglages système NON SECRETS, modifiables depuis les Paramètres.
--
-- La migration 018 (`cles_api`) a rendu les identifiants modifiables sans
-- session SSH. Le même besoin existe pour des réglages qui ne sont PAS des
-- secrets — à commencer par `llm_tete`, le modèle forcé en tête de cascade,
-- qu'il fallait jusqu'ici écrire dans le `.env` de CHAQUE serveur puis recréer
-- le conteneur. Deux clients, deux VPS, deux sessions SSH pour un essai de
-- modèle : le réglage le plus expérimental du socle était le plus coûteux à
-- changer.
--
-- TABLE SÉPARÉE DE `cles_api`, ET NON UNE LIGNE DE PLUS DEDANS.
-- Le contrat de `cles_api` tient en une phrase : « la valeur ne ressort jamais
-- de l'API ». Un réglage non secret doit au contraire s'AFFICHER — sans quoi
-- personne ne peut vérifier ce qui est en vigueur. Les loger ensemble
-- obligerait à percer une exception dans cet invariant, et c'est exactement
-- l'érosion qui rend un jour une clé lisible par accident.
--
-- Comme pour 018, la base SURCHARGE l'environnement : une instance sans ligne
-- ici se comporte exactement comme avant, ce qui rend la migration neutre.

CREATE TABLE IF NOT EXISTS reglages (
    cle         VARCHAR(64)  PRIMARY KEY,      -- ex. 'llm_tete'
    valeur      TEXT         NOT NULL,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_by  UUID         REFERENCES users(id)
);

COMMENT ON TABLE reglages IS
  'Réglages système NON secrets, saisis depuis les Paramètres (manage_system). '
  'Priorité sur le .env. Valeur affichable — contrairement à cles_api.';
