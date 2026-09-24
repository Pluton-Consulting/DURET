// LE MENU ÉCLAIR de la barre de saisie : LES 19 PROMPTS DU CAHIER DURET & SOLS.
//
// Fichier PAR CLIENT, déclaré dans la dérive : le MÉCANISME (menu, préremplissage)
// est du socle (`InputBar.tsx`, identique des deux côtés), le CONTENU est du
// métier. Un clic PRÉREMPLIT la saisie, il n'envoie rien : on relit, on remplace
// les crochets ([nom exact du chantier], [chemin]…), on envoie soi-même.
//
// 24/09, demande de Noa : « remplace les boutons rapides par tous ces prompts :
// un bouton par prompt, avec le titre du prompt ; quand on clique, ça écrit tout
// le prompt associé dans le chat ». Les textes sont ceux du cahier « PROMPT DURET
// SOLS » (19 prompts en 6 familles), recopiés TELS QUELS : rôle, contexte, tâche,
// contraintes, format, contrôle — c'est le cahier de recette du client, pas une
// rédaction à nous. Les crochets sont laissés : ce sont les trous à remplir.
// Les anciens raccourcis (courrier entrant, relances, compte rendu, chiffrage
// d'un plan en six passes…) ont quitté le menu à cette date ; les skills
// qu'ils appelaient existent toujours, une phrase suffit à les demander.
export type Raccourci = { famille: string; libelle: string; prompt: string }

const AO = "Appels d'offres et études"
const MAIL = "Boîte mail et suivi client"
const NAS = "NAS, Drive et arborescence"
const CHANTIER = "Chantier et PlanRadar"
const CHIFFRES = "Chiffres, factures, pilotage"
const MAISON = "Documents maison et planning"

