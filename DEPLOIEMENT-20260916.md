# DURET — commandes de livraison du 16 septembre 2026

## Ce que cette procédure conserve

Projet Compose : `duret-sols`. Base par défaut : `duret_sols`, identité PostgreSQL : `duret_user`. Les valeurs réellement en service font foi : l’installateur les lit dans la configuration existante et refuse de viser une autre base ou de changer les volumes.

Les fichiers `.env`, les credentials de `backend/secrets`, les clés en base, les utilisateurs, les conversations, les trames et les documents restent conservés. Aucune rotation des clés existantes. Seul `BROWSER_WORKER_SECRET`, s’il manque ou est explicitement vide, est créé automatiquement. Les anciennes sessions du navigateur sont copiées de `/tmp/sessions` vers le volume persistant `/sessions`.

Le code est préparé dans un nouveau dossier privé à côté de l’installation active, retrouvée dans les labels Docker. Les images se construisent une par une pendant que l’ancienne application fonctionne. Une interruption intervient ensuite pour la sauvegarde, les migrations et le redémarrage. Sa durée dépend du volume de données à sauvegarder. Les fichiers d’exploitation précédents sont conservés ; les anciennes commandes `backup.sh` et `restaurer.sh` suivent le dossier actif après succès.

Topologie prise en charge : le projet existant avec `docker-compose.yml` et `docker-compose.prod.yml`. Un autre overlay, un volume changé, une base externe ou des services actifs supplémentaires provoquent un refus explicite avant modification. Cela protège une installation personnalisée contre l’application d’une configuration incomplète.

## 1. Déposer les fichiers sur le VPS de DURET

Avec votre outil de transfert habituel, créer `~/livraison-ia-2026-09-16` et y copier ces quatre fichiers du dossier fourni :

- `DURET-2026-09-16.tar.gz` ;
- `installer-livraison.py` ;
- `SHA256SUMS` ;
- ce guide, à titre de référence.

Ne pas extraire l’archive dans le dossier en service. Elle contient le code et un manifeste d’empreintes ; elle ne contient aucune clé de votre installation. Ne pas remplacer `.env` par `.env.example`.

## 2. Précontrôle, à copier sur le VPS

Utiliser le compte qui possède l’installation et peut exécuter Docker.

```bash
cd "$HOME/livraison-ia-2026-09-16"
python3 --version
docker compose version
docker info >/dev/null
df -h
free -h
```

Python 3.10 ou ultérieur et le plugin Docker Compose sont requis. Vérifier que le disque peut garder les anciennes images, les nouvelles images et une sauvegarde complète. La construction consomme davantage de mémoire que le fonctionnement habituel ; fermer les autres builds en cours.

Vérifier les deux fichiers utiles à ce VPS, sans exiger l’archive de l’autre projet :

```bash
cd "$HOME/livraison-ia-2026-09-16"
python3 - <<'PYTHON'
import hashlib
from pathlib import Path
attendus = {}
for ligne in Path('SHA256SUMS').read_text().splitlines():
    empreinte, nom = ligne.split(maxsplit=1)
    attendus[nom.strip().lstrip('*')] = empreinte
for nom in ('DURET-2026-09-16.tar.gz', 'installer-livraison.py'):
    assert hashlib.sha256(Path(nom).read_bytes()).hexdigest() == attendus[nom], 'Fichier altéré : ' + nom
    print('Empreinte correcte :', nom)
PYTHON
python3 installer-livraison.py DURET-2026-09-16.tar.gz --projet duret-sols
```

Cette dernière commande prépare une copie privée du code et vérifie l’installation existante. Elle ne lance ni migration, ni arrêt de service, ni remplacement du code actif. Si elle refuse l’installation, lire le motif et corriger la configuration concernée ; ne pas contourner le refus en créant une base vide.

## 3. Appliquer la livraison

Pour conserver la commande même si la connexion SSH se coupe, utiliser `tmux` si disponible :

```bash
tmux new -s livraison-duret
```

Puis lancer :

```bash
cd "$HOME/livraison-ia-2026-09-16"
python3 installer-livraison.py DURET-2026-09-16.tar.gz --projet duret-sols --appliquer
```

Ne fermer la session qu’après « Livraison terminée ». Pour retrouver une session tmux : `tmux attach -t livraison-duret`.

