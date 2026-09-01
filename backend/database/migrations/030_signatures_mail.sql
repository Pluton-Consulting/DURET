-- 030 — LA SIGNATURE de mail, par boîte.
--
-- Séparée de `mail_style_profiles` (013) pour une raison de NATURE, pas de
-- rangement : un profil de style est une DESCRIPTION distillée par un modèle
-- et réinjectée dans un prompt ; une signature est une DONNÉE reproduite à
-- l'identique. Les mélanger reviendrait à laisser un modèle réécrire un
-- numéro de téléphone ou une mention légale — et il finirait par le faire.
--
-- Les octets du logo vivent ICI, en base64, ET dans le dépôt des visuels au
-- moment de l'apposer : le dépôt est un volume disque, une signature doit
-- survivre à un volume recréé. Quelques dizaines de kilo-octets, la base est
-- le bon endroit.
--
-- Idempotente : rejouable sans dommage (règle du projet).

CREATE TABLE IF NOT EXISTS mail_signatures (
    mailbox      VARCHAR(255) PRIMARY KEY,     -- en minuscules, comme partout
    html         TEXT NOT NULL DEFAULT '',     -- la signature telle qu'elle s'affiche
    texte        TEXT NOT NULL DEFAULT '',     -- son équivalent lisible (repli)
    images       JSONB NOT NULL DEFAULT '[]',  -- [{content_id, nom, mime, octets_b64}]
    source       TEXT,                         -- d'où on l'a apprise (objet + date)
    active       BOOLEAN NOT NULL DEFAULT true,
    derniere_maj TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by   UUID REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_mail_signatures_active
    ON mail_signatures (mailbox) WHERE active;
