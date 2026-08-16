# Le compteur de derive

Deux depots jumeaux, un seul produit. Ce dossier repond a une question et une
seule : **de combien ont-ils diverge, et ou ?**

La reponse doit etre un nombre reproductible. Deux lancements successifs
rendent des octets identiques - sans quoi le chiffre ne vaudrait rien.

## Lancer

```sh
./scripts/derive.sh --autre /c/Users/noa8b/Desktop/DURET-SOLS
```

```powershell
.\scripts\derive.ps1 --autre C:\Users\noa8b\Desktop\DURET-SOLS
```

Le chemin du jumeau peut aussi venir de la variable `DERIVE_AUTRE`, ou du
fichier `scripts/derive.jumeau.local` (une ligne, le chemin). Ce dernier est
propre a la machine : **a ajouter au `.gitignore`**, il n'a rien a faire dans
l'historique.

| Option | Effet |
|---|---|
| `--detail` | montre, pour chaque divergence, le diff APRES neutralisation |
| `--json` | sortie machine, pour une verification automatique |
| `--autre` | racine du depot jumeau |

Code de sortie : `0` si toute divergence est declaree, `1` s'il en reste une
qui ne l'est pas, `2` si le compteur n'a pas pu tourner. Le `1` est fait pour
etre branche un jour en verification automatique.

## Ce que le compteur classe

Chaque fichier present des deux cotes tombe dans une case et une seule.

**IDENTIQUE** - les deux contenus sont egaux une fois les fins de ligne
neutralisees (CRLF vers LF, une seule fin de ligne finale). C'etait le bruit
qui rendait tout diff illisible : un fichier annoncait 917 lignes changees
quand 4 l'etaient. Rien d'autre n'est efface - une espace en fin de ligne
reste une difference.

**MARQUE** - les deux contenus deviennent egaux une fois appliquee
`derive.marque.txt` : nom d'entreprise, domaine, couleurs, identifiants de
stockage, vocabulaire metier. Ces fichiers sont mutualisables tels quels ; il
suffira que la marque sorte dans une configuration par client.

**REELLE** - il reste une difference apres les deux neutralisations. C'est de
la derive au sens strict. Soit une divergence voulue, et elle doit figurer dans
`derive.declaration.txt` ; soit un correctif pose d'un seul cote, et il reste
au compteur jusqu'a ce que quelqu'un le traite.

Les fichiers presents d'un seul cote sont comptes a part, et doivent eux aussi
etre declares pour ne plus compter.

## Les deux fichiers a tenir

### `derive.marque.txt` - ce qui n'est QUE de l'habillage

Une regle par ligne : `<expression reguliere>  =>  <jeton neutre>`. Chaque
regle s'applique aux **deux** depots, si bien que la symetrie est structurelle :
il n'y a pas de cote Symbiose et de cote Duret, seulement des motifs qui se
replient sur un meme jeton. Un troisieme client s'ajouterait en allongeant la
liste, sans toucher au moteur.

L'ordre compte : le nom long passe avant le nom court.

Elargir cette table fait baisser le compteur sans qu'une ligne de code ait
bouge. Chaque regle ajoutee doit pouvoir se justifier par un diff reel.

### `derive.declaration.txt` - ce qui a le DROIT de differer

Une entree par ligne : `<chemin ou motif>   # <raison>`. La regle d'admission
est stricte, et elle est le coeur du dispositif :

> On declare le fichier qui **porte la marque par destination** - la charte, le
> logo, le prompt d'identite, le connecteur du socle documentaire d'un client,
> le fichier de deploiement d'un client.
>
> On ne declare **pas** un fichier du socle commun qui a seulement attrape un
> mot de marque au passage, ni un fichier ou un correctif n'a ete pose que d'un
> seul cote. Ces deux-la doivent converger, et le compteur doit continuer a les
> montrer.

Une raison ecrite est obligatoire : sans elle, personne ne saura dans six mois
si la ligne protege une decision ou couvre un oubli.

Une entree qui ne designe plus aucun fichier est signalee comme « sans objet ».
C'est une bonne nouvelle : le fichier a converge, la ligne est a retirer.

## Ce que ce compteur ne voit pas

- **Les migrations SQL et le schema de base.** Hors perimetre. C'est une
  lacune qui compte : la colonne `access_level` des skills existe d'un cote et
  pas de l'autre, et cela se voit dans cinq fichiers Python sans que le schema
  soit jamais compare.
- **Le contenu des dependances.** `package-lock.json` est compare comme un
  texte ; `node_modules/`, `.venv/` et les artefacts de build ne le sont pas du
  tout. Un compteur qui dependrait de qui a lance `npm install` en dernier ne
  mesurerait rien.
- **Les secrets et les fichiers d'environnement.** `.env`, `prod.env`,
  `CREDENTIALS.env` sont exclus : ils decrivent une machine, pas le produit.
- **La granularite est le FICHIER.** Declarer un fichier masque tout ce qu'il
  contient d'autre. `agents/agent1.py` est declare pour son prompt d'identite,
  et cela cache au passage un commentaire deplace. C'est le prix a payer
  aujourd'hui, et la raison de sortir les prompts du Python : le jour ou
  `SYSTEM_PROMPT` sera une donnee par client, le fichier convergera et son
  entree disparaitra.
- **Une couleur changee pour une raison non esthetique.** Toute valeur
  hexadecimale est neutralisee. Les pastilles de role de
  `frontend/lib/permissions.ts` portent des ratios de contraste calcules : le
  compteur ne les verifie pas.
- **Un renommage.** Un fichier deplace apparait comme deux orphelins, pas comme
  un fichier modifie.
- **L'equivalence semantique.** Deux ecritures differentes du meme
  comportement sont comptees comme une divergence. C'est voulu : le but est de
  faire converger le texte, pas seulement le resultat.
