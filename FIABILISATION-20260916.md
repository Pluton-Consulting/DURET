# Fiabilisation — Duret & Sols

## Duret & Sols

Projet vérifié : /Users/noa/benit-dev/infra IA/DURET-audit. Branche audit/duret. Nom du paquet frontend : duret-sols-frontend.

### Résultats de vérification

Suite complète : 153 scripts, dont 148 PASS, 3 SKIP et 2 dépassements du plafond de 45 secondes au premier passage. Les deux scripts concernés (enrichissement et tri NAS) passent ensuite lors du contrôle ciblé. Bilan après ces reprises : 150 scripts réussis, 3 ignorés. Les résultats bruts et les reprises sont conservés séparément.

Base PostgreSQL/pgvector temporaire : 49 fichiers de migration, incluant 049 ; démarrage réel de l’API, schéma et routes vérifiés. Modèles et services métier remplacés ou désactivés. Build Next.js 15.5.25 et TypeScript réussi ; audit npm sans vulnérabilité signalée. Dépendances Python installées depuis le verrou commun et auditées.

### 1. Compatibilité réelle de l’anonymisation

Fiches concernées : D-20, D-26.

Emplacements : backend/requirements.txt ; backend/requirements.lock ; backend/Dockerfile.

Défaut : L’installation non verrouillée associait NumPy 2 à spaCy 3.7 / Thinc 8.2. L’import échouait avec « numpy.dtype size changed », rendant le démarrage ou l’anonymisation défaillant.

Correction : NumPy est borné à la branche 1.x (1.26.4 résolu). Les dépendances transitives sont fixées avec leurs empreintes dans requirements.lock ; Docker installe ce fichier avec --require-hashes.

Vérification et limites : Installation complète réussie, modèle français fr_core_news_md 3.7.0 chargé et banc d’anonymisation exécuté des deux côtés. L’activation effective du réglage d’anonymisation et les données envoyées aux fournisseurs restent à vérifier sur le serveur.

### 2. Dépendances exposées corrigées

Fiches concernées : D-20, D-26.

Emplacements : backend/requirements.txt ; backend/requirements.lock ; frontend/package.json ; frontend/package-lock.json.

Défaut : Les audits de dépendances ont signalé des vulnérabilités connues dans Starlette, Next.js, PostCSS et Sharp. Next 15.5.23 précédait notamment un correctif de l’optimisation d’images AVIF.

Correction : FastAPI 0.141.1 et Starlette 1.6.0 ; Next 15.5.25 ; PostCSS 8.5.28 ; Sharp 0.35.4. Mise à jour des fichiers verrouillés et vérification de compatibilité de l’API et des interfaces.

Vérification et limites : npm audit ne signale aucune vulnérabilité sur chacun des deux frontends ; pip-audit ne signale aucune vulnérabilité connue dans le verrouillage Python commun. Deux builds Next/TypeScript réussis. Redimensionnement et encodage AVIF Sharp exécutés. Ce résultat décrit les avis connus au 16 septembre 2026, pas une preuve d’absence de toute faille.

### 3. Démarrage et bascule du code

Fiches concernées : D-18, D-23, D-26.

Emplacements : backend/main.py ; backend/database/connection.py ; backend/agents/checkpointer.py ; docker-compose.yml ; docker-compose.dev.yml ; deploy.sh.

Défaut : Les workers pouvaient démarrer avant les caches de clés et réglages. Une erreur de cache pouvait empêcher le suivant de se charger. Le montage complet du backend exposait immédiatement le nouveau code aux anciens conteneurs, avant la fin des migrations.

Correction : Chargements indépendants des caches avant les workers. Readiness exigeant base, schéma, mémoire durable, graphe utilisable et stockage accessible en écriture. Refus du repli en mémoire volatile en production lorsque le checkpointer PostgreSQL manque. Code embarqué dans l’image de production ; montage du code réservé au développement. Attente de PostgreSQL bornée à 180 secondes ; fermeture du pool à l’arrêt.

Vérification et limites : Démarrage complet de l’API et readiness testés avec PostgreSQL réel. YAML analysé et scripts shell vérifiés. Aucun Docker installé ici : construction des images, démarrage des workers et bascule réelle restent à essayer. Un échec après la bascule nécessite un retour arrière explicite ; il n’est pas automatique.

### 4. Références utilisables entre processus

Fiches concernées : D-07.

Emplacements : backend/stockage/verrous.py ; backend/ressources/registre.py.

