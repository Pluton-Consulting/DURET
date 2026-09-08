-- 039 — La colonne « Accès au mail » (08/09).
--
-- La base fait foi pour la matrice des permissions (leçon de la 028) : une
-- permission ajoutée au code n'existe pas tant qu'elle n'est pas semée. Elle
-- est accordée à TOUS les rôles — c'est ce qu'ils avaient avant la colonne —
-- et la direction décoche ce qu'elle veut. DO NOTHING : un choix déjà fait
-- à l'écran n'est pas écrasé. Idempotente.

INSERT INTO roles_permissions (role, feature, allowed)
SELECT r, 'access_mail', true
FROM unnest(ARRAY['super_admin', 'direction', 'commercial', 'bureau_etudes',
                  'conducteur', 'administratif', 'terrain']) AS r
ON CONFLICT (role, feature) DO NOTHING;
