-- 018 — Clés d'API saisissables depuis les Paramètres (super_admin).
--
-- Jusqu'ici, changer de fournisseur de modèle imposait d'éditer le `.env` sur
-- le serveur puis de redéployer. Une clé qui expire un vendredi soir bloquait
-- donc l'application jusqu'à ce que quelqu'un ouvre une session SSH.
--
-- Cette table les rend modifiables depuis l'interface. Elle NE REMPLACE PAS le
-- `.env` : elle le SURCHARGE. L'ordre de résolution est base -> environnement,
-- si bien qu'une instance sans ligne ici se comporte exactement comme avant.
--
-- ⚠ La valeur est stockée EN CLAIR, comme elle l'est déjà dans le `.env` et
-- dans l'environnement du conteneur. Ce n'est donc pas une dégradation, mais
-- l'exposition s'élargit : une sauvegarde de base contient désormais les clés.
-- Trois contreparties, appliquées dans le code :
--   * l'API ne renvoie JAMAIS la valeur, seulement une empreinte masquée ;
--   * seul `manage_system` peut lire cette liste ou écrire dedans ;
--   * toute modification est journalisée — sans la valeur.

CREATE TABLE IF NOT EXISTS cles_api (
    cle         VARCHAR(64)  PRIMARY KEY,      -- ex. 'deepseek_api_key'
    valeur      TEXT         NOT NULL,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_by  UUID         REFERENCES users(id)
);

COMMENT ON TABLE cles_api IS
  'Surcharge des identifiants de fournisseurs LLM, saisis depuis les Paramètres. '
  'Priorité sur le .env. Jamais renvoyée en clair par l''API.';
