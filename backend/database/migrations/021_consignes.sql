-- Consignes permanentes : ce qu'on apprend à l'assistant depuis le chat.
--
-- POURQUOI UNE TABLE À PART, et pas la mémoire d'entreprise. Une connaissance
-- rangée dans `documents` est retrouvée par recherche SÉMANTIQUE : elle remonte
-- quand la question lui ressemble, et pas autrement. C'est le bon comportement
-- pour un fait (« les devis sont valables 30 jours ») et le mauvais pour une
-- règle de comportement (« chez nous, "le serveur" désigne le NAS ») : celle-là
-- doit être présente AVANT que le modèle choisisse son action, sur chaque tour,
-- que la question lui ressemble ou non.
--
-- Une consigne qui s'applique « parfois » est pire qu'absente : personne ne peut
-- prévoir quand elle vaudra.
--
-- PORTÉE. `user_id` NULL = consigne d'ENTREPRISE, valable pour tout le monde ;
-- sinon elle n'appartient qu'à cette personne. Écrire pour toute l'entreprise
-- modifie le comportement de l'assistant chez les collègues : ce droit est
-- vérifié côté applicatif, pas ici.

CREATE TABLE IF NOT EXISTS consignes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    texte TEXT NOT NULL,

    -- NULL = toute l'entreprise. Sinon, propriétaire de la consigne.
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,

    -- Pour les consignes d'entreprise : qui les voit. Même échelle que les
    -- documents, pour qu'une règle destinée à la direction ne s'impose pas au
    -- terrain.
    access_level VARCHAR(50) NOT NULL DEFAULT 'all',

    cree_par UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Désactiver plutôt que supprimer : on garde la trace de ce qui a été
    -- enseigné, et une consigne retirée par erreur se remet sans la réécrire.
    actif BOOLEAN NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_consignes_actives
    ON consignes (actif, user_id, access_level);

-- Deux fois la même consigne ne sert à rien et dilue les autres.
CREATE UNIQUE INDEX IF NOT EXISTS idx_consignes_unicite
    ON consignes (COALESCE(user_id, '00000000-0000-0000-0000-000000000000'::uuid),
                  lower(texte))
    WHERE actif;
