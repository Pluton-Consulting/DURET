// LES PROCESS FRÉQUENTS du menu de la barre de saisie (bouton éclair).
//
// Fichier PAR CLIENT, déclaré dans la dérive : le MÉCANISME (menu, préremplissage)
// est du socle (`InputBar.tsx`, identique des deux côtés), le CONTENU est du
// métier — les rendus d'image n'existent que chez le client qui a l'offre
// visuelle. Un clic PRÉREMPLIT la saisie, il n'envoie rien : on relit, on
// ajuste, on envoie soi-même. 31/08 : les entrées clients et CA ont été
// retirées à la demande de Noa.
export const RACCOURCIS: { libelle: string; prompt: string }[] = [
  { libelle: "Synthèse des mails (7 jours)",
    prompt: "Fais le point sur tous mes mails des 7 derniers jours : une synthèse message par message, et propose une réponse pour chacun de ceux qui en appellent une." },
  { libelle: "Dossiers en attente",
    prompt: "Quels dossiers sont en attente d’une réponse ou d’une relance, du plus ancien au plus récent ?" },
  // LE COMPTE RENDU DE REUNION (03/09, demande de Noa). Le raccourci PREREMPLIT
  // la consigne et laisse le curseur a la fin : on colle la transcription
  // dessous, on envoie. Le travail lui-meme est fait par le skill
  // `compte_rendu_reunion` (backend/skills/reunion.py), qui decoupe et lit TOUT
  // le texte -- c'est pour cela qu'on peut coller une heure de reunion sans
  // rien elaguer.
  { libelle: "Compte rendu de réunion",
    prompt: `Fais le compte rendu de cette réunion : concis, avec les points clés, les décisions prises, et les actions (qui fait quoi, pour quand). Signale ce qui reste en suspens, et les réserves ou points bloquants s'il y en a.

N'invente aucun responsable ni aucune échéance qui n'aurait pas été dit : laisse-les vides, je les compléterai.

Transcription :
` },
  { libelle: "Analyser un DCE",
    prompt: "Je joins une pièce du DCE : analyse-la (lots, contraintes, délais, pièges) et dis ce qu’il faut vérifier avant de chiffrer." },
  // LE CHIFFRAGE D'UN PLAN, EN PASSES SÉPARÉES (02/09, demande de Noa).
  //
  // Inspiré d'un workflow de métré CVC multi-passes qui tourne en production
  // chez un autre client : six appels au modèle, un par sujet, chacun recevant
  // le résultat des précédents. Ce qui fait la qualité de ce workflow tient en
  // quatre principes, et ils se transposent tels quels à une demande unique :
  //
  //  · UNE MISSION PAR PASSE, en ignorant explicitement le reste. Un modèle à
  //    qui l'on demande tout à la fois survole tout ; à qui l'on demande une
  //    chose, il la fait bien.
  //  · LA LÉGENDE AVANT TOUT. Les conventions graphiques varient d'un bureau
  //    d'études à l'autre : les supposer, c'est se tromper sur tout le reste.
  //    On lit d'abord le cartouche et la légende, et on s'y tient.
  //  · TOUTE MESURE DIT SA SOURCE, par ordre de fiabilité décroissante : cote
  //    lue, déduction par proportion, estimation d'après un étalon, non
  //    mesurable. Un chiffre sans provenance ne vaut rien dans un DPGF.
  //  · UNE SYNTHÈSE QUI SE JUGE : ce qui manque, ce qui est à vérifier sur
  //    site, et si le métré est exploitable tel quel. Un métré qui ne dit pas
  //    ses trous se fait prendre pour un métré fini.
  //
  // Le raccourci PRÉREMPLIT : on relit, on ajuste au dossier, on joint le
  // plan, on envoie. Il complète le préprompt de `agent2.VISION_PROMPT`, qui
  // s'applique à toute image ; il ne le répète pas.
  { libelle: "Chiffrer un plan",
    prompt: `Je joins un plan. Prépare-moi un métré exploitable pour le chiffrage.

Procède en six étapes SÉPARÉES, dans cet ordre. À chaque étape, traite SON sujet et ignore ce qui relève des autres : c'est ce qui évite de survoler.

1. CARTOUCHE ET LÉGENDE, avant tout le reste.
Lis le cartouche (titre, niveau, échelle, date, indice, lot, maître d'œuvre) puis la légende, trame par trame et symbole par symbole. La légende prime toujours sur une convention supposée : elle change d'un bureau d'études à l'autre. Termine en désignant l'ÉTALON qui servira à mesurer (porte annotée, trame de poteaux, cote générale) et donne sa valeur.

2. LOCAUX.
Recense TOUS les locaux en balayant méthodiquement, zone par zone : nord-ouest, nord-est, centre, sud-ouest, sud-est. Pour chacun : nom annoté (sinon dis « non annoté » et déduis l'usage), usage, surface si elle est cotée, niveau. N'oublie aucun petit local : sas, placards, gaines techniques, circulations, escaliers.

3. REVÊTEMENTS ET SUPPORTS.
Pour chaque local de l'étape 2, nommé par son nom : revêtement prévu (carrelage, résine, béton, sol souple, parquet, ragréage), support existant, existant à déposer, chape ou isolation à prévoir.

4. QUANTITÉS, CHACUNE AVEC SA SOURCE.
Surfaces de sol (m²), plinthes (ml), seuils, joints de dilatation, profilés, nez de marche, relevés. Pour chaque quantité, dis d'où elle vient, dans cet ordre de préférence :
- cote lue sur le plan : reprends-la telle quelle ;
- déduction par proportion à partir d'une cote lue : montre le calcul ;
- estimation d'après l'étalon de l'étape 1 : rappelle l'étalon et sa valeur ;
- rien de tout cela : écris « non mesurable » et n'avance aucun chiffre.

5. POINTS SINGULIERS ET CONTRAINTES.
Ce qui coûte sans apparaître dans une surface : siphons, trappes, regards, réservations, changements de niveau, pentes, escaliers, découpes, accès au chantier, phasage imposé, locaux occupés.

6. SYNTHÈSE.
Un tableau des quantités par poste : quantité, unité, fiabilité de la mesure. Puis dis-moi ce qui manque pour chiffrer vraiment, ce qu'il faut vérifier sur site, et si ce métré est exploitable tel quel ou s'il demande une reprise. Ne donne aucun prix.` },
  // MESURER SUR UNE PHOTO (02/09, demande de Noa) : « il doit être capable
  // d'analyser une image et faire des liens avec un plan 2D, ou trouver des
  // éléments sur l'image qui lui permettent d'établir une échelle pour
  // mesurer ».
  //
  // UN PLAN EST À L'ÉCHELLE PARTOUT, UNE PHOTO NE L'EST NULLE PART. C'est
  // toute la difficulté, et c'est pourquoi ce raccourci est séparé de
  // « Chiffrer un plan » plutôt que fondu dedans : la méthode n'est pas la
  // même. Deux réflexes portent la fiabilité, et ils sont contre-intuitifs :
  //
  //  · COMPTER PLUTÔT QUE MESURER. Dès qu'un motif se répète (carreaux,
  //    lames, marches, parpaings), compter les unités et multiplier par la
  //    dimension unitaire bat très largement une longueur jugée à l'œil.
  //  · DIRE CE QUI FRAGILISE LA MESURE. Ce qui fuit vers le fond est
  //    sous-estimé, l'étalon ne vaut qu'à sa propre distance, un grand angle
  //    déforme les bords. Une mesure photographique qui tait ses limites se
  //    fait prendre pour une cote.
  //
  // Et quand un plan accompagne la photo, chacun son rôle : le plan dit les
  // dimensions, la photo dit l'état. Ce que l'un montre et que l'autre ignore
  // est justement ce qui coûte.
  { libelle: "Mesurer d'après une photo",
    prompt: `Je joins une ou plusieurs photos (et le plan, si j'en ai un). Sers-t'en pour mesurer et préparer le chiffrage.

Procède en six étapes SÉPARÉES, dans cet ordre.

1. CE QUE MONTRE LA PHOTO.
Décris la scène : local ou zone, nature du sol en place, état, ce qui est visiblement à déposer. Si un plan est joint, dis D'OÙ la photo est prise et QUELLE zone du plan elle montre, en t'appuyant sur des repères communs (ouvertures, poteaux, angles, changements de revêtement).

2. L'ÉTALON.
Cherche dans l'image un objet de dimension connue et nomme-le, avec la valeur que tu lui prêtes : porte (0,83 ou 0,93 m de passage, 2,04 m de haut), marche (giron 25 à 30 cm), carreau, plinthe (7 à 10 cm), prise (8,5 cm), interrupteur (1,10 m du sol), parpaing (20 x 20 x 50), palette (80 x 120), personne (1,70 m). Si rien de connu n'est visible, dis-le : sans étalon, aucune mesure n'est possible sur photo, et il vaut mieux le dire que produire un chiffre.

3. LES MESURES, EN COMPTANT D'ABORD.
Dès qu'un motif se répète, COMPTE les unités et multiplie : quinze carreaux de 60 cm font 9 m, c'est bien plus sûr qu'une longueur estimée. Vaut pour les carreaux, les lames, les marches, les parpaings, les dalles de plafond, les poteaux. Ce qui ne se compte pas se mesure par comparaison avec l'étalon de l'étape 2, en rappelant lequel.

4. CE QUI FRAGILISE CHAQUE MESURE.
Pour chaque quantité, dis ce qui la rend fragile : longueur qui fuit vers le fond (sous-estimée, ordre de grandeur seulement), élément plus loin ou plus près que l'étalon, photo prise en biais, bords déformés par un grand angle, zone masquée. Donne des fourchettes, plus larges que sur un plan.

5. PHOTO ET PLAN, CHACUN SON RÔLE (si un plan est joint).
Pour les DIMENSIONS, le plan fait foi. Pour l'ÉTAT réel, c'est la photo : dégradations, supports, existant à déposer, réseaux apparents, obstacles, accès. Dis ce que la photo apprend et que le plan ne dit pas, c'est ce qui coûte. Signale en clair toute CONTRADICTION (cloison ajoutée, revêtement différent de celui prévu).

6. SYNTHÈSE.
Un tableau : poste, quantité, unité, méthode (comptage, étalon, ordre de grandeur), fiabilité. Puis ce qu'il faut aller mesurer sur site parce que la photo ne le permet pas, et si ce relevé est exploitable tel quel. Ne donne aucun prix.` },
]
