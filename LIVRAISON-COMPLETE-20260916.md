# DURET — livraison complète du 16 septembre 2026

## État et périmètre

Corrections mises en place dans le code existant ; livraison préparée pour le projet Compose duret-sols. Aucun déploiement sur le VPS réel effectué. Les réglages, clés, comptes, historiques et fichiers antérieurs sont conservés ; les migrations sont additives et suivies.

Ce document remplace, pour l’état courant, les listes « à terminer » des rapports précédents. Ces derniers restent l’historique de l’audit. Le choix d’un registre JSON/SQLite protégé et persistant évite une migration inutile des références existantes ; un déploiement sur plusieurs hôtes demanderait une adaptation supplémentaire.

## Lots livrés

| Lot | Résultat |
|---|---|
| A | Précontrôle, archives vérifiées, anciennes images conservées, migrations automatiques, données comparées, retour arrière du code. |
| B | Préparation depuis une trame de l’entreprise, fidélité DOCX, images contrôlées, révisions, ateliers persistants et verrouillés, conservation et réserve disque. |
| C | Recherche reformulée, ouverture de sources autorisées, résultats partiels conservés, parcours reprenables et réconciliation du socle documentaire. |
| D | Capacités de messagerie, indicateurs, modification des brouillons, conservation MIME/pièces, reçus et validations. |
| E | Objectif, contraintes, références et résultats par fil, persistants et visibles ; reprise sans réexécution du chat. |
| F | Leçons contradictoires à vérifier, skills en brouillon, qualification liée au code exact, versions, validation et quarantaine. |
| G | Citations et empreintes des chiffres, calculs Decimal contrôlés ; observations visuelles qualifiées et à vérifier. |
| H | Baux de tâches, tickets partagés à usage unique, rôle SQL effectif, navigateur isolé, préparation atomique du nouvel index. |
| I | Suites locales, PostgreSQL réel, API réelle, images Linux, mise à jour et restauration Docker, guides VPS, Word et archives. |

## Preuves et limites

- Suite locale : 162 PASS, 0 FAIL, 3 SKIP (dépendances complètes ou bancs d’intégration séparés).
- Compléments d’exploitation après la dernière modification : 5 PASS, 0 FAIL.
- Conteneur réel, recette rapide avec anonymisation activée pour le test : 27 OK, 0 KO, 4 ignorés.
- Migrations 050–054 rejouées deux fois sur PostgreSQL ; anciennes colonnes inchangées ; 12 revendications d’une tâche, un seul gagnant ; séparation SQL de deux utilisateurs.
- APIs de travail et de skills exercées avec PostgreSQL ; génération vectorielle testée sur panne, mutation concurrente, bascule et reprise.
- Installations Docker : utilisateurs, messages, documents et sessions fictifs conservés ; readiness réelle. Restaurations dans une copie distincte, réseau interne et accès externes neutralisés.
- Audits Python et npm : aucune vulnérabilité connue signalée lors de la vérification. Les versions et empreintes sont figées dans les fichiers de dépendances.

Les fournisseurs réels (NAS/Drive, messagerie, modèles, Daytona), leurs quotas et leurs droits n’ont pas été testés avec les comptes métier. Les nouveaux scopes Gmail nécessitent éventuellement un consentement. Les chiffres et plans restent vérifiables humainement ; la fidélité aux modèles de l’entreprise doit être contrôlée sur ses fichiers réels. La destination de sauvegarde hors VPS reste un paramètre d’exploitation à renseigner.

## Détail des 28 fiches

### D-00 — Recette et préservation

Fichiers : `scripts/livrer.py`, `scripts/installer-livraison.py`, `backend/scripts/recette_usages.py`

La livraison découvre le projet existant, construit avant la coupure, contrôle ses volumes et ses secrets, puis compare les anciennes colonnes des tables protégées après migration. Les bancs d’intégration sont séparés des tests locaux. Une erreur de module interne reste un échec, jamais un succès masqué.

Vérification et portée : Installations Docker sur données fictives, readiness, historique, document et session navigateur contrôlés. Les comptes et fichiers métier réels doivent encore faire l’objet de la recette indiquée dans le guide VPS.

