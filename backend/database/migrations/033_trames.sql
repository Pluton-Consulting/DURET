-- 033 — LES TRAMES : ce qu'on reprend à chaque fois.
--
-- Demande de Noa (02/09) : « il doit être capable d'enregistrer des trames
-- qu'il reprend à chaque fois, que ce soit pour des documents, logo, méthodes,
-- process ».
--
-- POURQUOI UNE TABLE, ET PAS LES CONSIGNES. Une consigne (021) est une PHRASE
-- injectée dans le prompt à chaque tour : elle change le comportement du
-- modèle. Une trame est un OBJET qu'on rouvre et qu'on remplit — un devis type
-- avec son logo et sa trame de tableau, un classeur de suivi avec ses
-- formules. Les ranger ensemble ferait de l'un l'autre : soit on injecterait un
-- fichier de 300 ko dans chaque prompt, soit on laisserait un modèle réécrire
-- un document type. C'est la même raison qui a séparé `mail_signatures` (030)
-- de `mail_style_profiles` (013), et ce fichier en reprend la forme.
--
-- LES OCTETS VIVENT ICI, PAS SUR LE DISQUE. Le dépôt des documents produits est
-- un volume purgé à 24 h : une trame doit survivre à un redéploiement, à une
-- recréation de volume et à trois mois sans usage. Quelques centaines de
-- kilo-octets par trame, la base est le bon endroit — et c'est le même choix
-- que pour les images de signature.
--
-- PARTAGÉES PAR L'ENTREPRISE, PAS PRIVÉES. Ce que Nathalie enregistre, Éric le
-- retrouve : une trame est un bien commun, comme un modèle de devis dans un
-- classeur partagé. On garde QUI l'a posée (pour savoir à qui demander) sans en
-- faire une propriété.
--
-- Idempotente : rejouable sans dommage (règle du projet).

CREATE TABLE IF NOT EXISTS trames (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Le nom par lequel on la demande au chat (« devis type », « le logo »).
    -- Unique en minuscules : deux trames du même nom rendraient toute
    -- désignation ambiguë, et on ne devine jamais laquelle prendre.
    nom           VARCHAR(120) NOT NULL,
    -- 'document' : un .docx/.xlsx à rouvrir et remplir.
    -- 'logo'     : une image à réutiliser telle quelle.
    -- 'methode'  : une marche à suivre, un process — du texte.
    genre         VARCHAR(20) NOT NULL DEFAULT 'document',
    -- 'docx' | 'xlsx' | 'png' | 'jpeg' … NULL pour une méthode.
    type_fichier  VARCHAR(20),
    nom_fichier   VARCHAR(255),
    -- Les octets de l'original. NULL pour une méthode, qui n'a que du texte.
    contenu       BYTEA,
    -- Le texte d'une méthode, ou la description d'un document.
    texte         TEXT NOT NULL DEFAULT '',
    -- À quoi elle sert, en une phrase : c'est ce que le modèle lit pour
    -- choisir la bonne trame sans avoir à ouvrir les fichiers.
    description   TEXT NOT NULL DEFAULT '',
    -- Les variables détectées dans le document ({client}, [[ville]]…), pour
    -- dire à l'avance ce qu'il faudra fournir.
    variables     JSONB NOT NULL DEFAULT '[]',
    -- Ce que l'analyse a vu (tableaux, images, en-tête, feuilles) : sert à
    -- MONTRER la trame sans la rouvrir à chaque affichage.
    apercu        JSONB NOT NULL DEFAULT '{}',
    octets        INTEGER NOT NULL DEFAULT 0,
    actif         BOOLEAN NOT NULL DEFAULT true,
    cree_par      UUID REFERENCES users(id),
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    derniere_maj  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Combien de fois elle a servi : une trame jamais reprise est une trame à
    -- retirer, et on ne peut le savoir qu'en comptant.
    usages        INTEGER NOT NULL DEFAULT 0
);

-- Le nom fait foi pour désigner une trame : il doit être unique, insensible à
-- la casse. Un index UNIQUE sur l'expression plutôt qu'une contrainte sur la
-- colonne, sinon « Devis type » et « devis type » coexisteraient.
CREATE UNIQUE INDEX IF NOT EXISTS idx_trames_nom
    ON trames (lower(nom)) WHERE actif;

CREATE INDEX IF NOT EXISTS idx_trames_genre ON trames (genre) WHERE actif;
