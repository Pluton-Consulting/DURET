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
]
