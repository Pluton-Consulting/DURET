-- Fichier de SEED DEV (préfixe _ : jamais exécuté automatiquement comme migration).
-- Crée un utilisateur super_admin de test pour les smoke tests locaux.
INSERT INTO users (email, name, role)
VALUES ('dev@pluton.local', 'Dev Super Admin', 'super_admin')
ON CONFLICT (email) DO UPDATE SET role = 'super_admin', actif = true
RETURNING id, email, role;
