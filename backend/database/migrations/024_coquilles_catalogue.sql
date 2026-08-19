-- ============================================================
--  024 — Les coquilles du catalogue metier ne sont pas des capacites
-- ============================================================
--
-- `seed_skills_catalogue.py` seme au depart un catalogue de competences
-- metier (recherche_chantier_similaire, historique_devis_client, ...) dont
-- le code est un SQUELETTE : il rend « [A COMPLETER] » partout et le dit
-- lui-meme (« Squelette generique : implementer la logique metier »).
-- C'est une feuille de route visible a l'ecran, pas une competence.
--
-- Validees depuis l'onglet Apprentissage, ces coquilles etaient exposees au
-- modele comme des actions ; leur effet, jamais qualifie, valait « externe »
-- (defaut fail-closed de la migration 015). Resultat releve au banc de
-- recette : pour « retrouve un chantier similaire a Arcachon », le modele
-- choisit la coquille, l'ecran reclame un accord humain pour une lecture,
-- et l'execution ne rendrait rien — pendant que la vraie recherche
-- (`rechercher_documents`) reste inutilisee.
--
-- Le code (catalogue + executeur) ne les expose plus ni ne les execute, quel
-- que soit leur statut. Ici on aligne la base : desactivees, et rendues a
-- l'etat de brouillon, pour que l'ecran dise ce qu'elles sont. Rien n'est
-- supprime : elles restent une feuille de route.

UPDATE skills
   SET enabled = false,
       status  = 'draft',
       updated_at = NOW()
 WHERE COALESCE(code, '') LIKE '%Squelette g_n_rique%'
   AND (COALESCE(enabled, true) OR status IN ('validated', 'stable'));
