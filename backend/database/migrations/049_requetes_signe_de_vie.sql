-- Un tour garde un signe de vie indépendant de sa connexion WebSocket.
-- Additive ; une demande interrompue ne sera jamais relancée automatiquement.
ALTER TABLE requetes_chat ADD COLUMN IF NOT EXISTS proprietaire VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_requetes_chat_actives
 ON requetes_chat(maj_le) WHERE etat='en_cours';