Défaut : Deux processus pouvaient charger des copies divergentes du registre et écraser leurs ajouts mutuels ; un cache ancien ne voyait pas la référence créée ailleurs. Une panne disque n’était qu’un avertissement.

Correction : Verrou réentrant entre threads et processus sur volume local, relecture sous verrou, écriture atomique et erreur explicite si la persistance échoue. Le fichier corrompu n’est plus remplacé par un registre vide. Retrait de l’éviction automatique au seuil de 4 000 références.

Vérification et limites : 150 écritures depuis six processus : aucun ajout perdu, référence ancienne toujours lisible. Une panne disque simulée conserve le registre précédent et lève une erreur. Le registre reste un fichier JSON relu à chaque opération : coût croissant avec le volume, à surveiller avant migration transactionnelle en base.

### 5. Documents modifiés simultanément

Fiches concernées : D-04.

Emplacements : backend/bureautique/atelier.py ; backend/stockage/verrous.py.

Défaut : Le verrou local à un processus ne protégeait pas les versements effectués par plusieurs workers. Compteur, contenu et rendu pouvaient diverger.

Correction : Verrou interprocessus autour des lectures et mutations sensibles ; rendu vers un fichier temporaire puis remplacement atomique. Une révision terminée restitue son fichier existant et ne le régénère plus sous la même identité.

Vérification et limites : 30 versements concurrents conservés ; contrôle de l’empreinte et des octets du rendu lors d’une seconde demande. Le stockage reste sur volume local ; ce test ne valide pas un partage réseau distribué ni tous les scénarios de purge à l’échéance.

### 6. Vraies révisions et images autonomes

Fiches concernées : D-01, D-04.

Emplacements : backend/bureautique/atelier.py : nouvelle_revision ; terminer.

Défaut : Une nouvelle révision pouvait perdre le corps existant ou garder des références aux images de la précédente. La suppression de cette dernière cassait alors le nouveau document.

Correction : Copie du contenu et des images, réécriture récursive des chemins de médias, conservation de la lignée. Nettoyage de la nouvelle révision si sa préparation échoue.

Vérification et limites : Le banc supprime la révision d’origine, vérifie l’existence de l’image copiée et produit ensuite le nouveau Word. Les durées de conservation demeurent limitées : 24 heures pour les rendus ordinaires, sept jours pour les brouillons remplis.

### 7. Réutilisation des images de Word

Fiches concernées : D-02, D-03.

Emplacements : backend/bureautique/images.py : image_du_docx ; preparer.

Défaut : Un logo présent dans le Word de référence était inutilisable comme image. Plusieurs médias pouvaient aussi conduire à choisir arbitrairement la mauvaise illustration.

Correction : Lecture des relations internes du DOCX et extraction des images incorporées ; sélection de l’en-tête, du pied ou du corps selon le besoin. Plusieurs candidats imposent une sélection explicite #image=N. Refus des chemins d’image déjà rangés dans un autre document.

Vérification et limites : DOCX réel avec logo : extraction vérifiée par comparaison des octets. Deux images : ambiguïté refusée puis choix explicite vérifié. Certains anciens formats Word/VML ou médias vectoriels exigent encore une conversion ; aucune promesse de reprise visuelle universelle.

### 8. Pièces jointes fixées avant accord

Fiches concernées : D-09, D-10, D-11.

Emplacements : backend/mail/instantanes.py ; backend/mail/skills.py ; backend/agents/agent1.py.

Défaut : Une validation pouvait désigner un fichier ensuite modifié ou purgé. L’accord portait alors sur un nom, sans garantir les octets réellement envoyés.

Correction : Résolution avec identité et droits, copie dans l’atelier avant demande d’accord, boîte fixée, nom et SHA-256 inclus dans les arguments approuvés. Contrôle des octets avant l’envoi ; refus si la pièce diffère. Conservation des copies d’accord pendant sept jours.

Vérification et limites : Copie réelle testée : source supprimée, contenu et nom approuvés conservés. Modification des octets : refus avant envoi. Les accords déjà créés sans manifeste restent compatibles. Signature ajoutée par la messagerie et permissions ultérieurement modifiées sur la source originale ne sont pas entièrement figées/requalifiées par ce mécanisme.

### 9. Recherche directe après mémoire vide

Fiches concernées : D-06, D-07, D-08.

Emplacements : backend/skills/recherche_sources.py ; backend/skills/documents.py.

Défaut : Une mémoire vide pouvait produire une réponse d’absence sans tenter les sources disponibles, alors que le document ou le message existait encore à distance.

