-- 045 — Le registre des EFFETS EXTERNES (16/09, audit D-11, Duret).
--
-- L'accord humain était déjà réclamé atomiquement : deux personnes ne peuvent
-- pas approuver deux fois la même carte. Mais entre « approuvé » et « le mail
-- est parti », il n'y avait RIEN d'écrit : un redémarrage au mauvais moment, ou
-- une réponse SMTP perdue, laissaient la question sans réponse — et la seule
-- façon de « vérifier » était de renvoyer, donc parfois d'envoyer deux fois.
--
-- Une opération porte désormais DEUX états distincts :
--   · `decision`  : ce que l'humain a tranché (preparee, approuvee, refusee) ;
--   · `execution` : ce que le monde extérieur a fait (en_attente, en_cours,
--                   reussie, echouee, effet_inconnu).
-- `effet_inconnu` est le cas honnête : on ne sait pas. On ne relance JAMAIS
-- tout seul ; on cherche une preuve chez le fournisseur, et l'écran dit
-- « résultat à vérifier ».
--
-- `recu` garde ce que le fournisseur a rendu (identifiant de message, de
-- brouillon) : c'est lui qui permet la réconciliation. Idempotente.

CREATE TABLE IF NOT EXISTS operations_externes (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- La validation d'où vient l'opération (quand il y en a une).
    validation_id UUID,
    user_id       UUID REFERENCES users(id) ON DELETE SET NULL,
    thread_id     VARCHAR(255),
    skill         VARCHAR(120) NOT NULL,
    effet         VARCHAR(30)  NOT NULL DEFAULT 'externe',
    -- L'empreinte de CE QUI A ÉTÉ APPROUVÉ : ce qui s'exécute est ce qui a été lu.
    payload_hash  VARCHAR(128),
    decision      VARCHAR(20)  NOT NULL DEFAULT 'preparee',
    execution     VARCHAR(20)  NOT NULL DEFAULT 'en_attente',
    recu          JSONB        NOT NULL DEFAULT '{}',
    erreur        TEXT,
    cree_le       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    maj_le        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Une opération par validation : c'est ce qui empêche un second envoi après une
-- reprise (la réclamation échoue si elle est déjà en cours ou terminée).
CREATE UNIQUE INDEX IF NOT EXISTS idx_operations_validation
    ON operations_externes (validation_id) WHERE validation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_operations_execution
    ON operations_externes (execution, cree_le DESC);

COMMENT ON COLUMN operations_externes.execution IS
  'en_attente | en_cours | reussie | echouee | effet_inconnu — état du monde extérieur, '
  'distinct de la décision humaine. effet_inconnu ne se relance jamais tout seul.';
