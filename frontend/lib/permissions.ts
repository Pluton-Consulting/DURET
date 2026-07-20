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

export const ROLE_COLORS: Record<string, string> = {
  super_admin:   "#0F1F0E",
  direction:     "#304D32",
  commercial:    "#2563eb",
  bureau_etudes: "#0891b2",
  conducteur:    "#d97706",
  administratif: "#6b7280",
  terrain:       "#92400e",
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