export const RACCOURCIS: Raccourci[] = [
  // ── 1. Appels d'offres et études ──────────────────────────────────────
  { famille: AO, libelle: "Analyser un dossier de consultation complet",
    prompt: `Tu es chargé d'études en revêtements de sols. Tu travailles pour Duret & Sols.

DCE du chantier [nom exact du chantier], dossier [chemin]. Pièces : CCTP, CCAP, RC, DPGF, plans.

Produis une fiche de lecture : objet du marché, lots concernés, exigences techniques sols, délais, pénalités, pièces à fournir, dates limites.

Chaque élément renvoie à sa pièce et à sa page. Aucune exigence reformulée à l'approximation. Une information absente est écrite comme absente.

Un tableau rubrique / exigence / pièce source / page, puis cinq lignes de synthèse.

Annonce les pièces lues, celles que tu n'as pas trouvées, et les points à vérifier auprès du maître d'œuvre.` },
  { famille: AO, libelle: "Extraire les exigences revêtements de sols du CCTP",
    prompt: `Tu es technicien sols souples et durs. Tu lis un CCTP comme un exécutant, pas comme un commercial.

Document : [nom exact du CCTP], chantier [chantier], dans [chemin du dossier].

Relève tout ce qui concerne les sols : supports et états de surface exigés, produits et classements imposés, tolérances, mises en œuvre, réception, entretien.

Citations littérales entre guillemets. Aucune norme ajoutée de mémoire. Aucune marque supposée si le CCTP ne la nomme pas.

Une liste par local ou par zone, avec l'article du CCTP en référence.

Termine par les exigences ambiguës ou contradictoires, et par ce qui manque pour chiffrer.` },
  { famille: AO, libelle: "Comparer deux versions d'un document",
    prompt: `Tu es vérificateur de pièces marché : tu relèves les écarts, tu ne les interprètes pas.

Document A : [nom exact, indice, date]. Document B : [nom exact, indice, date]. Même chantier : [chantier].

Liste toutes les différences, en séparant celles qui ont un impact sur notre lot de celles qui n'en ont pas.

Aucun écart passé sous silence, même mineur. Pas de conclusion commerciale. Les quantités modifiées sont citées telles quelles.

Un tableau article / version A / version B / impact sur notre lot (oui, non, à vérifier).

Annonce le nombre d'écarts relevés et les parties que tu n'as pas pu comparer.` },
  { famille: AO, libelle: "Préparer la trame de réponse à une consultation",
    prompt: `Tu es responsable d'études : tu prépares le squelette de la réponse, Benoît écrit le fond.

Règlement de consultation [nom exact]. Réponse déjà rendue qui sert de modèle : [nom du dossier précédent].

Établis la liste des pièces à remettre, la trame du mémoire technique et le rétroplanning jusqu'à la date limite.

Aucune référence chantier inventée. Aucun prix. Les rubriques imposées par le RC sont reprises mot pour mot.

Un Word éditable déposé dans le dossier du chantier, plus une checklist des pièces.

Rappelle la date et l'heure limites de remise, et ce qui reste à produire en interne.` },

  // ── 2. Boîte mail et suivi client ─────────────────────────────────────
  { famille: MAIL, libelle: "Revue de boîte exhaustive et priorisée",
    prompt: `Tu es mon assistant de direction. Tu connais nos clients, nos fournisseurs et nos chantiers en cours.

Boîte [adresse], période : les [7] derniers jours. Les noms manquants se retrouvent dans l'historique des échanges.

Annonce le nombre total de mails reçus, puis liste-les tous : date, expéditeur, objet, résumé en une phrase, catégorie (appel d'offres, chantier, fournisseur, administratif, sans suite).

Aucun regroupement, aucune troncature, aucun « etc. ». Si la liste est longue, continue jusqu'au bout.

Un tableau, puis les trois mails à traiter en priorité avec la raison.

Termine en confirmant que le nombre de lignes du tableau égale le total annoncé.` },
  { famille: MAIL, libelle: "Brouillons de réponse dans mon style",
    prompt: `Tu écris à ma place, dans mon style : il se déduit de mes propres messages envoyés à chaque interlocuteur.

Les mails de la revue précédente qui appellent une réponse.

Rédige un brouillon par mail : reprends le tutoiement ou le vouvoiement déjà employé, réponds à chaque question posée, propose une suite concrète.

Aucun engagement de prix ni de délai que je n'ai pas donné. Signature [nom] à la fin de chaque message. Rien n'est envoyé.

Les brouillons numérotés dans ta réponse, et déposés en brouillon dans la boîte.

Liste à part les mails que tu n'as pas su traiter et pourquoi. Je te dirai lesquels envoyer.` },
  { famille: MAIL, libelle: "Reconstituer l'historique d'un dossier",
    prompt: `Tu es analyste de gestion : chaque information que tu avances est rattachée à sa source.

Dossier : [chantier ou client]. Sources autorisées : boîte mail, dossier [chemin], devis, situations et factures.

Reconstitue la chronologie : commandes, échanges décisifs, documents produits, points en suspens, dernière action connue.

Une source citée par ligne : nom de fichier ou date du mail. Aucun montant estimé. Une information manquante est écrite comme manquante.

Une fiche d'une page, chronologie en tableau, déposée dans le dossier du chantier.

Termine par la liste de ce que tu n'as pas trouvé et de l'endroit où tu as cherché.` },
  { famille: MAIL, libelle: "Relancer les devis restés sans réponse",
    prompt: `Tu es chargé du suivi commercial. Ton objectif est d'obtenir une réponse, pas de forcer une signature.

Devis envoyés depuis la boîte et enregistrés dans [chemin]. Un devis est en attente s'il n'a reçu ni réponse ni commande.

Identifie tous les devis en attente depuis plus de [15] jours, puis rédige une relance par client.

Ton courtois, jamais insistant. Rappel du numéro, du montant HT et de la date. Aucune remise proposée.

Un tableau client / devis / montant HT / date / chemin du fichier, puis les relances en brouillon.

Indique le montant total en attente et les devis pour lesquels tu n'as pas pu vérifier l'absence de réponse.` },

  // ── 3. NAS, Drive et arborescence ─────────────────────────────────────
  { famille: NAS, libelle: "Inventaire d'un dossier chantier",
    prompt: `Tu es documentaliste : tu inventories avant d'agir, tu n'interprètes pas les noms de fichiers.

Dossier à inventorier : [chemin complet], sous-dossiers inclus sur [un] niveau.

Liste tout son contenu : nom exact, type, date de modification, taille, sous-dossier d'appartenance.

N'ouvre aucun fichier. Ne renomme rien. Ne déduis pas le contenu d'un fichier depuis son nom.

Un tableau trié par date décroissante, avec les noms copiables tels quels.

Annonce le nombre total d'éléments et signale les doublons de nom. Je te dirai ensuite lequel ouvrir.` },
  { famille: NAS, libelle: "Ouverture certaine d'un document",
    prompt: `Tu restitues un document, tu ne le résumes pas tant que je ne l'ai pas demandé.

Document visé : [nom exact copié depuis l'inventaire], dans [chemin du dossier].

Ouvre-le et restitue-le intégralement : toutes les pages, tous les postes, annexes comprises.

Interdiction d'ouvrir un document approchant. Aucun résumé à la place du contenu. Aucun montant reconstitué de mémoire.

Le contenu fidèle, précédé du nom du fichier réellement ouvert et de son chemin complet.

Si le fichier est introuvable, arrête-toi et propose les cinq noms les plus proches avec leur emplacement.` },
  { famille: NAS, libelle: "Créer et ranger un dossier chantier",
    prompt: `Tu appliques notre convention de nommage à la lettre, tu n'en proposes pas une meilleure.

Emplacement : [chemin des chantiers]. Règle maison : [numéro de département — ville — NOM du client — année].

Crée le dossier pour [client], chantier à [ville], avec les sous-dossiers types, et copie dedans [les fichiers modèles].

Nommage strictement conforme aux dossiers existants, casse comprise. Aucun dossier créé ailleurs. Aucune variante si un dossier proche existe déjà.

Le nom exact du dossier créé, son chemin complet, et la liste de ce qui a été copié dedans.

Avant de créer, montre-moi deux dossiers existants dont tu t'inspires pour le nommage.` },

  // ── 4. Chantier et PlanRadar ──────────────────────────────────────────
  { famille: CHANTIER, libelle: "Synthèse des réserves d'un chantier",
    prompt: `Tu es conducteur de travaux : tu pilotes des réserves, tu ne commentes pas la qualité du travail.

Chantier [nom] dans PlanRadar, export des tickets [nom du fichier ou période].

Fais l'état des réserves : ouvertes, en cours, clôturées, avec le responsable, la date d'ouverture et l'ancienneté en jours.

Aucun ticket regroupé ni omis. Un ticket sans responsable est signalé comme tel, pas attribué d'office.

Un tableau trié par ancienneté décroissante, puis les cinq réserves à traiter en priorité.

Annonce le nombre total de tickets et vérifie que la somme des statuts égale ce total.` },
  { famille: CHANTIER, libelle: "Préparer une visite de chantier",
    prompt: `Tu prépares ma visite : tu me donnes de quoi arriver informé, pas un rapport à lire sur place.

Chantier [nom], visite le [date]. Sources : tickets PlanRadar, dossier [chemin], derniers échanges mail.

Prépare une note d'une page : avancement connu, réserves ouvertes, points à vérifier sur site, questions à poser au maître d'œuvre.

Uniquement ce qui est documenté. Aucune estimation d'avancement inventée. Chaque point renvoie à sa source.

Une page, quatre rubriques, listes courtes, lisible sur téléphone.

Termine par ce que tu n'as pas pu vérifier et qui doit être constaté sur place.` },
  { famille: CHANTIER, libelle: "Compte rendu de chantier à partir des tickets",
    prompt: `Tu rédiges un compte rendu destiné au client et au maître d'œuvre : factuel, daté, sans jugement.

Chantier [nom], période du [date] au [date]. Sources : tickets PlanRadar, photos, notes de visite.

Rédige le compte rendu : travaux réalisés, points bloquants, décisions attendues, échéances, avec les photos utiles en regard.

Aucune responsabilité imputée à un tiers. Aucun engagement de délai non validé. Vocabulaire du CCTP repris.

Un Word à la charte, déposé dans le dossier du chantier, une page recto si possible.

Liste les tickets utilisés et ceux volontairement écartés, avec le motif.` },

  // ── 5. Chiffres, factures, pilotage ───────────────────────────────────
  { famille: CHIFFRES, libelle: "Chiffre d'affaires sur une période",
    prompt: `Tu es contrôleur de gestion. Un chiffre sans méthode explicite n'a aucune valeur.

Périmètre : les factures de vente de [source], du [date] au [date]. Un devis ou une situation non facturée n'est jamais du chiffre d'affaires.

Calcule le chiffre d'affaires HT de la période, avec le détail mois par mois et la part des trois premiers clients.

Montants HT uniquement. Date retenue : la date de facture. Aucun document ambigu intégré sans me le signaler. Aucune extrapolation sur un mois incomplet.

Le total, le tableau mensuel, et un Excel des factures retenues (numéro, date, client, montant HT, chemin).

Déclare le nombre de factures prises en compte, celles écartées avec le motif, et celles que tu n'as pas pu lire.` },
  { famille: CHIFFRES, libelle: "Portefeuille client classé",
    prompt: `Tu es analyste : tu appliques la définition que je te donne, pas la tienne.

Période : [année]. Définition imposée : le chiffre d'affaires d'un client est la somme de TOUTES ses factures sur la période, jamais une facture isolée.

Classe les clients par chiffre d'affaires décroissant. Donne les dix premiers et les dix derniers, avec nombre de factures, total et panier moyen.

Regroupe les variantes d'écriture d'un même nom et dis-moi lesquelles tu as fusionnées. Aucun client inventé, aucun client oublié.

Deux tableaux, puis une lecture en cinq lignes : concentration du portefeuille et clients à réactiver.

Annonce le nombre total de clients analysés et vérifie que la somme des CA clients égale le CA de la période.` },
  { famille: CHIFFRES, libelle: "Achats fournisseur et consommations matière",
    prompt: `Tu es acheteur : tu rapproches ce qui est acheté de ce qui est posé.

Deux jeux de données : les factures d'achat du fournisseur [nom] sur [période], et les quantités posées des chantiers de la même période.

Un : totalise les achats — montant HT, nombre de factures, détail numéro / date / montant / chemin. Deux : rapproche achats et quantités posées par chantier.

Une facture illisible est signalée, jamais écartée en silence. Un rapprochement fondé sur moins de trois factures est marqué comme non fiable.

Un Excel à deux feuilles, la seconde triée par écart décroissant avec une colonne « donnée incomplète ».

Termine par les chantiers dont l'écart mérite une vérification, dans un sens comme dans l'autre.` },

  // ── 6. Documents maison et planning ───────────────────────────────────
  { famille: MAISON, libelle: "Produire un document à la charte Duret & Sols",
    prompt: `Tu es maquettiste : tu reproduis une charte existante, tu n'en proposes pas une nouvelle.

Étape 1 : trouve un document Duret & Sols à la charte (devis, facture, note de chantier) et montre-moi son en-tête et son pied de page en disant de quel fichier ils viennent.

Produis [le document demandé] en reprenant cet en-tête, ce pied de page, ces couleurs et cette hiérarchie de titres. Contenu : […].

Aucune police ni couleur hors charte. Toute mention d'une autre entreprise remplacée par Duret & Sols. Aucune page coupée, aucun tableau débordant.

Un Word éditable, déposé dans [dossier de destination], avec son nombre de pages annoncé.

Avant de me le rendre, vérifie l'en-tête et le pied de page sur chaque page et dis-moi que c'est fait.` },
  { famille: MAISON, libelle: "Planning des équipes de pose",
    prompt: `Tu es conducteur de travaux : tu planifies sous contrainte de moyens, pas à l'idéal.

Moyens : [nombre] équipes de [nombre] poseurs, jours ouvrés. Chantiers et échéances : [source]. Période : [mois ou trimestre].

Construis le planning : une ligne par intervention (date, chantier, ville, prestation, durée prévue, statut), une feuille par mois, déplacements regroupés par secteur.

Ne dépasse jamais le nombre d'équipes disponibles. Pas plus de [7] heures d'intervention par jour. Respecte les dates contractuelles de livraison.

Un Excel, plus la charge mensuelle en jours et le taux d'occupation des équipes.

Signale les semaines en surcharge et les chantiers à décaler. Pour la mise à jour hebdomadaire, redonne-moi ce prompt en précisant la semaine.` },
]

// Les familles, dans l'ordre du cahier : le menu les affiche comme des rubriques.
export const FAMILLES_RACCOURCIS: string[] = RACCOURCIS.reduce<string[]>(
  (acc, r) => (acc.includes(r.famille) ? acc : [...acc, r.famille]), [])
