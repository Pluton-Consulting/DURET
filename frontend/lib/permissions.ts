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
    href: "/parametres",
    roles: MANAGERS,
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
//  (Même principe que sur le socle : l'en-tête ne porte plus un menu mais
//  trois bulles ; les onglets par agent disparaissent au profit d'une carte
//  par EXPERT dans le tableau de bord ; Apprentissage et Savoir-faire
//  deviennent « Connaissances ».)
// ════════════════════════════════════════════════════════════════════════

export const VUES = [
  { key: "tableau", label: "Tableau de bord", href: "/accueil" },
  { key: "chat",    label: "Chat",            href: "/chat" },
] as const

export const SECTIONS: TabDef[] = [
  { key: "connaissances", label: "Connaissances", href: "/connaissances", roles: MANAGERS },
  { key: "gestion",       label: "Pilotage",      href: "/gestion",       roles: ["super_admin", "direction"] },
  { key: "parametres",    label: "Paramètres",    href: "/parametres",    roles: MANAGERS },
  { key: "superviseur",   label: "Développeur",   href: "/superviseur",   roles: ["super_admin"], dev: true },
]

export function getVisibleSections(role: string): TabDef[] {
  return SECTIONS.filter((s) => s.roles.includes(role))
}

/** Les experts, tels qu'ils se nomment à l'écran. Propres à l'entreprise. */
export const EXPERTS: { cle: string; nom: string; domaine: string; accent: string }[] = [
  { cle: "agent1", nom: "Expert administratif & clients",
    domaine: "administratif et commercial — dossiers, courriers, mails, documents", accent: "primary" },
  { cle: "agent2", nom: "Expert appels d'offres & chiffrage",
    domaine: "études — CCTP, DPGF, plans, métrés, pré-chiffrage", accent: "leaf" },
  { cle: "agent3", nom: "Expert savoir-faire",
    domaine: "apprentissage — compétences, consignes, connaissances acquises", accent: "mid" },
]

export const MARQUE = { nom: "Duret & Sols", logo: "/duret-sols.svg", logoAlt: "Duret & Sols" }
