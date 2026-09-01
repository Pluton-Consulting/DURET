// Hiérarchie : super_admin > direction > métier
// super_admin = développeur, accès total
// direction   = dirigeants, vue client + gestion app

export type Role =
  | "super_admin"
  | "direction"
  | "commercial"
  | "bureau_etudes"
  | "conducteur"
  | "administratif"
  | "terrain"

export const ROLE_LABELS: Record<string, string> = {
  super_admin:   "Super Admin",
  direction:     "Direction",
  commercial:    "Commercial",
  bureau_etudes: "Bureau d'études",
  conducteur:    "Conducteur",
  administratif: "Administratif",
  terrain:       "Terrain",
}

// Pastilles de rôle. Deux exigences qui tirent en sens inverse : rester dans la
// famille de la marque (encre, bleu, rouge du logo), et rester DISTINGUABLES
// entre elles — sept nuances du même bleu ne se lisent plus.
//
// Elles servent de texte sur une teinte très pâle d'elles-mêmes : chacune est
// donc vérifiée à 4,5 minimum sur fond clair. Le bleu pur du logo (#0687DA)
// plafonne à 3,83 et n'apparaît pas ici — il reste à la marque, où il n'a pas
// de texte à porter.
export const ROLE_COLORS: Record<string, string> = {
  super_admin:   "#0B0E11",   // l'encre du logo — 19,35
  direction:     "#0A6FB4",   // le bleu de marque, assombri — 5,32
  commercial:    "#0B66A6",   // 6,06
  bureau_etudes: "#0B7285",   // 5,59
  conducteur:    "#A16207",   // le jaune de marque, assombri — 4,92
  administratif: "#606B78",   // 5,42
  terrain:       "#CC0E1B",   // le rouge de marque, assombri — 5,76
}

export interface TabDef {
  key: string
  label: string
  href: string
  roles: string[]
  /** RÉSERVÉ À QUI DÉVELOPPE. L'onglet se dessine dans la couleur à part
   *  (`--marque-dev`) : de la mécanique, pas du travail de l'entreprise. */
  dev?: boolean
}

const ALL_ROLES: string[] = [
  "super_admin",
  "direction",
  "commercial",
  "bureau_etudes",
  "conducteur",
  "administratif",
  "terrain",
]

const MANAGERS: string[] = ["super_admin", "direction"]

export const TABS: TabDef[] = [
  { key: "accueil",     label: "Accueil",            href: "/accueil",     roles: ALL_ROLES },
  { key: "commercial",  label: "Administratif",  href: "/commercial",  roles: ALL_ROLES },
  {
    key: "conception",
    label: "Appels d'offres",
    href: "/conception",
    roles: ["super_admin", "direction", "bureau_etudes", "conducteur"],
  },
  {
    key: "auto-evolution",
    label: "Apprentissage",
    href: "/auto-evolution",
    roles: ["super_admin", "direction"],
  },
  {
    key: "skills",
    label: "Savoir-faire",
    href: "/skills",
    roles: MANAGERS,
  },
  {
    key: "gestion",
    label: "Pilotage",
    href: "/gestion",
    roles: ["super_admin", "direction"],
  },
  // L'ONGLET « RECHERCHE WEB » A ÉTÉ RETIRÉ DU MENU, ET C'EST UN GAIN.
  //
  // Il portait une capacité que le chat n'avait pas : pour faire lire une page
  // à l'assistant, il fallait quitter la conversation, remplir un formulaire
  // dans un autre écran, puis revenir avec le résultat. Deux endroits pour une
  // seule idée — et, côté modèle, une capacité qu'il ignorait posséder : il
  // répondait « je ne peux pas accéder à internet », ce qui était vrai depuis
  // sa place.
  //
  // La navigation est désormais un GESTE du chat (`chercher_web`,
  // `ouvrir_page`) : on la demande là où le besoin naît.
  //
  // LA PAGE EXISTE TOUJOURS, à /navigateur, et reste accessible par son
  // adresse : elle porte la navigation AUTONOME — celle qui se connecte et
  // remplit des formulaires. Celle-là appelle un accord humain et un choix de
  // domaines ; elle n'a pas sa place dans un menu de tous les jours.
  {
    key: "parametres",
    label: "Paramètres",
    // Ouvert à TOUS : chacun y relie SA boîte Google (connexion personnelle).
    // Les onglets d'administration restent filtrés par rôle dans la page.
    href: "/parametres",
    roles: ALL_ROLES,
  },
  // Console développeur — logs bruts en direct, super_admin uniquement.
  {
    key: "superviseur",
    label: "Développeur",
    href: "/superviseur",
    roles: ["super_admin"],
    dev: true,
  },
]