### D-01 — Documents conformes aux modèles de l’entreprise

Fichiers : `backend/skills/preparation_document.py`, `backend/skills/trames.py`, `backend/agents/agent1.py`, `backend/agents/router.py`

preparer_document_maison reprend la référence du fil, cherche des trames enregistrées puis des sources autorisées. Le modèle choisi et son empreinte restent associés au travail. reproduire_document inspecte la référence fournie ; le système ne choisit pas silencieusement un modèle arbitraire quand le choix est ambigu.

Vérification et portée : Banc de préparation exécuté. En recette métier, demander un document précis avec un modèle réel et comparer logo, en-tête, tableaux et zones remplacées.

### D-02 — Fidélité Word, images et révisions

Fichiers : `backend/bureautique/modele.py`, `backend/bureautique/trame.py`, `backend/bureautique/rendu.py`, `backend/bureautique/images.py`

La modification travaille sur la structure du DOCX et conserve les composants utiles du modèle. Les remplacements traversant plusieurs fragments sont contrôlés. Les médias incorporés sont récupérables ; les révisions reprennent le corps et les images dans leur propre fichier. Les formats d’images sont vérifiés par décodage, avec limite de pixels et orientation EXIF.

Vérification et portée : Bancs Word, versions, images et XML réussis. La conformité visuelle de chaque document complexe dans Microsoft Word reste une vérification métier ; aucune génération de texte ne garantit à elle seule une mise en page parfaite.

### D-03 — Ressources, propriétaires et images réutilisables

Fichiers : `backend/ressources/registre.py`, `backend/visuels/depot.py`, `backend/bureautique/images.py`, `backend/security/acces.py`

Les références persistantes permettent de retrouver les mêmes sources après redémarrage. Les médias produits restent associés à leur propriétaire ; les images générées ou extraites ne deviennent pas publiques par défaut. Une panne du registre est rendue visible. L’ouverture d’une source relit les droits applicables.

Vérification et portée : Bancs de propriétaires et de registre réussis. Une copie déjà produite et possédée par un utilisateur reste son document : retirer l’accès au fichier source n’efface pas rétroactivement ce livrable.

### D-04 — Atelier durable et écritures concurrentes

Fichiers : `backend/bureautique/atelier.py`, `backend/stockage/verrous.py`, `backend/stockage/capacite.py`

Les mutations d’un document utilisent un verrou entre processus. La limite des ateliers ouverts est vérifiée sous verrou par propriétaire. Les documents terminés n’ont plus de suppression implicite à échéance ; les brouillons remplis sont protégés. Les nouvelles écritures contrôlent une réserve disque de 128 Mio.

Vérification et portée : Bancs de concurrence, quotas, purge et conservation exécutés. Le volume doit rester monté et sauvegardé ; l’absence de purge automatique impose de surveiller sa croissance.

### D-05 — Résultats d’action et reçus exploitables

Fichiers : `backend/skills/gestion_mail.py`, `backend/skills/brouillons_distants.py`, `backend/agents/agent1.py`

Les opérations de messagerie rendent leurs identifiants distants et l’état réellement observé. Les modifications exposent les échecs et les réserves du fournisseur ; l’étape après accord ne transforme plus un résultat partiel en affirmation de réussite. Les états déjà incertains doivent être vérifiés avant une répétition.

Vérification et portée : Fournisseurs doublés en tests, dont relecture Outlook, brouillons Gmail et UID IMAP. Un délai réseau peut laisser un résultat distant incertain : la procédure prévoit la consultation de l’objet avant relance.

### D-06 — Recherche après une mémoire vide

Fichiers : `backend/skills/recherche_sources.py`, `backend/agents/agent1.py`

La recherche reformule les demandes, conserve les résultats partiels et ouvre un petit nombre de sources réellement autorisées pour en lire le contenu. Le secours documentaire et mail ne se limite plus au seul index mémorisé. Le résultat distingue absence, accès refusé, parcours incomplet et indisponibilité.

Vérification et portée : Bancs de recherche et de lecture réelle des extraits réussis. Les délais bornent le travail ; un corpus entier ne peut pas être parcouru dans chaque question.

