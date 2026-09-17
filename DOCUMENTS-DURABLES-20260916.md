# Documents longs et métrés — correctifs complémentaires du 16 septembre 2026

## État et portée

Les correctifs sont appliqués au code local de DURET et SYMBIOSE. Ils remplacent les limitations reproduites après l’export Langfuse du 16 septembre. Aucun VPS de production n’a été modifié. Les archives de livraison sont renouvelées : utiliser les nouvelles archives et leur nouveau SHA256SUMS ensemble.

Le mécanisme de rédaction est général : rapports, études, réponses à consultation, dossiers de présentation, mémoires techniques et autres documents composés à partir de plusieurs pièces. Les titres, critères et contraintes proviennent de la demande et des sources. Aucun plan de mémoire technique n’est imposé à tous les usages. La génération d’images Nano Banana reste propre à SYMBIOSE ; DURET bénéficie de la lecture des images et de leur incorporation dans les documents.

## 1. DURET — ce qui change

Application : `DURET-audit`, projet Compose `duret-sols`.

### Pièces jointes et lecture complète

`backend/routers/chat.py` conserve l’original de chaque pièce dans le volume documentaire existant, avec son propriétaire. Le lecteur `backend/bureautique/lecture_integrale.py` parcourt les pages textuelles d’un PDF, les paragraphes, tableaux et en-têtes d’un Word, et toutes les feuilles d’un Excel. Les cellules portent leurs coordonnées ; une formule sans résultat calculé est signalée. Les limites explicites de sécurité arrêtent les fichiers excessifs ; aucun aperçu tronqué n’est présenté comme une lecture intégrale.

`backend/ressources/dossiers.py` conserve le texte complet dans `dossiers.sqlite3`, dans le répertoire persistant `DOCUMENTS_DIR`. Les sources et étapes sont liées au compte et à la conversation. Le découpage en fragments permet de lire les pièces entièrement sans les placer toutes dans un seul prompt. Les citations renvoient à une source et à un fragment. Les anciennes versions référencées par une rédaction restent consultables par leur identifiant.

`backend/agents/agent1.py` montre au modèle l’index du dossier en dehors du plafond de 6 000 caractères, puis un aperçu équilibré. Le corps complet reste disponible par les outils de lecture. Les avertissements sur les pièces non prises en charge et les instructions du tableau joint restent dans le contexte. Les pages de lecture de 1 600 caractères tiennent dans les résultats d’outils ; la suite est indiquée par un curseur de fragment et de position.

`backend/nas/acces.py` enregistre également la lecture complète d’un fichier ouvert sur le NAS. Si cette préparation échoue, la consultation et sa carte restent disponibles, avec un avertissement explicite. `ajouter_source_dossier` permet de reprendre la préparation depuis la référence autorisée. Les droits d’accès et l’empreinte des sources distantes sont revérifiés avant une rédaction ; un changement de fichier impose de sélectionner sa version actuelle.

### Création d’un document neuf

`backend/skills/documents_dossier.py` fournit `composer_document_dossier` : analyse de chaque fragment, extraction de faits avec citations présentes dans le texte, plan adapté à la demande, rédaction par rubrique, relecture de chaque rubrique, contrôle global et vérification du fichier final. Les informations d’un ancien chantier sont distinguées des faits stables de l’entreprise. Une donnée absente doit être signalée, pas inventée.

La demande originale arrive directement du serveur, avec les contraintes actives et les dernières demandes utilisateur. Une création Word/PDF choisie via l’ancien outil est redirigée vers ce parcours lorsque le dossier joint est long ou comporte plusieurs pièces. L’outil s’utilise aussi explicitement avec les sources sélectionnées, y compris des fichiers retrouvés après le premier message.

Chaque étape validée est sauvegardée. Un contrôle final défavorable prépare une correction ; un dépassement de pages prépare une réduction du texte et un nouveau rendu. Les rubriques restent présentes. Les essais sont bornés : le système signale un blocage persistant plutôt que livrer un document déclaré conforme sans contrôle.

