# Documents téléchargeables

Mode d'emploi complet. Pour un document ordinaire, `produire_document` fait tout
en un appel. Ce qui suit ne sert qu'aux cas que la bibliothèque ne couvre pas.

## Le contenu se DÉCRIT

On ne programme jamais la mise en page : on décrit des blocs, et le code de
rendu (écrit une fois, éprouvé) s'en charge pour les trois formats.

| Bloc | Champs |
|---|---|
| `titre` | `texte`, `niveau` (1 à 4) |
| `paragraphe` | `texte` ; au choix `gras`, `italique`, `centre` (booléens), `taille`, `couleur` |
| `liste` | `items[]`, `ordonnee` (booléen) |
| `tableau` | `entetes[]`, `lignes[[]]`, `legende` |
| `saut_page` | aucun champ |
| `feuille` | `nom`, `entetes[]`, `lignes[[]]` |
| `image` | `image` (la référence), `legende`, `largeur_cm` (2 à 17), `centre` |

**Images.** La référence d'un bloc `image` est ce qu'un geste a déjà rendu :
la clé d'une image de la conversation (photo jointe, image ouverte, tirage),
le jeton d'un document, la `ref` d'une pièce d'un mail ouvert, ou le NOM d'un
fichier image du stockage — jamais un chemin. `entete_image` et `pied_image`
(paramètres de `creer_document` / `produire_document`) posent une image (un
logo) sur chaque page ; en Excel, qui n'a pas d'image d'en-tête, elle est
posée en haut de chaque onglet et en bas du dernier. Une image qui ne se
résout pas est ÉCARTÉE avec sa raison, jamais insérée vide.

**Tailles** : `petit`, `normal`, `grand`, `tres_grand`.
**Couleurs** : `rouge`, `vert`, `bleu`, `orange`, `gris`, `noir`.

Vocabulaire FERMÉ : une valeur inventée retombe sur un défaut sûr plutôt que de
casser le rendu. Pas de jaune : illisible sur blanc à toute taille.

## Les trois formats

- **pdf** : en-tête et pied de page sur chaque page, numérotation.
- **docx** : idem, plus les tableaux natifs Word.
- **xlsx** : chaque bloc `feuille` devient un onglet ; ailleurs, un `feuille`
  est rendu comme un tableau précédé de son nom.

## Les gros documents

`produire_document` accepte 400 blocs d'un coup. Au-delà, il faut l'atelier en
trois temps :

1. `creer_document` ouvre l'enveloppe et rend un `document_id` ;
2. `ajouter_document` verse du contenu, **autant de fois qu'il le faut** ;
3. `terminer_document` produit le fichier et donne le lien.

Le `document_id` se REPREND caractère pour caractère. Il est imprévisible : un
identifiant qui « ressemble » est refusé, et c'est voulu.

Tant que `terminer_document` n'a pas été appelé, **aucun fichier n'existe** : il
n'y a donc rien à télécharger ni à déposer sur le serveur.

## Durée de vie

Un document non téléchargé disparaît au bout de 24 heures. Cinq documents
ouverts au maximum par personne : au-delà, le plus ancien est refermé.

Un document appartient à qui l'a ouvert. Personne d'autre ne peut y ajouter, le
finaliser ni le télécharger, pas même un administrateur.