### D-07 — Références fiables entre processus

Fichiers : `backend/ressources/registre.py`, `backend/stockage/verrous.py`

Le registre JSON est relu sous verrou quand le fichier a changé. Les écritures sont atomiques, synchronisées sur disque, privées et sans éviction arbitraire des références anciennes. Le cache utilise les métadonnées du fichier pour éviter de reparcourir tout le JSON quand il est inchangé.

Vérification et portée : 150 écritures concurrentes, redémarrage, cache et erreur disque testés. Le choix JSON/SQLite conserve les références existantes ; il suppose un volume partagé localement. Un déploiement sur plusieurs hôtes exigerait un entrepôt commun supplémentaire.

### D-08 — Remplacement sûr du contenu indexé

Fichiers : `backend/vectorstore/generation.py`, `backend/vectorstore/client.py`, `backend/vectorstore/worker.py`

Les nouveaux vecteurs sont préparés avec le modèle et l’empreinte du contenu. Le système détecte un document changé pendant le calcul et le prépare de nouveau. La transaction finale vérifie la couverture actuelle avant d’effectuer la bascule de l’index et de son modèle.

Vérification et portée : Test PostgreSQL avec modification concurrente de contenu et panne fournisseur. Aucun basculement n’est validé sur un lot incomplet.

### D-09 — Droits de lecture et périmètre des boîtes

Fichiers : `backend/security/acces.py`, `backend/security/lecteur.py`, `backend/skills/recherche_sources.py`

Les recherches conservent le périmètre utilisateur et les boîtes accessibles avant la sélection des résultats. Les outils d’ouverture et les calculs sourcés réévaluent l’accès aux sources. Le rôle SQL de lecture ne peut pas contourner la séparation des utilisateurs.

Vérification et portée : Tests d’accès et RLS réels réussis. Les autorisations NAS/Drive restent celles effectivement attribuées dans ces services ; elles doivent être vérifiées avec les comptes de l’entreprise.

### D-10 — Capacités de messagerie et brouillons distants

Fichiers : `backend/skills/gestion_mail.py`, `backend/skills/brouillons_distants.py`, `backend/mail/google_perso.py`

Les outils couvrent les capacités exposées, lu/non lu, suivi et catégories selon le fournisseur, ainsi que l’édition d’un brouillon existant. Gmail conserve le MIME et ses pièces ; Outlook utilise l’ETag avec If-Match et relit le brouillon ; IMAP exige UIDPLUS pour un remplacement ciblé sans expurger les autres messages. Le contrôle UIDVALIDITY s’applique quand le reçu le fournit.

Vérification et portée : Gmail, Outlook et IMAP testés avec réponses simulées. Les nouveaux scopes Gmail demandent un consentement supplémentaire du titulaire ; aucune mise à jour ne peut l’accorder à sa place.

### D-11 — Approbations, pièces jointes et non-duplication

Fichiers : `backend/mail/attaches.py`, `backend/routers/chat.py`, `backend/agents/agent1.py`

Les pièces présentées pour accord sont copiées dans une révision figée et vérifiées par empreinte avant utilisation. Les requêtes de chat utilisent un identifiant persistant, un propriétaire et un signe de vie. Une reprise de page lit le résultat enregistré au lieu de répéter aveuglément une action externe.

Vérification et portée : Bancs de figement, réservations concurrentes et API réelle réussis. Gmail ne fournit pas de transaction globale entre la relecture du MIME et son remplacement ; l’interface doit conserver les réserves sur les conflits distants.

### D-12 — Chiffres calculés depuis des sources vérifiables

Fichiers : `backend/skills/chiffres_sources.py`

Les valeurs extraites gardent la référence, l’empreinte du document, la ligne, la citation et l’unité observée. Les calculs utilisent Decimal et une expression limitée aux références c1…c12 et aux quatre opérations. Avant le calcul, droits et empreinte sont relus pour détecter une source modifiée.

Vérification et portée : Bancs de provenance et de calcul exécutés. Le système ne déduit pas automatiquement une conversion d’unité ni la signification d’un nombre : une date ou une référence peut aussi contenir des chiffres.

