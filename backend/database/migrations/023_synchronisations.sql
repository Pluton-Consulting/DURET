-- ============================================================================
-- Historique persistant des synchronisations de connecteurs.
-- ============================================================================
--
-- POURQUOI UNE TABLE. L'état vivait dans un dictionnaire Python (`_SYNCS`,
-- routers/ingestion.py) : il MEURT avec le processus. Le gérant a redémarré le
-- backend pour débloquer une ingestion coincée, et l'écran « Synchronisations »
-- a répondu « Jamais lancée » sur tous les connecteurs — alors que le Drive
-- venait de tourner vingt minutes. Ce n'est pas un défaut d'affichage : c'est
-- l'application qui affirme le contraire de ce que la personne vient de faire.
--
-- POURQUOI PAS `audit_log`. L'audit contient DÉJÀ une ligne `ingestion_sync`
-- par synchronisation réussie, et il la garde. Il ne peut pourtant pas porter
-- cet état :
--   1. il est INSERT-seul par contrat (« jamais d'UPDATE, jamais de DELETE »),
--      or une barre de progression est une ligne qu'on RÉÉCRIT sans cesse ;
--   2. il n'écrit qu'à la FIN et seulement en cas de succès — les branches
--      `except` ne loguent rien, donc ni les échecs ni le « en cours depuis
--      quatre minutes » n'y figurent ;
--   3. requalifier une synchro fantôme exige un UPDATE, impossible sur une
--      table append-only.
-- L'audit reste la trace IMMUABLE de qui a déclenché quoi ; cette table porte
-- l'état OPÉRATIONNEL, mutable par nature.
--
-- POURQUOI UNE LIGNE PAR EXÉCUTION. Une table « une ligne par source » qu'on
-- écrase perd la date de la dernière RÉUSSITE dès qu'un échec passe par-dessus.
-- C'est justement la date demandée. Ici, « le dernier état » et « la dernière
-- réussite » sont deux lectures de la même table. Le volume est dérisoire :
-- quelques lignes par jour.

CREATE TABLE IF NOT EXISTS synchronisations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Clé du connecteur : 'outlook', 'google_drive', 'extrabat'…
    -- VOLONTAIREMENT SANS CHECK NI CLÉ ÉTRANGÈRE. La liste vit dans le code
    -- (`CONNECTEURS`) et change d'un client à l'autre — Duret & Sols n'a pas la
    -- même. Un CHECK ici imposerait une migration à chaque connecteur ajouté,
    -- et ferait échouer l'INSERT d'une source parfaitement légitime ailleurs.
    source VARCHAR(64) NOT NULL,

    -- en_cours | terminee | echec | non_configure | interrompue
    -- « jamais lancée » N'EST PAS un statut : c'est l'ABSENCE de ligne. Un
    -- statut 'jamais' stocké devrait être créé par quelqu'un, et ce quelqu'un
    -- n'existe pas. Le routeur complète avec les connecteurs jamais vus.
    statut VARCHAR(24) NOT NULL DEFAULT 'en_cours',

    -- Ce qu'on est en train de faire, en français, pour l'écran.
    etape TEXT,
    -- Avancement. `total` est NULLABLE, et c'est le cœur du contrat : le Drive
    -- connaît son total, Outlook ne le connaît que tard, Extrabat jamais.
    -- `total IS NULL` = barre INDÉTERMINÉE. On n'invente pas un pourcentage :
    -- une barre qui affiche 40 % sans savoir est pire que pas de barre.
    traites INTEGER NOT NULL DEFAULT 0,
    total INTEGER,

    resultat JSONB,
    erreur TEXT,

    lance_par UUID REFERENCES users(id) ON DELETE SET NULL,
    -- L'e-mail est FIGÉ ici : supprimer un compte ne doit ni effacer
    -- l'historique (CASCADE) ni bloquer la suppression (RESTRICT).
    lance_par_email TEXT,

    demarre_a TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    termine_a TIMESTAMPTZ,
    -- Battement de cœur : sert à afficher « en cours depuis X », et surtout à
    -- repérer une synchronisation PENDUE — celle qui ne rend jamais la main.
    maj_a TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_synchronisations_source_date
    ON synchronisations (source, demarre_a DESC);

-- UN SEUL 'en_cours' PAR SOURCE, garanti par la base. Le garde-fou anti-doublon
-- lisait un dictionnaire en mémoire : il ne survivait ni au redémarrage, ni au
-- jour où l'on passera uvicorn à plusieurs workers. Ici c'est un invariant.
CREATE UNIQUE INDEX IF NOT EXISTS idx_synchronisations_une_seule_en_cours
    ON synchronisations (source) WHERE statut = 'en_cours';

-- AMORÇAGE DEPUIS L'AUDIT. Sans ça, l'écran afficherait « Jamais lancée » sur
-- des connecteurs qui ont tourné des dizaines de fois — le défaut qu'on corrige,
-- reproduit le jour du déploiement. `audit_log` porte déjà une ligne par
-- synchronisation réussie : on reprend la DERNIÈRE de chaque source. C'est un
-- pur INSERT dans une table neuve, il ne détruit rien.
INSERT INTO synchronisations (source, statut, resultat, demarre_a, termine_a, maj_a)
SELECT DISTINCT ON (a.metadata->>'source')
       a.metadata->>'source', 'terminee', a.metadata, a.created_at, a.created_at,
       a.created_at
  FROM audit_log a
 WHERE a.action = 'ingestion_sync'
   AND a.metadata->>'source' IS NOT NULL
 ORDER BY a.metadata->>'source', a.created_at DESC
ON CONFLICT DO NOTHING;