La commande effectue dans l’ordre : contrôle des volumes et des clés ; construction ; arrêt des producteurs ; reprise des derniers fichiers de credentials ; sauvegarde ; conservation des sessions ; migrations manquantes ; comparaison des données antérieures et des secrets ; démarrage ; contrôle `/api/ready`. En cas d’échec après arrêt, elle tente de remettre en service les anciens conteneurs ou leurs images exactes. Elle ne restaure jamais un dump par-dessus la base de production.

## 4. Vérifications après livraison

Retrouver le dossier actif sans deviner son chemin :

```bash
PROJET_IA='duret-sols'
CONTENEUR_IA="$(docker ps -q --filter "label=com.docker.compose.project=$PROJET_IA" --filter label=com.docker.compose.service=backend)"
test -n "$CONTENEUR_IA" || { echo 'Backend actif introuvable'; exit 1; }
DOSSIER_IA="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$CONTENEUR_IA")"
cd "$DOSSIER_IA"
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T backend python -c "import json,urllib.request; r=json.load(urllib.request.urlopen('http://localhost:8000/api/ready',timeout=10)); print(json.dumps(r,ensure_ascii=False,indent=2)); assert r.get('pret') is True"
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=80 backend nginx
```

`pret` doit être `true`, `manquantes` doit être vide. Le journal privé `.livraisons/<date>/termine.json` contient le résultat de readiness et la confirmation de préservation. `.livraisons/<date>/donnees-avant.json` et `donnees-apres.json` portent les empreintes des anciennes colonnes protégées, sans exporter leur contenu. Le manifeste permet de reconnaître le code exact livré.

## 5. Adaptation des bases et fichiers : automatique

Aucune commande SQL manuelle à ajouter après l’installation. Le suivi `schema_migrations` est conservé et chaque migration manquante est appliquée dans une transaction avec sa marque. Les objets attendus sont ensuite contrôlés.

| Migration | Adaptation |
|---|---|
| 049 | Requêtes de chat persistantes, propriétaire et signe de vie, si elle n’était pas encore appliquée. |
| 050 | Baux et propriétaire d’exécution des tâches planifiées. |
| 051 | Rôle PostgreSQL sans contournement des règles d’accès, utilisé dans les transactions utilisateur. Aucun mot de passe PostgreSQL changé. |
| 052 | Versions de skills et preuves de qualification associées à l’empreinte du code. |
| 053 | Compteur d’erreurs et mise à l’écart d’un skill défectueux. |
| 054 | Préparation persistante d’un nouvel index vectoriel et modèle actif, sans effacer l’index pendant son calcul. |

Les petits états de travail, les jetons à usage unique et les recherches reprenables utilisent le volume des documents. Leur création est automatique. Les documents terminés ne sont plus supprimés par une durée de conservation implicite. Une réserve disque protège les nouvelles écritures : surveiller l’espace disponible et conserver les sauvegardes.

## 6. Recette d’usage de DURET

1. Rouvrir une conversation ancienne et un document déjà produit. Vérifier l’accès avec un utilisateur existant.
2. Demander un document à partir d’un vrai modèle du NAS. L’outil `preparer_document_maison` cherche les références ; `reproduire_document` ou `utiliser_trame` reprend le fichier. Comparer en-tête, logo, tableaux, couleurs, texte remplacé et images. Les styles d’un document arbitraire ne se valident pas par le seul succès technique d’un téléchargement.
3. Chercher un terme connu d’un fichier peu courant du NAS. Vérifier la source citée, l’ouverture du fichier et les limites/pagination annoncées. Une source indisponible doit être présentée comme indisponible, pas comme inexistante.
4. Déposer un brouillon fictif, changer son objet et son corps, ajouter une pièce jointe, puis vérifier le brouillon dans la boîte. Tester un indicateur lu/non lu ou suivi. Pour IMAP, conserver aussi `uidvalidity` quand le reçu le fournit. Contrôler l’état distant avant de répéter une action dont le résultat est incertain.
5. Sur un travail de plusieurs messages, vérifier le volet « Travail en cours », les contraintes et les références. Recharger la page pendant une demande : la reprise doit retrouver le résultat, sans réexécuter l’action.
6. Vérifier le cycle d’apprentissage : leçon visible et retirable, conduite divergente mise à vérifier ; skill généré en brouillon, trois cas fictifs au minimum, qualification du code exact, puis validation et activation. Une panne réseau ne doit pas devenir une règle métier.
7. Après un changement de modèle d’embedding, lancer la préparation de l’index depuis les réglages. L’ancien modèle reste actif jusqu’à la bascule ; une panne conserve l’ancien index et les lots préparés. Relancer reprend ces lots.