`backend/bureautique/document_modele.py` prépare une copie de présentation du Word original : styles, marges, en-têtes, pieds de page et logos. Il retire le corps de l’ancien projet et ses données incorporées inutilisées. L’héritage des en-têtes et pieds entre sections est matérialisé avant de remplacer le corps. `backend/bureautique/rendu.py` compose ensuite le contenu nouveau sans imposer les styles génériques par-dessus ceux du modèle.

`backend/bureautique/illustrations.py` extrait les illustrations du corps du Word avec leur contexte, les fait lire et permet de réutiliser celles retenues dans le plan. Une illustration illisible ou dans un format non décodable est signalée. Une photo ne devient pas une preuve d’une quantité ou d’un engagement. Les illustrations des anciens projets ne sont pas attribuées automatiquement au nouveau chantier.

Le backend inclut désormais LibreOffice Writer et des polices de remplacement. La limite de pages, lorsqu’elle est demandée, est mesurée par un rendu réel. Le PDF est produit depuis le Word pour conserver sa présentation. Une conversion interrompue reprend le Word déjà fabriqué ; elle ne bloque plus sur son état « terminé » et réutilise un PDF déjà acquis.

### Traitement des gros dossiers en arrière-plan

`backend/ressources/documents_file.py` conserve une file dans la même base SQLite. Au-delà de 50 000 caractères de sources, la rédaction est enregistrée en arrière-plan ; une rédaction plus courte interrompue rejoint aussi cette file. Les métrés utilisent cette file dès le départ. Le chat peut être fermé : le travail reste enregistré.

Le worker est lancé par `backend/main.py` pour les rôles de processus `complet` et `fond`. Il traite une rédaction à la fois, limite ses appels LLM de fond, recharge le compte actif et applique ses droits. Chaque tentative dispose de 900 secondes ; les étapes acquises survivent au délai. La reprise est bornée à huit tentatives et s’arrête plus tôt en cas d’échec répété sans progression observée. Un verrou interprocessus empêche deux workers de fabriquer le même document simultanément.

Le résultat, ou le point bloquant, est ajouté dans la conversation d’origine. L’écriture vérifie son propriétaire. Un verrou transactionnel PostgreSQL évite les notifications en double, même si le processus s’arrête entre la publication et son acquittement. Les essais et leur consommation sont conservés ; l’audit reçoit l’activité documentaire et le coût estimé lorsque la base est disponible.

Outils de suivi : `lister_sources_dossier`, `suspendre_redaction`, `reprendre_redaction`. On peut demander dans le chat « où en est la rédaction ? », « suspends cette rédaction » puis « reprends-la ». L’arrêt conserve les sources et les étapes. Un appel fournisseur déjà parti peut terminer avant la suspension effective.

### Mémoires techniques et métrés de l’export

Le mémoire principal comportait sept pièces textuelles, soit plus de 600 000 caractères. L’ancien contexte gardait principalement le début de la première pièce. Le nouveau dossier garde les sept textes et leurs fragments : notice acoustique, CCAP, CCTP et référence Word ne disparaissent plus sous le plafond du prompt. La demande avec cadre imposé et maximum 20 pages peut suivre le parcours complet de rédaction et de pagination.

Les conversations simultanées ne reprennent plus le même brouillon sur le seul critère « même compte + même titre ». `backend/security/conversation.py`, `backend/skills/executor.py`, `backend/bureautique/atelier.py` et les appels de `agent1.py` isolent les mutations et les listes de documents par fil. Une carte de fichier ouvert sur le NAS reste affichable ; elle ne prouve plus qu’un document neuf a été créé.

L’analyse visuelle ne remplace plus le texte du Word joint : `backend/agents/router.py` conserve les deux. Les modèles DeepSeek textuels identifiés dans l’incident sont exclus de la sélection vision et refusés comme nouveau réglage vision. Les clés et autres réglages existants sont conservés.

`backend/skills/plans_dossier.py` lit les pages graphiques d’un plan retrouvé au NAS, dans un mail ou dans le chat. Les pages manquantes sont indiquées. Le parcours documentaire complète automatiquement la lecture des pièces marquées comme graphiques et des pages sans couche texte dans un PDF mixte.

