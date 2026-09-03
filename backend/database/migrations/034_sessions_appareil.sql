-- 034 — LA SESSION D'APPAREIL : se connecter UNE FOIS sur un poste, plus jamais ensuite.
--
-- LE BESOIN (03/09, Noa) : « il faudrait que chacun puisse se connecter avec
-- son mail comme actuellement mais sans resaisir le mail et sans aller cliquer
-- sur le magic link à chaque fois, car ça prend beaucoup trop de temps. »
--
-- CE QUI SE PASSAIT. Le lien magique rendait un JWT de 24 h, et RIEN d'autre :
-- passé ce délai il n'existait aucune trace qu'un appareil avait déjà prouvé
-- son identité. Le lendemain, tout était à refaire — taper son adresse, ouvrir
-- sa boîte, cliquer. Trois gestes et une attente, chaque jour, par personne.
--
-- CE QUE CETTE TABLE AJOUTE. Une preuve DURABLE, posée sur l'appareil au
-- moment où le lien magique est consommé : un jeton long, aléatoire, que le
-- navigateur renvoie pour obtenir un JWT frais sans repasser par le mail. Le
-- lien magique reste la SEULE porte d'entrée — il n'est franchi qu'une fois
-- par appareil.
--
-- POURQUOI UNE TABLE, ET PAS UN JWT PLUS LONG. Un JWT ne se révoque pas : le
-- rallonger à un an, c'est perdre tout moyen de couper l'accès d'un poste volé
-- ou d'un salarié parti. Ici chaque appareil est une LIGNE — donc visible dans
-- Paramètres, et coupable d'un clic. C'est le prix d'entrée d'une session qui
-- ne périme pas.
--
-- `jeton_hash`, JAMAIS le jeton. La base ne stocke que l'empreinte SHA-256 :
-- une copie de la table ne permet de se connecter nulle part. Même raison
-- qu'un mot de passe — la valeur en clair n'existe que dans le navigateur.
--
-- `expire_le` NULL = ILLIMITÉ (décision de Noa du 03/09 : « illimité tant
-- qu'on ne se déconnecte pas »). La colonne existe quand même, pour que le
-- réglage `SESSION_APPAREIL_JOURS` puisse poser une échéance glissante sans
-- migration de plus si l'entreprise change d'avis.
--
-- Idempotente : rejouable sans dommage.

CREATE TABLE IF NOT EXISTS sessions_appareil (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id              UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Empreinte SHA-256 du jeton. UNIQUE : deux appareils ne partagent jamais
    -- une session, et un rejeu ne peut pas créer de doublon silencieux.
    jeton_hash           TEXT NOT NULL UNIQUE,
    -- « Chrome sur Mac » — de quoi RECONNAÎTRE son poste dans la liste et
    -- repérer celui qu'on ne reconnaît pas. Déduit de l'en-tête du navigateur,
    -- jamais une adresse IP : on veut que la personne s'y retrouve, pas la
    -- pister.
    appareil             TEXT NOT NULL DEFAULT '',
    cree_le              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    derniere_utilisation TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- NULL = pas d'échéance. Voir ci-dessus.
    expire_le            TIMESTAMPTZ,
    -- Révoquée : « Se déconnecter », un appareil coupé depuis Paramètres, ou
    -- une déconnexion totale. On garde la ligne (l'historique dit QUAND l'accès
    -- a été coupé) plutôt que de l'effacer.
    revoque_le           TIMESTAMPTZ
);

-- L'écran « Mes appareils » lit toujours ainsi : les sessions vivantes d'une
-- personne, la plus récemment utilisée en tête.
CREATE INDEX IF NOT EXISTS idx_sessions_appareil_user
    ON sessions_appareil (user_id, derniere_utilisation DESC)
    WHERE revoque_le IS NULL;