Les nouveaux droits Gmail de modification/brouillons peuvent nécessiter de reconnecter le compte Google une fois pour consentir aux scopes supplémentaires. Une mise à jour ne peut pas accorder ces droits à la place du titulaire. Les accès déjà accordés sont conservés. Les droits Outlook/IMAP/NAS, les quotas des fournisseurs et la connexion Daytona se vérifient avec les comptes réels après déploiement.

Duret conserve ses outils de lecture de plans et ses images documentaires. Aucun ajout de génération paysagère Nano Banana.

## 7. Sauvegarde et restauration d’essai

Depuis le dossier actif retrouvé à l’étape 4 :

```bash
./backup.sh
```

La sauvegarde sérialise les appels pour ce projet. Elle arrête brièvement les producteurs actifs pour copier ensemble la base, les fichiers et les états SQLite, puis les redémarre, y compris si la sauvegarde échoue. PostgreSQL reste en service. Prévoir ce créneau dans la planification quotidienne.

Le chemin du jeu complet est affiché. Utiliser ce chemin pour créer une copie isolée :

```bash
./restaurer.sh '/chemin/du/jeu/affiché'
```

Cette commande crée un autre projet et d’autres volumes, contrôle les empreintes, restaure les fichiers et la base dans cette copie, adapte son schéma au code, coupe les sorties et attend sa readiness. Les comptes et messages de la copie restent présents ; les credentials externes y sont neutralisés pour la recette. L’authentification de production n’est pas réutilisée dans cette copie isolée. Contrôler les objets restaurés et les comptes en lecture, puis arrêter uniquement la copie :

```bash
./restaurer.sh --arreter
```

Les volumes de la copie sont conservés. Ne jamais utiliser `docker compose down -v` sur le projet de production. Ne pas vider `schema_migrations`, ne pas rejouer `001` manuellement et ne pas lancer un nettoyage Docker global pendant la livraison.

Une copie hors du VPS peut être activée avec `BACKUP_DISTANT='utilisateur@serveur:/dossier' ./backup.sh`, en remplaçant la destination par votre serveur de sauvegarde et après configuration SSH. Un échec de cette copie fait échouer la commande ; le jeu local complet reste disponible. La destination distante et l’alerte de supervision dépendent de votre exploitation. Si `BACKUP_PASSPHRASE` est utilisée, conserver sa valeur ailleurs que sur ce VPS pour pouvoir relire les secrets chiffrés.

## 8. Retour arrière du code

Dans chaque nouveau dossier, `RETOUR-ARRIERE.txt` indique l’ancien chemin, les commandes exactes de retour et celle pour réappliquer la livraison. Le retour fixe également le dossier de projet afin que les credentials et les commandes de sauvegarde suivent la version réellement active. Les installations simultanées du même projet sont refusées. Lire ce fichier :

```bash
cat RETOUR-ARRIERE.txt
```

Les commandes utilisent `.configuration-retour.json`, qui conserve les images réellement en service avant la mise à jour ainsi que leurs montages. Ce fichier est privé car la configuration résolue peut contenir des secrets : ne pas le joindre à un ticket ou à un dépôt Git.

Les migrations additives et les données nouvelles restent en base. Le retour arrière concerne le code ; les fonctionnalités nouvellement ajoutées nécessitent le code de cette livraison pour être utilisées. En cas de coupure du VPS pendant l’installation, retrouver le dossier annoncé, lire le journal privé et utiliser ce fichier de retour plutôt que restaurer un ancien dump sur les écritures récentes.

## 9. Vérifications déjà réalisées sur la livraison

Duret : 162 bancs locaux réussis, aucun échec, trois bancs non joués par le lanceur local (dépendances complètes ou intégration).

Recette rapide dans le vrai conteneur : 27 contrôles réussis, aucun échec, quatre contrôles ignorés en mode rapide. Migration réelle sur PostgreSQL, baux concurrents, séparation SQL des utilisateurs, APIs de qualification, construction des images Linux et conservation des données fictives contrôlées. Les accès à vos fournisseurs et la fidélité à vos modèles métier doivent être vérifiés avec la recette de l’étape 6. Aucun VPS réel n’a été modifié pendant cette préparation.