`backend/skills/quantitatifs.py` rapproche les pièces du dossier pour construire un Excel détaillé par lot, poste, niveau et local. Chaque opérande doit apparaître avec son unité dans une citation ; la formule est recalculée en décimal et ses dimensions sont vérifiées. L’affectation au poste doit aussi citer une pièce. Les doublons sont rapprochés, les quantités contradictoires passent en réserve. Une relecture contrôle les affectations et les risques de double comptage.

Le classeur contient le détail, la synthèse, les réserves et des feuilles de preuves. Les quantités sont numériques dans Excel. Le nombre de lignes du fichier rendu est vérifié. Les lectures visuelles sont identifiées comme telles ; une citation de transcription ne constitue pas une validation géométrique. Les postes impossibles à calculer avec les pièces présentes ne sont pas complétés par une estimation présentée comme exacte.

## 2. SYMBIOSE — ce qui change

Application : `SYMBIOSE-audit/symbiose-noa`, projet Compose `symbiose-noa`.

SYMBIOSE reçoit les mêmes modules de dossier, lecture intégrale, composition, pagination, illustrations, quantitatifs, suivi en arrière-plan et isolation par conversation. Le parcours général reste identique : joindre ou retrouver les sources, analyser tous leurs fragments, établir le plan demandé, rédiger et contrôler les sections, vérifier le Word/PDF ou le classeur, puis publier le résultat dans le fil propriétaire.

L’adaptation au connecteur se trouve dans `backend/outils/drive.py`, notamment `_deposer_pour`. L’ouverture d’un fichier Drive récupère ses octets exportés et prépare son texte intégral avec la référence Drive réelle. L’aperçu visible et son téléchargement continuent de fonctionner si la préparation analytique échoue ; l’échec est indiqué et peut être repris par `ajouter_source_dossier`. Un fichier Google exporté en Word peut servir de référence de présentation lorsque son original exporté est accessible.

Les fichiers joints sont conservés par `backend/routers/chat.py`. `backend/agents/router.py` garde le Word et l’analyse d’image ensemble. `backend/agents/agent1.py` montre l’index complet du dossier, distingue source consultée et document créé et transmet la demande originale aux nouveaux outils. `backend/bureautique/atelier.py` et le contexte de conversation empêchent les collisions entre deux fils du même utilisateur.

Le worker de `backend/ressources/documents_file.py` et le démarrage dans `backend/main.py` utilisent les comptes, rôles et volumes existants de SYMBIOSE. Les notifications, reprises, suspensions, contrôles des droits et limites d’exécution fonctionnent selon le même mécanisme que DURET. Les identités, sources et brouillons des deux installations ne sont pas mélangés.

Les usages ne sont pas limités au bâtiment : un dossier paysager, une étude, une présentation ou un rapport peut reprendre sa propre structure. Les tableaux quantitatifs utilisent les unités et preuves réellement disponibles. Les fonctions Nano Banana existantes restent distinctes de cette rédaction documentaire et de la lecture des plans.

## 3. Comment fournir les modèles

Joindre le véritable fichier `.docx` dans la conversation, en plus des pièces du nouveau dossier. Une formulation utile : « Utilise ce Word comme modèle de présentation et comme source des informations stables de notre entreprise. Rédige un nouveau document à partir des autres pièces. Ne reprends pas les faits de son ancien projet. Respecte les rubriques suivantes… »

Le fichier peut aussi rester sur le NAS de DURET ou le Drive de SYMBIOSE : indiquer son nom et son dossier, puis demander de l’ouvrir comme source et modèle. La référence doit être accessible au compte qui rédige. Il n’y a pas de dossier système spécial à créer sur le VPS et aucun JSON à écrire à la main pour cette utilisation.

La copie et ses étapes sont conservées dans le dossier de la conversation. Cela ne publie pas automatiquement une nouvelle trame pour tous les collaborateurs ni un nouveau skill exécutable. Pour un modèle réutilisable dans toute l’organisation, utiliser aussi le mécanisme de trames déjà présent dans l’application. Les règles de qualification des skills restent applicables.

Le texte extrait d’un export Langfuse permet de vérifier la conservation des pièces et le traitement des contraintes. Il ne remplace pas les octets du Word original pour restituer ses logos, ses styles ou ses illustrations.

