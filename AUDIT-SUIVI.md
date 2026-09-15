# Suivi de l'audit détaillé du 15/09 — Duret & Sols

Branche `audit/duret` (worktree `infra IA/DURET-audit`), partie du tag
`sauvegarde/avant-audit-2026-09-16` (8050e28). Document source : « Audit détaillé -
Duret et Symbiose.docx » (copie dans `infra IA/sauvegardes/2026-09-16-avant-audit/`).

Règles de Noa (16/09) : lot par lot (un lot + ses bancs → validation et déploiement
par Noa → lot suivant) ; opérations serveur = scripts + procédures que Noa lance ;
branches poussées sur benit seulement ; code admin « 0000 » à usage unique.

## Lot 1 — premier lot court + garde-fous

| Fiche | Sujet | État |
|---|---|---|
| D-02 | Styles Word conservés au remplacement, contrôle du fichier produit | fait (bancs réels) |
| D-05 | Échecs métier jamais présentés comme réussis | étape 1 faite (normaliseur, exécuteur, boucle, reprise) ; reçus avant « créé/envoyé » et preuves par requête : lot suivant |
| D-06 | Secours lexical quand les embeddings tombent | étape 1 faite (embedding et voie vectorielle isolés, diagnostic, panne ≠ absence) ; orchestrateur de sources et comparables NAS : lot 2 |
| D-03 | Bearer jamais envoyé à une origine externe ; propriété des visuels | étape 1 faite (jeton par origine, propriétaire noté au dépôt, route et pièces jointes contrôlées, pièce de mail résolue dans sa boîte, script de rattachement des anciens) ; registre PostgreSQL des ressources, médias DOCX, résultat structuré d'image manquante : lot suivant |
| D-27 | Doublons NAS : plus d'exclusion sur nom+taille | étape 1 faite (copies lues en dernier et reconnues à leur contenu, « toujours apprendre », fichiers écartés retentés et repris à la main, écritures atomiques) ; écran détaillé du tri, budgets et baux, niveaux réactualisés, références et couverture de `nas_chercher` : lots 2 et 4 |
| D-19 | Code admin : refus sur schéma incomplet, tentatives atomiques, « 0000 » à usage unique | fait (verdict typé fail-closed, verrou de ligne, code de première entrée à usage unique + migration 044, clé de chiffrement séparée, borne par origine, script de secours) ; réauthentification ciblée pour l'administration : lot suivant |
| D-22 | Export CSV neutralisé, export borné, secrets dans les traces | étape 1 faite (cellules inertes, fin bornée + pagination par clé + manifeste, ticket de téléchargement, filtre des secrets sur les handlers et les traces) ; carte des sorties, modes de confidentialité et rétention par type : lot 4 |
| D-23 / D-26 / D-00 | Scripts de sauvegarde, de déploiement vérifié et procédure de recette | fait (backup.sh complet et vérifié, restaurer.sh isolé, deploy.sh réordonné avec ligne de base vérifiée, readiness séparée de la liveness, RECETTE-LOT1.md) ; exercice de restauration réel : à jouer par Noa |

## Lot 2 — documents durables, sources retrouvables, droits et recherche

