-- 047 — LES JOBS DE VECTORISATION SE RÉCLAMENT (16/09, audit D-17, Duret).
--
-- Le worker prenait les jobs « en attente » par un simple SELECT : deux
-- processus (deux workers, ou un redémarrage pendant un lot) pouvaient
-- travailler le MÊME job, payer deux fois le fournisseur, et le résultat le
-- plus lent écrasait le plus récent.
--
-- Un job porte désormais son BAIL : qui le tient, jusqu'à quand, et quand il
-- pourra être retenté. La réclamation se fait par `FOR UPDATE SKIP LOCKED` :
-- deux workers ne prennent jamais la même ligne, et un bail expiré revient
-- naturellement dans la file.
--
-- `modele` retient AVEC QUOI le vecteur a été calculé : deux modèles de même
-- dimension ne partagent pas le même espace, et comparer leurs vecteurs donne
-- des résultats faux sans aucun message d'erreur. Idempotente.

ALTER TABLE embedding_jobs ADD COLUMN IF NOT EXISTS claimed_by      VARCHAR(80);
ALTER TABLE embedding_jobs ADD COLUMN IF NOT EXISTS lease_until     TIMESTAMPTZ;
ALTER TABLE embedding_jobs ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_embedding_jobs_a_prendre
    ON embedding_jobs (status, next_attempt_at NULLS FIRST, created_at);

-- L'identité de l'espace vectoriel, à côté du vecteur lui-même.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS embedding_modele VARCHAR(120);

COMMENT ON COLUMN embedding_jobs.lease_until IS
  'Jusqu''à quand ce job est réservé par claimed_by. Passé ce délai, il redevient '
  'disponible : un worker mort ne bloque pas la file.';
COMMENT ON COLUMN documents.embedding_modele IS
  'Le modèle qui a produit ce vecteur (fournisseur:modèle). NULL = corpus antérieur : '
  'la recherche lexicale reste la voie sûre pendant une migration de modèle.';
