# Lot 1 de l'audit — ce qu'il faut faire, dans l'ordre, et ce qu'on doit voir

Branche `audit/duret`. Ce document est la **procédure** : les commandes se lancent
sur le serveur (Noa), les contrôles se font à l'écran. Rien ici n'a tourné contre
le vrai Postgres, le vrai NAS ni un navigateur — c'est précisément ce que cette
recette va dire.

Fiches livrées dans ce lot : **D-02** (styles Word), **D-05** (un échec n'est plus
une réussite), **D-06** (recherche quand les embeddings tombent), **D-03** (propriété
des visuels, jeton), **D-27** (doublons du NAS), **D-19** (code administrateur),
**D-22** (journaux et export), **D-23 / D-26 / D-00** (sauvegarde, déploiement,
restauration).

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
3. **Optionnel mais recommandé** : `BACKUP_PASSPHRASE=<phrase>` (chiffre les
   secrets dans les sauvegardes) et `BACKUP_DISTANT=user@hote:/chemin` (copie
   hors de la machine). La phrase de passe se garde **ailleurs** que les
   sauvegardes.

## 2. Déployer (D-26 — la livraison vérifiée)

```bash
cd ~/DURET/duret-sols        # le dossier du projet sur le VPS
git fetch origin && git checkout audit/duret && git pull
./deploy.sh
```

`deploy.sh` fait, **dans cet ordre** : version livrée → construction des images →
**sauvegarde** → démarrage de la base seule → **migrations** (la **044** est la
nouvelle ; un échec ARRÊTE la livraison) → vérification que le schéma est complet
→ bascule → attente de `/api/ready`.

**À VÉRIFIER** : la dernière ligne affiche l'état prêt, avec le commit. Sinon, le
script dit ce qui manque et rappelle le retour arrière — l'ancienne version est
restée en service.

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
* Les fiches restantes (D-01, D-04, D-07 à D-18, D-20, D-21, D-24, D-25, et la
  suite de D-05, D-06, D-22, D-27) ne sont pas dans ce lot.
