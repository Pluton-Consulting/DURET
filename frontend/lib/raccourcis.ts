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
]
