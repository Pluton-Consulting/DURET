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
    label: "Auto-Évolution",
    href: "/auto-evolution",
    roles: ["super_admin", "direction"],
  },
  {
    key: "skills",
    label: "Skills",
    href: "/skills",
    roles: MANAGERS,
  },
  {
    key: "gestion",
    label: "Gestion",
    href: "/gestion",
    roles: ["super_admin", "direction"],
  },
  {
    key: "navigateur",
    label: "Navigateur",
    href: "/navigateur",
    roles: MANAGERS,
  },
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
  },
]

export function getVisibleTabs(role: string): TabDef[] {
  return TABS.filter((t) => t.roles.includes(role))
}

export function canAccess(role: string, tabKey: string): boolean {
  const tab = TABS.find((t) => t.key === tabKey)
  return tab ? tab.roles.includes(role) : false
}
