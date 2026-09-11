-- Fichier de SEED DEV (préfixe _ : jamais exécuté automatiquement comme migration).
-- Crée un utilisateur super_admin de test pour les smoke tests locaux.
-- Pas de conflit sur l'adresse : elle n'est plus unique à elle seule depuis la 040.
INSERT INTO users (email, name, role)
SELECT 'dev@pluton.local', 'Dev Super Admin', 'super_admin'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE lower(email) = 'dev@pluton.local');
UPDATE users SET role = 'super_admin', actif = true
 WHERE lower(email) = 'dev@pluton.local'
RETURNING id, email, role;
