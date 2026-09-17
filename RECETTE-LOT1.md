# L'audit sur Duret — ce qu'il faut faire, dans l'ordre, et ce qu'on doit voir

Branche `audit/duret`. Ce document est la **procédure** : les commandes se lancent
sur le serveur (Noa), les contrôles se font à l'écran. Rien ici n'a tourné contre
le vrai Postgres, le vrai NAS ni un navigateur — c'est précisément ce que cette
recette va dire.

Fiches livrées sur cette branche, dans l'ordre des commits :

**Lot 1** — **D-02** (styles Word), **D-05** (un échec n'est plus une réussite),
**D-06** (recherche quand les embeddings tombent), **D-03** (propriété des visuels,
jeton), **D-27** (doublons du NAS), **D-19** (code administrateur, puis connexions
Google), **D-22** (journaux et export), **D-23 / D-26 / D-00** (sauvegarde,
déploiement, restauration).

**Lot 2** — **D-04** (versions et atelier durables), **D-07** (références stables),
**D-01** (bon document de référence), **D-09** (droits dans la requête), **D-08**
(réindexation), **D-10** (pagination des mails), **D-11** (un envoi ne part qu'une
fois), **D-13** (une demande ne lance qu'un tour), **D-16** (budget de temps),
**D-17** (baux de vectorisation), **D-20** (cloisonnement PostgreSQL), **D-12**
(montants au centime), **D-14** (leçons qualifiées), **D-15** (code généré isolé),
**D-18** (rôle du processus), **D-21** (SSRF du navigateur), **D-25** (la recette qui
se mesure), **D-24** (pages d'un PDF, suite du tour).

---

## 1. Avant de déployer (D-00 — la préparation)

1. **Pousser la branche** (Claude ne pousse pas) :
   `git push origin audit/duret` depuis le worktree `DURET-audit`.
2. **Deux réglages à poser dans le `.env` du serveur** (audit D-19) :
   ```
   CODE_ADMIN_DEFAUT=<4 à 6 chiffres, propre à cette installation>
   CODE_CHIFFREMENT_CLE=<openssl rand -hex 32>
   ```
   · `CODE_ADMIN_DEFAUT` ne sert **qu'une fois** : à la première entrée, l'écran
   fait poser un vrai code. Ne l'écrire nulle part ailleurs.
   · `CODE_CHIFFREMENT_CLE` sépare le chiffrement des codes du secret des
   sessions. Vide, tout continue de fonctionner (ancienne dérivation) ; posée,
   les codes se réécrivent avec elle au fil des lectures.
3. **Une clé de plus** (audit D-19, connexions Google) :
   ```
   JETONS_CHIFFREMENT_CLE=<openssl rand -hex 32>
   ```
   Elle chiffre au repos les jetons des comptes Google reliés, séparément du
   secret des sessions. Vide, tout continue (dérivation depuis `JWT_SECRET_KEY`).
4. **Optionnel mais recommandé** : `BACKUP_PASSPHRASE=<phrase>` (chiffre les
   secrets dans les sauvegardes) et `BACKUP_DISTANT=user@hote:/chemin` (copie
   hors de la machine). La phrase de passe se garde **ailleurs** que les
   sauvegardes.
5. **Facultatif, pour plus tard** : `ROLE_PROCESSUS` (audit D-18) reste à
   `complet` — ne le changer que le jour où l'on ajoute un second processus.

## 2. Déployer (D-26 — la livraison vérifiée)

```bash
cd ~/DURET/duret-sols        # le dossier du projet sur le VPS
git fetch origin && git checkout audit/duret && git pull
./deploy.sh
```

`deploy.sh` fait, **dans cet ordre** : version livrée → construction des images →
**sauvegarde** → démarrage de la base seule → **migrations** (**044**, **045**,
**046**, **047**, **048**, **049** sont nouvelles, toutes additives et idempotentes ; un
échec ARRÊTE la livraison) → vérification que le schéma est complet → bascule →
attente de `/api/ready`.

**À VÉRIFIER** : la dernière ligne affiche l'état prêt, avec le commit. Sinon, le
script dit ce qui manque et rappelle le retour arrière. Avant la bascule, un échec
arrête la livraison en conservant les conteneurs précédents. Après la bascule,
un échec de readiness exige un retour arrière explicite : il n'est pas automatique.

```bash
# la version réellement en ligne, à tout moment
curl -s https://duret.pluton-consulting.fr/api/ready | head -c 400
```

## 3. Ce qu'on doit voir, fiche par fiche

### D-19 — le code administrateur
1. Se déconnecter, ouvrir `/login`, bouton **Admin**, taper `CODE_ADMIN_DEFAUT`.
   **À VÉRIFIER** : on entre, et un panneau s'impose : « Choisissez votre code
   d'administrateur ». Poser un code de 4 à 6 chiffres.
2. Se déconnecter, réessayer avec `CODE_ADMIN_DEFAUT`.
   **À VÉRIFIER** : refusé — « le code de première entrée a déjà servi ». Le
   nouveau code, lui, ouvre.
3. Cinq codes faux d'affilée → carte bloquée un quart d'heure, dit à l'écran.
4. **Porte de secours** (à connaître, à ne pas garder ouverte) :
   ```bash
   docker compose exec backend python scripts/code_admin.py --lister
   docker compose exec backend python scripts/code_admin.py --profil <nom>
   ```
   Le code s'affiche **une fois**, dans le terminal du serveur.

### D-03 — les visuels ont un propriétaire
1. Depuis deux comptes différents : le premier joint une photo au chat, le second
   ouvre l'URL `/api/visuels/<clé>` de cette photo.
   **À VÉRIFIER** : le second reçoit 404 (« visuel inconnu »), le premier la voit.
2. Rattacher les visuels d'avant le correctif (ils restent lisibles par défaut) :
   ```bash
   docker compose exec backend python scripts/rattacher_visuels.py            # constat
   docker compose exec backend python scripts/rattacher_visuels.py --ecrire   # rattache
   ```
   **À VÉRIFIER** : le constat dit combien de visuels ont un propriétaire
   établi et combien restent indéterminés. Les anciennes conversations montrent
   toujours leurs images.
3. Une image reçue en pièce jointe d'un mail, insérée dans un Word : elle entre
   (elle se résout maintenant dans SA boîte) ; depuis un compte sans droit sur
   cette boîte, elle est refusée en le disant.

### D-27 — les doublons du NAS
1. Paramètres → Synchronisations → « Ce que l'assistant apprend du NAS ».
   **À VÉRIFIER** : la pastille ne dit plus « N doublons » mais « N copies
   possibles, lues en dernier », et la décision **Toujours apprendre** est
   proposée pour un dossier (trames, procédures, référentiels).
2. Poser deux fichiers de **même nom et même taille** mais de contenu différent
   dans deux affaires. Lancer une synchronisation.
   **À VÉRIFIER** : les deux sont lus (aucun n'est écarté), et le compte rendu
   dit « copies possibles » / « copies reconnues ».
3. Un vrai doublon (même contenu) : le second n'est pas relu, il reprend les
   morceaux du premier — et reste rangé sous **son** dossier et **son** niveau
   d'accès.
4. L'encart « fichiers écartés » donne le motif et le prochain essai ; le bouton
   **Réessayer ces fichiers** les rouvre au palier suivant.

### D-22 — journaux et export
1. Console développeur → **Exporter tout (Excel)**.
   **À VÉRIFIER** : le téléchargement démarre tout de suite (plus d'attente
   pendant que le navigateur charge tout en mémoire) ; la dernière ligne du CSV
   est un `#manifeste` avec le nombre de lignes ; une question commençant par
   `=` apparaît en texte, pas en formule.
2. `docker compose logs backend | grep -i "key="` → aucune clé lisible, seulement
   `***` suivi de six caractères.

### D-19 (suite) — les connexions Google
1. Relier un compte Google, puis sur le serveur :
   `SELECT left(refresh_token, 8) FROM connexions_google;`
   **À VÉRIFIER** : la valeur commence par `coffre1:`, jamais par `1//`.
2. Les comptes reliés AVANT ce déploiement continuent de marcher et passent au
   coffre au premier rafraîchissement (journal : « Jetons Google mis au coffre »).
3. `docker compose logs backend | grep "MAGIC LINK"` → **rien** en production.

### D-24 — la page qu'il faut lire
Joindre un DCE long dont la cote utile est en page 8, et demander cette cote.
**À VÉRIFIER** : la réponse donne la cote OU dit explicitement quelles pages ont
été lues et que celle-là ne l'a pas été — jamais un « non visible » sans précision.
Une demande de photomontage reçoit une explication fidèle : aucun moteur de
retouche n'est installé ici, et l'assistant ne le promet pas.

### Le reste du lot 2, en une passe
* **D-01 / D-04** — « reprends ce devis pour Madame Martin », puis « change le
  prix », puis « joins-le à un mail ». **À VÉRIFIER** : c'est la DERNIÈRE version
  qui part ; on ne redemande pas ce qui a déjà été dit.
* **D-09** — un compte sans accès à une boîte demande un compte de messages.
  **À VÉRIFIER** : le compte annoncé est celui qu'on a le droit de lire.
* **D-11 / D-13** — approuver un envoi, puis recharger la page pendant le
  traitement. **À VÉRIFIER** : le mail ne part pas deux fois.
* **D-12** — « le total des devis de l'année » : juste au centime.
* **D-14** — corriger l'assistant, puis Connaissances → Leçons : la leçon porte un
  type et une confiance ; une correction qui suit une panne n'en crée aucune.
* **D-08** — relancer « Enrichir les documents » : aucun document ne perd ses
  morceaux en route (une réindexation est une seule transaction).
* **D-15** — un skill GÉNÉRÉ (Savoir-faire → un brouillon de skill) : sans
  exécuteur isolé configuré, il est REFUSÉ en le disant. Les gestes natifs
  continuent normalement.
* **D-16** — un tour qui enchaîne plusieurs gestes se termine, et une cascade
  entièrement en panne ne fait plus payer tous ses fournisseurs avant de conclure.
* **D-21** — « ouvre http://169.254.169.254/ » → refusé, en le disant.
* **D-25** — `docker compose exec backend python scripts/recette_usages.py` → un
  rapport daté, 0 FAIL.

### D-05 / D-06 — les gestes disent la vérité
1. Poser une question qui déclenche un geste voué à l'échec (par exemple retenir
   une consigne vide). **À VÉRIFIER** : l'assistant dit l'échec ; la console le
   compte comme un échec, pas comme une réussite.
2. Couper la clé Google (Paramètres → Clés API) et chercher dans les documents.
   **À VÉRIFIER** : la recherche répond quand même (voie plein texte) et dit que
   la recherche par sens est indisponible — jamais « je n'ai rien trouvé ».

### D-02 — les documents gardent leur mise en page
Reprendre un devis Word du NAS et remplacer un nom.
**À VÉRIFIER** : logo, en-tête, styles et tableaux intacts ; seule la valeur
demandée a changé ; l'assistant dit ce qu'il n'a pas pu remplacer.

## 4. L'exercice de restauration (D-23) — à faire une fois, au calme

```bash
./backup.sh                                   # un jeu complet, daté
./restaurer.sh ~/duret-backups/duret_<date>   # une copie ISOLÉE, ports 3100/8100
```

**À VÉRIFIER dans la copie** (jamais dans la production) : une conversation
passée s'ouvre avec ses pièces jointes ; une trame se rouvre ; un document avec
image montre son image ; un brouillon de mail garde sa pièce jointe. Noter **le
temps qu'a pris la reprise** et **l'heure du dernier point restaurable**
(manifeste du jeu) : c'est ce couple qui dit ce que la maison peut perdre.

La copie ne peut **rien envoyer** : clés vidées dans son `.env` et dans sa base,
tâches planifiées et lecture du NAS coupées.

```bash
./restaurer.sh --arreter                      # puis, si l'on veut, docker volume rm …
```

## 5. Retour arrière

* **Application** : `git checkout <commit précédent> && ./deploy.sh`. Les
  migrations de ce lot sont **additives** : l'ancienne image les ignore.
* **Intégration continue du NAS** : un clic dans Paramètres → Synchronisations.
* **Code administrateur** : `scripts/code_admin.py` rend l'accès sans revenir en
  arrière sur le code.
* **Base** : une restauration en production est une opération préparée — jamais
  un réflexe. Passer par la copie isolée d'abord.

## 6. Ce que ce lot ne prouve pas

* Aucune requête n'a tourné contre le vrai Postgres du serveur : le SQL des
  migrations et de l'export est vérifié par les bancs, pas par la production.
* Le NAS, le Drive et les fournisseurs de modèles n'ont pas été appelés.
* Rien n'a été rendu dans un navigateur : l'écran du tri, le panneau du code
  administrateur et l'export se jugent à la première utilisation.
* Les **étapes 2** annoncées fiche par fiche dans `AUDIT-SUIVI.md` ne sont pas
  faites : registre des ressources en base (D-03/D-07), générations de vecteurs
  (D-17), delta Graph des mails (D-10), recadrage des cotes (D-24), rétention et
  modes de confidentialité (D-22), écran détaillé du tri NAS (D-27).
* La bascule du rôle applicatif PostgreSQL (D-20) est une opération de serveur :
  `scripts/controle_droits_base.py` dit seulement où l'on en est.

## Complément de fiabilisation du 16 septembre 2026

- Inclure `backend/requirements.lock` et la migration `049_requetes_signe_de_vie.sql` dans la livraison. La branche locale contient aussi des fichiers nouveaux non suivis tant que les corrections ne sont pas enregistrées dans Git.
- Construire le backend depuis le fichier verrouillé avec empreintes ; NumPy reste en version 1.x pour spaCy 3.7. Le frontend utilise Next 15.5.25, PostCSS 8.5.28 et Sharp 0.35.4.
- Le code backend de production est désormais dans l’image ; les secrets et les documents restent montés. Le montage intégral du code n’existe que dans `docker-compose.dev.yml`. Une simple réouverture du navigateur ne livre donc pas ces changements.
- Le signe de vie des requêtes bat toutes les 15 secondes ; une demande sans signe de vie depuis 120 secondes devient interrompue lors de sa consultation, sans relance automatique. Le budget total d’un tour est de 600 secondes (`DEMANDE_DELAI_S`).
- Les pièces jointes des nouveaux accords sont copiées avant validation, contrôlées par SHA-256 avant envoi et conservées sept jours. Après cette durée, préparer un nouvel accord.
- Une recherche sans résultat en mémoire complète la lecture avec le stockage et/ou la boîte autorisés, avec 15 secondes par source. Les noms trouvés doivent encore être ouverts ; cette recherche n’est pas exhaustive.
- Les tests de la dernière revue et leurs limites sont détaillés dans `FIABILISATION-20260916.md`. Ne pas classer la production validée avant la recette des services réels.