Correction : Appel de l’exécuteur habituel avec l’identité de l’utilisateur pour interroger nas_chercher (NAS) et/ou lire_mails. Droits, activation des skills et validation totale restent applicables. Délai de 15 secondes par source ; opt-out sources_directes=false ; filtre de types et pagination respectés.

Vérification et limites : Banc de contrat : identité, choix des sources, filtre email seul et opt-out vérifiés. La recherche de stockage porte sur les noms ; le modèle doit ouvrir les résultats. Pas d’exhaustivité sur toutes les boîtes ni tous les contenus. Un fournisseur indisponible ne prouve pas une absence.

### 10. Reprise du chat sans travail dupliqué

Fiches concernées : D-13.

Emplacements : backend/agents/requetes.py ; backend/routers/chat.py ; frontend/components/chat/ChatWindow.tsx ; backend/database/migrations/049_requetes_signe_de_vie.sql.

Défaut : Le résultat pouvait se perdre à la reconnexion ; une demande abandonnée restait en cours ; les sondages répétaient le POST, les pièces ou les vérifications de quota.

Correction : Route GET /api/chat/demandes/{request_id} authentifiée ; relecture des demandes existantes avant contrôle de quota pour un nouveau tour ; propriétaire de traitement et signe de vie toutes les 15 secondes. Une demande inactive depuis 120 secondes est marquée interrompue lors de sa consultation. Aucun rejeu automatique d’un effet potentiel.

Vérification et limites : API réelle : un seul appel du runtime pour deux POST identiques, résultat et deux messages d’historique récupérés, demande inconnue en 404, interruption ancienne détectée, signe de vie actif après 16 secondes. Le runtime LLM est doublé dans ce test ; pas de coupure WebSocket navigateur réelle. Les tickets WebSocket restent en mémoire : conserver un seul processus API avant une évolution de cette authentification.

### 11. Budget de temps réellement appliqué

Fiches concernées : D-16.

Emplacements : backend/llm/budget.py ; backend/llm/router.py ; backend/agents/runtime.py ; backend/agents/router.py ; backend/config.py.

Défaut : Le module de budget existait mais n’encadrait pas réellement le tour complet. Délais de modèles, attente de concurrence et nouvelles tentatives s’additionnaient.

Correction : Propagation par contexte ; enveloppe totale de 600 secondes par défaut (DEMANDE_DELAI_S). Délais des modèles et des pauses bornés par le temps restant. Annulation d’une action approuvée : effet inconnu à réconcilier. Apprentissage de fond lancé avec un contexte indépendant.

Vérification et limites : Un vrai appel asynchrone de trois secondes est interrompu par un budget d’une seconde. Un délai ne peut pas annuler des octets déjà envoyés à un fournisseur ou arrêter de force un thread natif : vérifier le reçu avant une relance.

### 12. Apprentissage plus sélectif

Fiches concernées : D-14.

Emplacements : backend/learning/lecons.py ; backend/routers/learning.py ; frontend/components/learning/LeconsApprises.tsx.

Défaut : Type, preuve et confiance pouvaient être perdus ou une confiance invalide faire échouer la lecture. Une panne d’outil ou un effet ambigu pouvait servir de base à une mauvaise leçon.

Correction : Conservation du type et de la preuve ; confiance bornée et valeur de repli 0,6. Filtrage des échecs, refus, attentes et effets inconnus avant apprentissage. Exposition des champs dans l’API et l’écran des leçons.

Vérification et limites : Valeur de confiance invalide et exclusions d’apprentissage testées ; route et build de l’écran validés. L’écran existait déjà : cette correction l’enrichit. La confiance est une estimation ; ce mécanisme ne constitue pas une validation autonome complète des skills appris.

### 13. Secrets et reprise du chiffrement

Fiches concernées : D-20, D-22.

Emplacements : backend/security/coffre.py ; backend/mail/google_perso.py ; backend/.dockerignore.

Défaut : Un jeton lisible avec l’ancienne clé de repli pouvait être considéré comme déjà à jour. Les secrets du dossier backend risquaient aussi d’entrer dans les couches de l’image.

Correction : Détection du chiffrement encore fondé sur la clé de repli pour re-chiffrer avec la clé principale du bon usage. Exclusion des secrets, fichiers .env et environnements virtuels du contexte Docker.

Vérification et limites : Bancs de chiffrement et de masquage conservés ; configuration d’exclusion inspectée. La rotation arbitraire d’une clé dédiée exige toujours de conserver les anciennes clés utiles ; ce n’est pas un trousseau général de rotation.

### 14. Recette fidèle à ce qu’elle observe

Fiches concernées : D-00, D-25, D-26.