| Fiche | Sujet | État |
|---|---|---|
| D-04 | Versions de documents et atelier durables | fait (verrou, écriture atomique, compteur réconcilié, lignée et manifeste, purge par groupe, quota qui refuse au lieu d'effacer) |
| D-07 | Références de sources stables | étape 1 faite (registre durable des messages et pièces, relu après redémarrage) ; couverture des recherches et registre en base : lots suivants |
| D-01 | Choisir et réutiliser le bon document de référence | fait (référence du travail mémorisée, remplacements déjà donnés repris, original modifié signalé) |
| D-09 | Droits appliqués avant les résultats et les comptes | à faire |
| D-08 | Réindexer sans effacer prématurément | à faire |
| D-10 | Lire complètement les mails | à faire |

## Journal

- 16/09 — D-02 : `bureautique/trame.py` réécrit le remplacement Word nœud `w:t` par nœud
  (styles des fragments, dessins, champs, zones de texte, tableaux imbriqués, en-têtes de
  première page) ; remplacements simultanés, chevauchements refusés ; formules Excel jamais
  réécrites ; `bureautique/controle.py` compare original et résultat rouvert. Bancs
  `test_trame_document` (+13), `test_reproduire_du_serveur`, `test_trame_pdf` verts avec
  python-docx/openpyxl/PyMuPDF réels.
- 16/09 — D-05 (étape 1) : `skills/resultats.py` (outcome, ok, effect_status, evidence_refs,
  warnings, retryable) ; `execute_skill` rend `ok` métier + champs d'avant, audit en échec ;
  `tools_node` et la reprise après accord suivent `ok`. Banc `test_resultats_normalises`.
- 16/09 — hors fiche (trouvé par la suite de bancs) : relances de facturation comptées au jour
  UTC — entre minuit et 2 h « relancée à l'instant » devenait « il y a 1 jour ». Jour à Paris.
- 16/09 — D-06 (étape 1) : `vectorstore/rag.py` calcule le vecteur hors du `try` de la recherche
  (`_embedding_sans_panne`), `retrieve_detaille` rend le diagnostic (API liste conservée),
  `search_hybrid` isole la voie vectorielle, `rechercher_documents` distingue panne (ok False,
  interdiction de conclure à l'absence) et « rien trouvé », et dit la couverture. Banc
  `test_recherche_documents` +5.
- 16/09 — D-03 (étape 1) : `frontend/lib/origineBackend.ts` — l'aperçu et « Télécharger » ne posent
  `Authorization` que pour l'origine du backend (ou de la page) ; un lien tiers se charge sans jeton.
  `visuels/depot.py` note le propriétaire de chaque dépôt fait pendant un geste (`<clé>.acces`,
  écriture atomique sous verrou, noté AVANT l'image) via `security.lecteur.id_lecteur` ; `peut_lire`
  (super_admin, propriétaire ; visuel ancien sans propriétaire : lisible, jamais réclamé par un
  redépôt) ; la route répond 404 et `Vary: Authorization` ; `mail/attaches._du_depot` vérifie ; les
  photos jointes au chat appartiennent à la personne du tour (agent2). Une pièce de mail insérée dans
  un document se résout dans SA boîte (`mail.lecture.boite_de_piece` + `verifier_acces`) au lieu d'une
  boîte vide. `scripts/rattacher_visuels.py` (constat / `--ecrire` / `--fermer-indetermines`) établit
  les propriétaires des visuels anciens d'après les messages qui les citent. Choix : fichiers voisins
  dans le volume des documents plutôt qu'une migration (D-23 doit sauvegarder ce volume). Banc
  `test_visuels_proprietaire` ; `test_pieces_multiples` charge le vrai contexte du lecteur ;
  `test_resultats_normalises` dit sa section sautée sous Python < 3.10.
- 16/09 — D-27 (étape 1) : `nas/tri.py` — `copies_possibles` remplace `doublons` : une copie
  possible (même nom, même taille) n'est plus écartée, elle est lue APRÈS les originaux, dans
  des paquets à part (sinon les quatre lectures de front liraient l'original et sa copie en même
  temps) ; une vraie copie se reconnaît à l'empreinte SHA-256 de son contenu
  (`nas_empreintes.json`) et reprend les morceaux et vecteurs de l'original
  (`vectorstore.copier_source`, `ingestion.pipeline.copier_document`) sous SA source, SON nom et
  SON niveau d'accès — deux affaires ne fusionnent pas leurs droits ; une copie dont l'original
  n'a plus ses morceaux est relue. Décision « toujours apprendre » (âge sans effet, réservée à
  l'administrateur : l'IA ne la propose pas). Un fichier écarté porte une fiche (motif, essais,
  prochain essai) : « trop lent » est retenté à 1, 3, 7 puis 30 jours, « sans texte » attend que
  le fichier change, et `POST /api/nas-tri/reprendre` (bouton « Réessayer ces fichiers ») relance
  tout de suite. Les trois mémoires (écartés, scans de nuit, empreintes) vivent dans `nas/tri.py`
  et s'écrivent atomiquement ; une disparition n'est conclue que sur un relevé COMPLET et non
  restreint à un dossier (avant, un essai sur un dossier vidait la liste de la nuit). Bancs
  `test_tri_nas` (+28, dont la synchronisation réelle avec copies, fichier trop lent et purge) ;
  `test_enrichir_stockage` rend un contenu par fichier (doublure irréaliste : 251 fichiers aux
  octets identiques).
- 16/09 — D-19 : `auth/profils.controler_code` rend un `Verdict` (ok, raison, doit_changer) et
  REFUSE tout ce qu'elle ne peut pas vérifier — schéma incomplet, profil inconnu, empreinte
  absente : avant, ces trois cas rendaient `None`, c'est-à-dire « entre ». Le compte des essais
  et le blocage tiennent dans une transaction avec `FOR UPDATE` (essais simultanés). Le code de
  PREMIÈRE ENTRÉE (`CODE_ADMIN_DEFAUT`, propre à l'installation) ne sert qu'une fois — migration
  **044** `users.code_defaut_le`, refusé si la migration manque — et l'écran (`nav/CodeAPoser.tsx`,
  posé devant l'application pour un super_admin sans code) fait poser un vrai code aussitôt ;
  reprise hors interface par `scripts/code_admin.py`. `security/tentatives.py` borne les essais
  ratés par origine (30 / 15 min, oubliés à l'entrée réussie) sans fermer la boîte partagée. La
  clé qui chiffre les codes relisibles est séparée du secret JWT (`CODE_CHIFFREMENT_CLE`), les
  anciens chiffrés restent lisibles et se réécrivent à la lecture ; lire le code d'un autre est
  journalisé. Refus techniques en 503, blocages en 429, tous dits en français. Bancs
  `test_code_admin` (40) ; `test_connexion_admin` et `test_droits_par_profil` remis sur le
  nouveau contrat.
  ⚠️ Au déploiement : appliquer la 044 AVANT de redémarrer, sinon l'entrée par le code de
  première entrée est refusée (c'est voulu) ; poser `CODE_ADMIN_DEFAUT` et `CODE_CHIFFREMENT_CLE`
  dans le `.env` du VPS.
- 16/09 — D-22 (étape 1) : `security/secrets.py` (nouveau) porte le masquage des clés — et le filtre
  est posé sur les HANDLERS, pas sur le seul logger racine : un enregistrement d'un logger enfant ne
  passe pas par les filtres du parent, donc presque rien n'était masqué. Il couvre désormais le
  message, les arguments, le message RECOLLÉ (« key=%s » + la valeur : le secret n'existe qu'une fois
  les deux réunis), la trace d'une exception, et il est reposé au démarrage (uvicorn installe ses
  handlers après l'import). Les traces Langfuse passent par le même masquage, et leur docstring ne
  promet plus « aucune PII » — l'anonymisation est coupée depuis le 31/08, c'est dit. Export de la
  console : cellules CSV inertes (`=`, `+`, `-`, `@`, caractères de contrôle — le JSON reste fidèle),
  fin bornée à l'instant du lancement, pagination par clé `(created_at, id)` au lieu d'OFFSET,
  manifeste (période, filtres, nombre de lignes) en dernière ligne CSV et dans le JSON, et un ticket
  court à usage unique pour que le navigateur écrive le fichier sans Blob géant — jamais le jeton
  dans l'URL. Bancs `test_secrets_journaux` (+8, filtre exécuté sur un logger enfant et une
  exception) et `test_echanges_admin` (+10, export exécuté par ticket et par jeton).
- 16/09 — D-23 / D-26 / D-00 : `backup.sh` prend désormais la base ET le volume des documents
  produits (Word, Excel, visuels et leurs propriétaires) ET les secrets (`.env`, `backend/secrets`,
  chiffrables) ; il écrit dans un dossier provisoire, vérifie (gzip, tar, sha256) puis publie, avec
  un manifeste (commit, migrations, comptes) — et ne purge qu'ensuite, en gardant toujours les
  derniers jeux. `restaurer.sh` (nouveau) reconstitue une copie ISOLÉE (autre projet Compose, donc
  autres volumes, autres ports) et coupe toute sortie : clés vidées dans le `.env` et dans `cles_api`,
  tâches planifiées et lecture du NAS désactivées ; il refuse de tourner sous le projet de production.
  `deploy.sh` réordonné : version → build → sauvegarde → base seule → migrations (un échec ARRÊTE la
  livraison) → schéma vérifié complet → bascule → attente de `/api/ready`. La ligne de base ne dit
  plus « la base existe donc tout est appliqué » : `migrations/attendus.tsv` donne l'objet attendu de
  chaque migration, et celle dont l'objet manque est JOUÉE. `main.py` sépare `/api/health` (liveness)
  de `/api/ready` (base, schéma complet, checkpointer durable, commit livré ; 503 sinon).
  `RECETTE-LOT1.md` : la procédure de Noa, fiche par fiche, avec le retour arrière et ce que le lot
  ne prouve pas. Banc `test_deploiement` (34, dont `backup.sh` EXÉCUTÉ contre un docker doublé).
- 16/09 — D-04 / D-07 / D-01 : `bureautique/atelier.py` — verrou par document, fiche écrite
  atomiquement (temporaire propre à chaque écrivain : deux fils se marchaient dessus), compteur
  RÉCONCILIÉ sur le contenu réel, lignée (`document_id`, `revision`, `parent_revision`, `fil`,
  `source_ref`) et `manifeste` par rendu (empreinte, blocs, images, à compléter), `nouvelle_revision`,
  `revisions`, `dernier_livrable_du_fil` (plus de tri global qui rendait le document d'une autre
  conversation), purge PAR GROUPE (un brouillon rempli vit sept jours, les images d'un rendu partent
  avec lui), quota qui REFUSE en nommant les documents au lieu d'effacer un brouillon rempli.
  `ressources/registre.py` (nouveau) retient les références de messages et de pièces jointes dans le
  volume des documents : un accord en attente les retrouve après un redéploiement — jamais leur
  contenu. `skills/trames.py` mémorise la référence choisie ET les remplacements déjà donnés pour la
  conversation : « refais-le pour Madame Martin » ne redemande plus le fichier, et un original qui a
  changé depuis le choix est dit. Le serveur donne le fil aux gestes de documents et de trames.
  Banc `test_versions_documents` (29, atelier et registre exécutés, concurrence réelle).