### D-13 — Contraintes et progression conservées par fil

Fichiers : `backend/ressources/travail.py`, `backend/skills/travail.py`, `backend/routers/chat.py`, `frontend/components/chat/SuiviTravail.tsx`

Le travail conserve l’objectif, les contraintes explicites, les références, les étapes et les résultats dans SQLite sur le volume persistant. Le contexte de travail est réinjecté séparément des extraits documentaires. Le volet Travail en cours rend cet état consultable ; l’API vérifie le propriétaire du fil.

Vérification et portée : Reprise entre processus et séquence de 40 tours testées ; accès d’un autre utilisateur, même administrateur, refusé sur l’endpoint réservé au propriétaire. Les anciens historiques restent conservés ; les nouveaux états structurés se construisent au fil des échanges, sans prétendre reconstruire parfaitement tous les anciens fils.

### D-14 — Leçons contrôlables et contradictions

Fichiers : `backend/learning/lecons.py`, `frontend/components/learning/LeconsApprises.tsx`, `backend/routers/skills.py`

Une leçon n’est renforcée comme doublon que si la conduite normalisée correspond. Une conduite différente pour une situation presque identique devient un brouillon à vérifier. Les leçons disposent de leur état, de leur confiance et d’actions de validation/retrait ; une contradiction n’est plus silencieusement consolidée.

Vérification et portée : Bancs de duplication, inversion et validation exécutés. Les leçons retirées restent en base pour la traçabilité ; elles ne sont plus utilisées comme consignes actives.

### D-15 — Création, qualification et versions des skills

Fichiers : `backend/agents/agent3.py`, `backend/learning/qualification.py`, `backend/learning/skills.py`, `backend/routers/skills.py`

Un skill généré commence désactivé. La qualification exige des cas fictifs, un contrôle AST et l’exécuteur Daytona configuré. Le résultat de qualification est attaché à l’empreinte exacte du code ; une modification invalide l’ancienne preuve. La promotion exige cette preuve et une validation humaine. Les anciennes versions sont archivées et restaurables en brouillon ; trois erreurs déterministes mettent le skill à l’écart.

Vérification et portée : API réelle avec PostgreSQL : promotion sans preuve refusée, preuve valide acceptée, preuve ancienne refusée, restauration et quarantaine testées. L’exécution chez Daytona nécessite ses identifiants réels : en leur absence, la qualification refuse de déclarer le code sûr.

### D-16 — Délais, reprises et fluidité

Fichiers : `backend/agents/agent1.py`, `backend/skills/recherche_sources.py`, `backend/stockage/processus.py`

Le budget de tour borne le travail et les lecteurs de secours reçoivent une enveloppe compatible. Les résultats déjà acquis sont conservés si une autre lecture échoue. Les verrous interprocessus évitent deux travaux simultanés sur le même fil ; la reprise peut retrouver le résultat enregistré.

Vérification et portée : Bancs de délai, vitesse, résultat partiel et reprise exécutés. Les fournisseurs peuvent rester lents ou indisponibles ; les limites sont annoncées plutôt que compensées par une boucle sans borne.

### D-17 — Changement de modèle sans perdre la recherche

Fichiers : `backend/vectorstore/generation.py`, `backend/vectorstore/embeddings.py`, `backend/vectorstore/worker.py`, `backend/database/migrations/054_generation_vectorielle.sql`

Le choix d’un nouveau modèle prépare une génération séparée. L’ancien modèle reste actif pour les requêtes et les workers jusqu’à la bascule transactionnelle. Les anciens vecteurs sont refusés après celle-ci ; les lots déjà préparés se réutilisent après un échec. Un verrou de préparation empêche deux reconstructions concurrentes.

Vérification et portée : PostgreSQL réel : panne sans perte de l’index, rattrapage d’une modification, bascule atomique, ancien vecteur refusé et reprise sans recalcul. La progression affichée reste liée au processus courant ; après redémarrage, relancer la préparation reprend les données persistées.

### D-18 — Tâches longues et séparation des processus

Fichiers : `backend/tasks/worker.py`, `backend/database/migrations/050_baux_taches.sql`, `backend/agents/runtime.py`