Emplacements : backend/scripts/test_fiabilisation.py ; backend/scripts/test_e2e.py ; RECETTE-LOT1.md.

Défaut : Le banc exécuté par docker exec inspectait une variable Python locale pour décider si le worker de l’API tournait : il ne pouvait pas observer un autre processus. Des résultats anciens pouvaient aussi être lus comme une validation des dernières modifications.

Correction : Contrôle non observable explicitement ignoré avec consigne de consulter le processus de fond ; nouveaux tests de concurrence, révision, médias, budget, pièces et panne disque. Documentation de la migration 049, des dépendances et de la bascule.

Vérification et limites : Le mode e2e rapide donne 26 OK, 1 KO (Tesseract absent de l’hôte), 4 ignorés pour chaque projet. L’anonymisation active passe. L’erreur OCR est conservée dans les preuves ; elle n’est pas reclassée artificiellement en réussite.

### 15. Séparation des deux projets

Fiches concernées : D-07, D-18.

Emplacements : backend/ressources/registre.py ; backend/visuels/depot.py ; backend/agents/requetes.py ; modules communs et connecteurs.

Défaut : Le socle devait rester cohérent sans recopier le connecteur ou les chemins propres à l’autre entreprise. Un chemin de registre par défaut de Duret subsistait dans Symbiose ; les visuels de Duret utilisaient encore le dossier par défaut de Symbiose.

Correction : Comparaison des modules partagés, conservation de NAS pour Duret et Drive pour Symbiose. Dans Symbiose, correction du registre par défaut vers /tmp/symbiose-documents et du nom de journal correspondant. Dans Duret, correction du dépôt des visuels vers /tmp/duret-documents. Un banc compare les trois chemins par défaut (registre, atelier, visuels).

Vérification et limites : Modules fonctionnels communs comparés ; différences restantes examinées (commentaires de fiches et connecteurs). Cohérence des trois chemins de stockage vérifiée. En production, définir explicitement DOCUMENTS_DIR sur le volume dédié de chaque projet.

### Déploiement et recette propres à ce projet

1. Depuis le worktree /Users/noa/benit-dev/infra IA/DURET-audit, examiner git status --short et les différences. Inclure les fichiers nouveaux, notamment requirements.lock, migration 049, mail/instantanes.py, skills/recherche_sources.py et stockage/. Le nom de branche seul ne suffit pas à livrer les modifications non enregistrées.

2. Sur le serveur correspondant à Duret & Sols, après livraison du code complet et conservation des clés et volumes, utiliser le deploy.sh existant depuis le dossier de ce projet. Il construit les images, sauvegarde, applique les migrations, vérifie le schéma, puis bascule et contrôle /api/ready. La copie d’environnement et les données métier ne doivent pas être remplacées par celles des essais locaux.

3. Exiger /api/ready prêt puis tester une conversation simple, son rechargement et une pièce jointe. Vérifier également le processus de fond dans ses propres journaux. Si le contrôle échoue après la bascule, suivre la procédure de retour arrière ; aucune restauration automatique n’a été prouvée.

4. Prendre un document métier de référence contenant logo, tableaux et en-têtes, demander un remplacement puis une révision ; comparer le Word final visuellement. Rechercher un document connu seulement dans le NAS, ouvrir son contenu et utiliser une image autorisée.

5. Sur une boîte d’essai, créer et modifier un brouillon avec pièce jointe, approuver un envoi puis vérifier chez le fournisseur qu’un seul message existe. Vérifier une réponse perdue, les refus de droits et le retrait d’accès à une source.

6. Tester l’OCR dans le conteneur construit (Tesseract et langue fra), la restauration Docker isolée, les clés et le bac Daytona distant. Ces étapes nécessitent l’environnement réel ; elles n’ont pas été exécutées dans cette session.

### Points qui restent ouverts

Les fiches annonçant « étape 1 » ou « lot suivant » restent partielles : registre unifié en base et droits des documents dérivés ; recherche réellement exhaustive et réconciliation des sources ; reçus fournisseur pour tous les effets ; validation et promotion mesurées des skills appris ; générations de vecteurs et baux des travaux longs. Les contrôles d’accès historiques des visuels sans propriétaire exigent une requalification sur les données réelles.

Conserver un seul processus API tant que les tickets WebSocket et états OAuth restent locaux au processus. Surveiller la taille du registre JSON et l’espace du volume. Les références ne sont plus évincées automatiquement ; la rétention des pièces d’accord est de sept jours. La purge et la création sous forte concurrence à l’échéance demandent une recette supplémentaire.
