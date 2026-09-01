-- 032 — LE PROFIL D'UNE PERSONNE : sa façon de parler, ses habitudes, ses
-- préférences, ce qu'elle n'a pas besoin de répéter.
--
-- POURQUOI UNE TABLE DE PLUS, alors qu'il en existe déjà trois qui apprennent.
-- Chacune répond à une autre question, et les mélanger les rendrait toutes
-- fausses :
--   · `consignes` (021) porte des ORDRES explicites — « appelle-moi Noa », posés
--     par un humain, retirables un par un. Ici rien n'est ordonné : c'est OBSERVÉ.
--   · `mail_style_profiles` (013) décrit une BOÎTE mail, pas une personne, et ne
--     sert qu'à rédiger des messages.
--   · La mémoire de conversation (025) rappelle des ÉCHANGES passés, datés, à la
--     demande. Ici on veut ce qui NE DATE PAS : une manière de travailler.
--
-- CE QUI EST STOCKÉ EST DU TEXTE RÉHYDRATÉ. Le profil doit contenir les vrais
-- noms pour servir à quelque chose ; c'est l'envoi au modèle qui est masqué,
-- jamais le stockage — même règle que `learning/debrief.py`.
--
-- `jusqu_a` est le CURSEUR : la passe de nuit ne relit que les conversations
-- touchées depuis. Sans lui, relire tout l'historique chaque nuit coûterait
-- davantage à chaque jour qui passe, pour n'apprendre presque rien de neuf.
--
-- Idempotente : rejouable sans dommage.

CREATE TABLE IF NOT EXISTS profils_utilisateur (
    user_id       UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profil        TEXT NOT NULL DEFAULT '',
    -- Ce que la dernière passe a lu : sert à l'écran, et à dire honnêtement
    -- sur quoi le profil se fonde.
    conversations INTEGER NOT NULL DEFAULT 0,
    messages      INTEGER NOT NULL DEFAULT 0,
    -- Le curseur : rien avant cet instant n'est relu.
    jusqu_a       TIMESTAMPTZ,
    derniere_maj  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Une personne peut refuser d'être observée : le profil existe alors mais
    -- ne s'injecte plus, et la passe de nuit la saute.
    actif         BOOLEAN NOT NULL DEFAULT true
);

-- La passe de nuit balaie par ancienneté de mise à jour : les comptes jamais
-- traités passent d'abord.
CREATE INDEX IF NOT EXISTS idx_profils_utilisateur_maj
    ON profils_utilisateur (derniere_maj) WHERE actif;
