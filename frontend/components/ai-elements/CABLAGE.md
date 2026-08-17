# Ce qui est câblé, ce qui ne l'est pas, et pourquoi

Les 19 composants d'AI Elements sont **posés et compilent tous**. Ce document dit
lesquels sont branchés à une donnée réelle, et pour les autres, ce qu'il faudrait
pour qu'ils disent quelque chose de vrai.

La règle qui a tranché chaque cas : **un composant qui affiche une valeur
approximative avec l'assurance d'une valeur mesurée coûte plus cher qu'un
composant absent.** Un écran qui ment se corrige lentement, parce qu'on ne le
soupçonne pas.

## Branchés à une donnée réelle

| Composant | Ce qu'il affiche | D'où vient la donnée |
|---|---|---|
| `Conversation` | le fil et son défilement | l'état local du chat |
| `Message`, `MessageContent` | chaque bulle | idem |
| `MessageResponse` | le texte des réponses (Streamdown) | `final_response` |
| `MessageActions`, `MessageAction` | copier la réponse | le texte affiché |
| `PromptInput` et sa famille | la saisie, les pièces jointes, l'envoi | l'état local |
| `Shimmer` | le balayage du libellé d'activité | `libelle` (WebSocket) |
| `Sources` | les documents et pages ayant nourri la réponse | `sources_memoire`, `browser_sources` |
| `Suggestion` | les propositions d'action | bloc ```ui `quick_replies` |

## Non branchés, et la raison

**`Reasoning`** a été branché, puis débranché. Son dépliant listait les étapes
déjà franchies — c'est-à-dire les phrases qui venaient de défiler dans la ligne
d'activité juste au-dessus, et que la colonne de droite résume déjà par grandes
étapes. Ouvrir ne montrait rien de neuf. Ce qui avait été demandé, « le texte de
raisonnement qui défile », c'est la ligne vivante : elle reste, sans le pli.
`ReflexionEnCours` mesure désormais sa durée elle-même, ce que le composant
tenait pour lui. Le défaut d'ouverture automatique qu'il portait a été corrigé
avant le débranchement, pour qu'il soit sain s'il resert un jour.

**`Context`** dessine un anneau de remplissage du contexte. Il exige `maxTokens`,
la fenêtre maximale du modèle. Or la cascade change de modèle à chaud
(`llm/router.py`) et aucune table fiable n'existe. Une jauge à 12 % calculée sur
un maximum approximatif serait un chiffre faux affiché avec assurance. Les jetons
réels sont donc affichés sans le décor, dans `SourcesReponse`.
*Pour le brancher :* une table modèle vers fenêtre, tenue à jour à chaque
changement de cascade.

**`Image`** attend `base64` et `mediaType` (`Experimental_GeneratedImage`). Nos
visuels sont des **URL** distantes rendues par Higgsfield (`visuels/higgsfield.py:147`).
Le brancher imposerait de télécharger puis ré-encoder chaque image pour la
redonner au navigateur qui allait la chercher lui-même.
*Pour le brancher :* un type de bloc ```ui `visuel` rendant les URL, ce qui est
plus simple et plus juste.

**`WebPreview`** charge une page tierce dans un cadre de l'application. Les pages
consultées apparaissent déjà comme liens dans `Sources`. Faire entrer du contenu
extérieur dans l'écran demande une décision explicite, pas un câblage discret.

**`Tool`** montrerait chaque action avec ses entrées et sorties. Mais la trace de
raisonnement le fait déjà, avec le lieu et le budget consommé
(« je parcours les dossiers du Drive : Chantiers/2026 [3/8] »). Deux endroits
pour une seule chose, c'est le défaut que `MessageList` met en garde par ailleurs.
Ses libellés d'état sont en outre figés en anglais dans le composant.

**`Task`** n'a aucun état : ni prop `status`, ni `state`. C'est un dépliant
décoratif, il ne peut pas porter les cinq états d'une tâche.

**`ChainOfThought`** ne connaît que trois états là où `ReasoningPath` en distingue
cinq. « Sauté » rabattu sur « à venir » ferait attendre une étape qui ne viendra
jamais. Voir le commentaire en tête de `components/chat/ReasoningPath.tsx`.

**`CodeBlock`** ferait doublon : Streamdown rend déjà le code, coloration comprise,
par le greffon `@streamdown/code`.

**`InlineCitation`** ancre une citation sur un passage précis. Le RAG rend des
extraits avec leur fichier d'origine, pas la position dans ce fichier. Sans cet
ancrage, la citation désignerait un document entier, ce que `Sources` fait déjà.
*Pour le brancher :* remonter l'index du morceau et sa position, ce que le
vectorstore stocke (`chunk_index`) mais ne transmet pas.

**`Artifact`**, **`Canvas`**, **`Plan`**, **`OpenInChat`** n'ont pas d'usage ici :
respectivement un panneau de document (l'aperçu est déjà sous la carte fichier),
un constructeur de graphe, un plan d'exécution que l'agent ne produit pas, et
l'ouverture d'un contenu dans une autre conversation.

## Extend UI

Dix composants posés. `pptx-viewer` est câblé dans l'aperçu, aux côtés de docx,
xlsx, csv et pdf. `file-upload` et `pdf-block-resizable-shell` sont disponibles.

Quatre du registre sont **écartés pour incompatibilité de génération** :
`file-system`, `schema-builder`, `document-splits` et `e-signature` sont écrits
contre **Base UI** (`render` au lieu de `asChild`, `DialogPanel`,
`CollapsiblePanel`, `keepMounted`). Les adopter imposerait de migrer les 22
primitives shadcn et de casser tout ce qui est bâti dessus.

## Deux pièges à connaître avant de poser un composant

**`--overwrite` écrase les extensions maison.** Six primitives portent des
ajouts nécessaires à la compatibilité Coss UI (le `loading` du bouton, le `size`
en mot-clé de l'input, le `scrollFade` de la zone défilante, les variantes du
badge). Une pose avec `--overwrite` les détruit. Vérifier `git status` après.

**Plusieurs composants importent mermaid statiquement.** `message.tsx` et
`reasoning.tsx` le faisaient : 164 Ko dans le paquet du chat, mesurés, pour une
syntaxe qu'ils n'affichent jamais. Vérifier le poids de `/chat` après chaque pose.