export function getVisibleTabs(role: string): TabDef[] {
  return TABS.filter((t) => t.roles.includes(role))
}

export function canAccess(role: string, tabKey: string): boolean {
  const tab = TABS.find((t) => t.key === tabKey)
  return tab ? tab.roles.includes(role) : false
}

// ════════════════════════════════════════════════════════════════════════
//  NAVIGATION V2 — deux vues, un panneau, des experts.
//
//  L'en-tête ne porte plus un menu : trois bulles flottantes. Au centre un
//  SWITCH à deux positions — le tableau de bord et le chat — parce que ce sont
//  les deux seules choses qu'on ouvre dix fois par jour. Tout le reste vit
//  derrière l'engrenage, dans un panneau qui glisse depuis la droite : ce qui
//  se règle, se consulte rarement, ou ne concerne que qui administre.
//
//  Les onglets « par agent » disparaissent : ils n'affichaient que des
//  maquettes. Leurs indicateurs RÉELS vivent dans le tableau de bord, une carte
//  par EXPERT — c'est ainsi qu'on les nomme désormais à l'écran : un expert de
//  quelque chose, pas un « agent ». Apprentissage et Savoir-faire, qui
//  parlaient de la même chose, deviennent un seul onglet « Connaissances ».
// ════════════════════════════════════════════════════════════════════════

/** Les deux vues du switch central. */
export const VUES = [
  { key: "tableau", label: "Tableau de bord", href: "/accueil" },
  { key: "chat",    label: "Chat",            href: "/chat" },
] as const

/** Ce qui vit derrière l'engrenage, dans l'ordre d'affichage. */
export const SECTIONS: TabDef[] = [
  { key: "connaissances", label: "Connaissances",
    // « ce que l'assistant sait faire et ce qu'il apprend » : validations,
    // débrief d'apprentissage, savoir-faire — réunis.
    href: "/connaissances", roles: MANAGERS },
  { key: "gestion",       label: "Pilotage",      href: "/gestion",     roles: ["super_admin", "direction"] },
  // Ouvert à TOUS : chacun y relie SA boîte Google ; les onglets
  // d'administration restent filtrés par rôle dans la page elle-même.
  { key: "parametres",    label: "Paramètres",    href: "/parametres",  roles: ALL_ROLES },
  { key: "superviseur",   label: "Développeur",   href: "/superviseur", roles: ["super_admin"], dev: true },
]

export function getVisibleSections(role: string): TabDef[] {
  return SECTIONS.filter((s) => s.roles.includes(role))
}

/** Les experts, tels qu'ils se nomment à l'écran. Propres à l'entreprise. */
// `court` : le même expert dans un en-tête de colonne, où « Expert appels
// d'offres » ne tient pas. AJOUTÉ le 01/09 parce que la matrice des droits
// affichait encore « Agent 1 / Agent 2 / Agent 3 » — relevé de Noa : « ça veut
// dire quoi agent 1 2 3 dans les utilisateurs, c'est pas clair ». Le mot
// « agent » avait disparu des écrans en août, sauf là.
export const EXPERTS: { cle: string; nom: string; court: string; domaine: string; accent: string }[] = [
  { cle: "agent1", nom: "Expert administratif & chantiers", court: "Admin & chantiers",
    domaine: "suivi de chantiers, clients, mails, documents administratifs", accent: "primary" },
  { cle: "agent2", nom: "Expert appels d'offres", court: "Appels d'offres",
    domaine: "analyse de DCE — CCTP, CCAP, RC, DPGF, métrés et chiffrage", accent: "leaf" },
  { cle: "agent3", nom: "Expert savoir-faire", court: "Savoir-faire",
    domaine: "apprentissage — compétences, consignes, connaissances acquises", accent: "mid" },
]

/** Le nom d'écran d'un expert, à partir de sa clé technique. Jamais « agent1 ». */
export function nomExpert(cle: string, court = false): string {
  const e = EXPERTS.find((x) => x.cle === cle)
  return e ? (court ? e.court : e.nom) : cle
}

export const MARQUE = { nom: "Duret & Sols", logo: "/duret-sols.svg", logoAlt: "Duret & Sols" }
