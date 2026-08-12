# Serveur de fichiers (NAS Synology)

Mode d'emploi complet. À lire quand aucune fonction de la bibliothèque ne
couvre le besoin — pour les cas courants, les fonctions sont plus rapides et ne
peuvent pas se tromper d'enchaînement.

## Comment on l'appelle ici

**LE NAS, LE SERVEUR, LE SERVEUR DE FICHIERS, LE RÉSEAU, LES PARTAGES RÉSEAU,
LE DISQUE RÉSEAU et SYNOLOGY désignent tous LA MÊME CHOSE.** Personne dans
l'entreprise ne dit « le NAS Synology » : on dit « le serveur » ou « le
réseau ». Une demande parfaitement claire pour un humain porte donc rarement le
mot NAS.

## Les chemins

Un chemin se REPREND, il ne se reconstruit pas. Chaque entrée rendue par une
liste porte son champ `chemin` : c'est celui-là qu'il faut réutiliser, tel quel.

- Un partage nommé `Drive` vu dans `/home` se désigne **`/home/Drive`**.
- Jamais `/Drive` : le dossier parent serait perdu et le chemin ne désignerait
  rien.

C'est l'erreur la plus fréquente, et elle produit un « fichier introuvable »
qui ressemble à une panne du serveur alors que le fichier existe.

## Ce qui est accessible

Seuls les dossiers ouverts à l'assistant, définis par la configuration. Tout
chemin est vérifié comme étant SOUS l'un d'eux, après neutralisation des `..` et
des chemins relatifs. La racine `/` n'est jamais accessible, même si elle est
configurée : elle exposerait les dossiers personnels et les sauvegardes.

Aucun dossier configuré = aucun accès. Le refus est volontaire, pas un défaut.

## Les limites

| | |
|---|---|
| Entrées par listage | 200 |
| Taille lisible dans le chat | 15 Mo |
| Caractères rendus par fichier | 40 000 |
| Résultats de recherche | 50 |

Un fichier plus gros que 15 Mo ne se lit pas dans une conversation : il faut
passer par une synchronisation, qui l'ingère en mémoire d'entreprise.

## Ce qui se lit

Le même lecteur que les imports : PDF, Word, Excel, CSV, texte, et les scans
par reconnaissance de caractères. Un tableur est rendu comme un tableau
(colonnes + lignes), pas comme du texte.

## Écrire

Le dépôt est la SEULE écriture possible. Pas de suppression, pas de
déplacement, pas de renommage — volontairement. Un dépôt n'écrase jamais un
fichier existant, et il passe par une validation humaine avant d'être exécuté.

## Quand ça tombe en panne

- **« Une fois sur deux »** : le relais QuickConnect change de port à chaque
  allocation. L'adresse retenue devient fausse d'un instant à l'autre ; une
  nouvelle résolution est tentée automatiquement.
- **Codes d'erreur** : les familles DSM se recouvrent. Le code 408 signifie
  « mot de passe expiré » pour l'authentification et « dossier inexistant » pour
  les fichiers. Le message rendu tient compte du contexte de l'appel.