## 4. Vérifications et limites

La recette générale réussit : 163 bancs DURET et 156 bancs SYMBIOSE, zéro échec. Trois bancs ne sont pas joués dans chaque campagne locale ; les rapports détaillent les dépendances et intégrations concernées. Les essais historiques de déploiement, sauvegarde et retour arrière restent conservés dans la livraison.

Une recette complémentaire de 22 tests couvre les pièces complètes, citations, conservation Word + image, lecture Excel après la ligne 50, unités et conflits de quantités, vraie fabrication Word/Excel, isolation, file persistante, suspension/reprise, pagination, PDF et modèles avec en-têtes hérités. Les appels de rédaction y sont simulés pour tester l’orchestration. Les conversions Word/PDF et les fichiers Excel sont réels. Le texte des sept pièces du véritable export est relu séparément sur les deux projets ; il reste accessible intégralement. Les annonces concurrentes ont également été testées sur PostgreSQL réel avec des données fictives.

Ce que ces tests ne prouvent pas : la qualité finale d’un modèle fournisseur sur toutes les pièces réelles, l’exactitude métier de tous les engagements ou métrés, et une fidélité visuelle au pixel près à un modèle dont les polices propriétaires ne sont pas installées. Les contrôles de contenu utilisent aussi des modèles et peuvent se tromper. Les plans sans cotes, les scans illisibles et les informations d’entreprise absentes nécessitent des réserves ou une précision humaine.

La recette métier finale doit être rejouée après déploiement avec le Word original et les pièces de la demande réelle. Vérifier le fichier téléchargé : toutes les rubriques imposées, les deux lots concernés, les faits actuels, l’entreprise, les illustrations pertinentes, le respect des 20 pages et les réserves. Pour les métrés, contrôler les niveaux, les postes, les unités, les preuves et les totaux. Un inventaire de fichiers ou une simple carte de source n’est pas un résultat acceptable.

Bornes explicites : 8 millions de caractères par source, 30 millions par conversation ; fragments de 18 000 caractères ; 40 sections principales maximum ; 60 illustrations par Word ; références de fichiers jusqu’à 60 Mo selon le résolveur et le connecteur. Le chargement par le chat conserve ses propres limites existantes. Les pièces trop grandes peuvent être sélectionnées ou fractionnées. Ces bornes ne doivent jamais devenir une troncature silencieuse présentée comme complète.

## 5. Déploiement et conservation

Suivre le guide VPS propre au projet dans le dossier de livraison du Bureau. Utiliser la nouvelle archive et son nouveau manifeste d’empreintes. L’installateur retrouve la configuration active, prépare le code à côté, construit les images, sauvegarde, applique les migrations manquantes et compare les données protégées avant remise en service.

Aucune nouvelle clé fournisseur n’est exigée. Aucune nouvelle migration PostgreSQL numérotée n’est ajoutée par ce lot : les migrations additives déjà livrées jusqu’à 054 restent gérées par l’installateur. `dossiers.sqlite3` et sa file se créent automatiquement dans le volume documentaire existant. Les utilisateurs, conversations, clés, trames et historiques sont conservés par la procédure existante.

La reconstruction de l’image backend est indispensable pour installer LibreOffice. Redémarrer seulement un ancien conteneur ne suffit pas. Les rôles `complet` ou `fond` doivent exécuter le worker ; si une installation personnalisée utilise seulement le rôle `interactif`, prévoir son processus de fond avec le même volume documentaire.

Les clés actuelles des fournisseurs et un modèle compatible avec les images restent nécessaires pour les pages graphiques. Les droits NAS/Drive sont ceux du compte demandeur. Les noms de modèles conservés par la configuration ne sont pas remplacés globalement.

Les sauvegardes couvrent déjà le volume documentaire et arrêtent les écritures applicatives pendant sa capture : la nouvelle base SQLite et ses étapes sont donc incluses. Le retour arrière conserve les données ; une ancienne version ne saura simplement pas poursuivre ces nouvelles tâches tant que le nouveau backend n’aura pas été rétabli.