Les exécutions de tâches portent un bail et un propriétaire renouvelés pendant le travail. Une fin tardive d’un ancien propriétaire ne peut plus écraser l’exécution courante. Un travail expiré dont l’effet externe est incertain n’est pas rejoué automatiquement. Les rôles API et fond restent séparables sans perdre les tickets partagés.

Vérification et portée : Douze revendications concurrentes sur PostgreSQL : une seule exécution. La recette Docker utilise le rôle API pour empêcher les appels métier ; le déclenchement avec les vrais connecteurs reste à contrôler sur le VPS.

### D-19 — Secrets et authentification entre processus

Fichiers : `backend/security/coffre.py`, `backend/security/jetons_ephemeres.py`, `backend/security/tentatives.py`, `backend/routers/auth.py`

Les refresh tokens restent chiffrés, les anciennes valeurs lisibles sont migrables et les erreurs de clé sont explicites. Les tickets OAuth/WebSocket sont stockés sous empreinte dans SQLite avec expiration et consommation atomique. Les limitations de tentatives protègent les demandes et leur validation. La livraison ne remplace aucune clé existante.

Vérification et portée : Bancs du coffre, consommation unique et API exécutés. Aucune rotation de clé dédiée n’est imposée ; en cas de rotation volontaire ultérieure, conserver la capacité de lire les anciens secrets.

### D-20 — Isolation SQL effective

Fichiers : `backend/security/lecteur.py`, `backend/database/migrations/051_rls_connexions_utilisateur.sql`

Les lectures utilisateur emploient SET LOCAL ROLE avec un rôle NOLOGIN, non superutilisateur et sans BYPASSRLS. Les paramètres d’identité sont limités à la transaction ; ils ne restent pas attachés à la connexion remise au pool.

Vérification et portée : Test PostgreSQL avec deux utilisateurs : les fils de l’autre utilisateur sont invisibles et le rôle de la connexion est réinitialisé après transaction. Les tables techniques de préparation d’index ne sont pas accordées au lecteur utilisateur.

### D-21 — Navigateur et exécution des actions

Fichiers : `browser-worker/worker.py`, `browser-worker/browser_agent.py`, `docker-compose.yml`, `docker-compose.prod.yml`

Le navigateur reçoit une liste limitée de réglages utiles et un secret interne. Il ne monte plus tout le dossier de secrets et ne reçoit pas de credentials PostgreSQL. Les prises de tâche sont atomiques, les retours sont rattachés au propriétaire et les actions d’écriture passent par les validations ; le garde-fou de lecture seule couvre aussi les outils ajoutés tardivement.

Vérification et portée : Dépendance browser-use et outils réels vérifiés, image construite et sessions migrées en permissions privées. Une session fournisseur et un parcours réel avec modèle nécessitent les comptes du VPS.

### D-22 — Sorties, conservation et exploitation

Fichiers : `backend/security/secrets.py`, `backend/security/cleanup.py`, `backend/stockage/capacite.py`, `backup.sh`

Les secrets restent exclus des archives de livraison et des contextes de build. Les exports et messages techniques conservent leur masquage ; les documents finis ne sont plus supprimés par une durée implicite. La readiness expose l’état de l’atelier et sa réserve disque. Les copies privées de configuration servent exclusivement au retour arrière.

Vérification et portée : Audits des dépendances Python/npm sans vulnérabilité connue signalée au moment du contrôle. Les archives finales sont contrôlées fichier par fichier. Les journaux privés d’installation ne doivent pas être joints à un ticket public.

### D-23 — Sauvegardes cohérentes et restauration

Fichiers : `backup.sh`, `restaurer.sh`, `scripts/verrou_backup.py`

Une sauvegarde prend ensemble PostgreSQL, documents, sessions et secrets, publie après vérification des empreintes et garde une rétention minimale. Les sauvegardes du même projet sont sérialisées ; les producteurs actifs sont arrêtés pour la copie puis repris même si le dump échoue. Un échec de copie distante renvoie un code d’échec en conservant le jeu local. La restauration travaille dans un autre projet, adapte le schéma et attend une readiness réelle.

Vérification et portée : Sauvegarde quotidienne réelle exécutée ; arrêt/reprise sur succès et panne testés. Restauration Docker isolée des deux projets avec utilisateur, message et fichier antérieurs contrôlés. La destination de copie hors VPS doit être choisie par l’exploitant ; aucune destination réelle n’a été inventée.

### D-24 — Lecture de plans et preuves visuelles

Fichiers : `backend/agents/agent2.py`, `backend/agents/preuves_visuelles.py`

Les observations visuelles distinguent ce qui est lu, estimé ou non mesurable. Elles gardent citation, page et zone normalisée lorsqu’elles existent, avec contrôle de structure et empreinte de l’analyse. Les valeurs restent à vérifier humainement avant une utilisation engageante.

Vérification et portée : Banc de preuves visuelles et OCR Docker réussis. Une citation produite par le modèle n’est pas une certification de la cote sur le plan ; aucune promesse de métrés automatiques exacts sans échelle et validation.

### D-25 — Tests représentatifs et résultats honnêtes

Fichiers : `backend/scripts/recette_usages.py`, `backend/scripts/test_e2e.py`

Le lanceur filtre l’environnement, utilise un dossier temporaire sans .env et laisse les bancs de fournisseurs à une exécution explicite séparée. Les fixtures OAuth utilisent le vrai stockage SQLite isolé. Les tests de sauvegarde utilisent un projet fictif unique pour ne pas se gêner entre projets.

Vérification et portée : Duret : 162 PASS, 0 FAIL, 3 SKIP. Symbiose : 155 PASS, 0 FAIL, 3 SKIP. En Docker : 27 OK, 0 KO, 4 contrôles ignorés en mode rapide par projet. Les suites locales ne constituent pas une preuve d’accès aux comptes réels.

### D-26 — Livraison, readiness et retour arrière

Fichiers : `scripts/installer-livraison.py`, `scripts/livrer.py`, `mettre-a-jour.sh`, `backend/main.py`

L’archive est contrôlée par manifeste SHA-256, extraite dans un dossier privé et reliée aux volumes existants. La construction séquentielle réduit le pic de mémoire. La livraison garde les images exactes précédentes sous des étiquettes Docker réservées et prépare RETOUR-ARRIERE.txt ; en échec, elle tente de reprendre l’ancien code sans remettre un ancien dump sur les données récentes. Les anciennes commandes d’exploitation et leurs bibliothèques sont conservées et mises à jour ensemble.

Vérification et portée : Mises à jour Linux/Docker exécutées sur les deux projets. Le précontrôle refuse overlays supplémentaires, changement de volumes, base incohérente ou service actif non repris. Ces refus protègent les topologies personnalisées ; ils ne doivent pas être contournés.

### D-27 — NAS : parcours reprenable, noms et droits

Fichiers : `backend/skills/recherche_nas_contenu.py`, `backend/nas/acces.py`, `backend/nas/tri.py`

Le parcours garde un curseur SQLite, un propriétaire et un verrou. Les dossiers sont parcourus progressivement avec limites de temps et de fichiers. Une ouverture exacte qui échoue ne déclenche pas une recherche globale d’un homonyme ; les alias sont résolus dans le dossier parent avec le même nom. Les copies identiques restent détectées par leur contenu.

Vérification et portée : Bancs NAS de reprise, budget et recherche réussis. L’arborescence et les ACL du NAS de production ne sont pas parcourues dans cette recette fictive ; tester un fichier connu peu courant et un fichier réellement interdit après installation.

## Déployer

Suivre `DEPLOIEMENT-20260916.md`. Les commandes de migration sont intégrées à l’installateur ; aucune réinitialisation SQL à lancer.


## Complément documents longs

Le correctif issu de l’export Langfuse du 16 septembre est détaillé dans `DOCUMENTS-DURABLES-20260916.md`. Les archives du Bureau sont renouvelées. Voir `DEPLOIEMENT-DOCUMENTS-20260916.md` pour les contrôles supplémentaires ; aucune nouvelle clé ni migration PostgreSQL supplémentaire.
