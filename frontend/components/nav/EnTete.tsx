"use client"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { signOut } from "next-auth/react"
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { MARQUE, ROLE_LABELS, VUES, getVisibleSections } from "@/lib/permissions"

/**
 * L'EN-TÊTE EN TROIS BULLES.
 *
 * Plus de barre pleine largeur avec un menu : trois bulles flottantes, qui ne
 * touchent ni les bords ni entre elles. À gauche le logo, juste à sa taille.
 * Au centre un SWITCH à deux positions — tableau de bord, chat — dont le
 * curseur glisse d'une position à l'autre : ce sont les deux seules vues
 * qu'on ouvre dix fois par jour. À droite un engrenage, juste à sa taille,
 * qui ouvre un panneau glissant depuis la droite avec tout le reste — le
 * profil, et les sections qu'on consulte rarement ou qui n'intéressent que
 * qui administre.
 *
 * Le switch parle à la scène (les deux vues côte à côte) par un événement,
 * pas par une navigation : c'est ce qui permet de FAIRE GLISSER la vue
 * plutôt que de la recharger. Hors de la scène (sur une page Connaissances,
 * Paramètres…), un clic navigue normalement vers la vue demandée.
 */

export const EVENEMENT_VUE = "v2:vue"

interface Props { role: string; email: string; name: string }

const ICONES = {
  tableau: (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="3" y="3" width="7" height="9" rx="2" /><rect x="14" y="3" width="7" height="5" rx="2" />
      <rect x="14" y="12" width="7" height="9" rx="2" /><rect x="3" y="16" width="7" height="5" rx="2" />
    </svg>
  ),
  chat: (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  ),
  engrenage: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  ),
}

const ICONES_SECTIONS: Record<string, ReactNode> = {
  connaissances: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /></svg>,
  gestion: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M3 3v18h18" /><path d="m7 15 4-4 4 4 5-6" /></svg>,
  parametres: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M4 21v-7" /><path d="M4 10V3" /><path d="M12 21v-9" /><path d="M12 8V3" /><path d="M20 21v-5" /><path d="M20 12V3" /><path d="M1 14h6" /><path d="M9 8h6" /><path d="M17 16h6" /></svg>,
  superviseur: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg>,
}
const SOUS_TITRES: Record<string, string> = {
  connaissances: "Ce que l'assistant sait faire et apprend — à valider, savoir-faire, apprentissage",
  gestion: "Usages, coûts, journal — pour la direction",
  parametres: "Utilisateurs, droits, horaires, quotas, connecteurs",
  superviseur: "Console technique — réservée au développement",
}

export default function EnTete({ role, email, name }: Props) {
  const pathname = usePathname()
  const router = useRouter()
  const [panneau, setPanneau] = useState(false)
  const sections = getVisibleSections(role)

  // La vue active : lue dans l'URL, et tenue à jour par la scène quand elle glisse.
  const vueDeChemin = pathname?.startsWith("/chat") ? "chat" : pathname === "/accueil" || pathname === "/" ? "tableau" : null
  const [vue, setVue] = useState<string | null>(vueDeChemin)
  useEffect(() => { setVue(vueDeChemin) }, [vueDeChemin])
  useEffect(() => {
    const h = (e: Event) => setVue((e as CustomEvent).detail)
    window.addEventListener(EVENEMENT_VUE, h)
    return () => window.removeEventListener(EVENEMENT_VUE, h)
  }, [])

  // Le curseur se place sous le bouton actif : mesuré, pas supposé, parce
  // que les deux libellés n'ont pas la même largeur.
  const refSwitch = useRef<HTMLDivElement>(null)
  const [curseur, setCurseur] = useState<{ x: number; w: number; visible: boolean }>({ x: 0, w: 0, visible: false })
  useLayoutEffect(() => {
    const conteneur = refSwitch.current
    if (!conteneur) return
    const cible = conteneur.querySelector<HTMLButtonElement>(`[data-vue="${vue}"]`)
    if (!cible) { setCurseur((c) => ({ ...c, visible: false })); return }
    setCurseur({ x: cible.offsetLeft - 5, w: cible.offsetWidth, visible: true })
  }, [vue])

  const aller = (cle: string) => {
    setVue(cle)
    // La scène se déclare elle-même quand elle est montée : c'est elle qui sait
    // glisser. Sans elle (page Connaissances, Paramètres…), on navigue.
    const surScene = typeof document !== "undefined" && document.documentElement.hasAttribute("data-v2-scene")
    if (surScene) {
      // La scène écoute, glisse, et met l'URL à jour elle-même.
      window.dispatchEvent(new CustomEvent(EVENEMENT_VUE + ":demande", { detail: cle }))
    } else {
      router.push(VUES.find((v) => v.key === cle)?.href || "/accueil")
    }
  }

  const initiales = (name || email).split(/[\s.@]+/).filter(Boolean).slice(0, 2).map((m) => m[0]).join("").toUpperCase() || "?"

  useEffect(() => {
    if (!panneau) return
    const echap = (e: KeyboardEvent) => { if (e.key === "Escape") setPanneau(false) }
    document.addEventListener("keydown", echap)
    return () => document.removeEventListener("keydown", echap)
  }, [panneau])

  return (
    <>
      <header className="v2-entete" role="banner">
        <Link href="/accueil" className="v2-bulle v2-bulle-logo sym-tap" aria-label={MARQUE.nom}>
          <img src={MARQUE.logo} alt={MARQUE.logoAlt} />
        </Link>

        <div className="v2-bulle v2-switch" ref={refSwitch} role="tablist" aria-label="Vue principale">
          <span className="v2-switch-curseur" aria-hidden
                style={{ transform: `translateX(${curseur.x}px)`, width: curseur.w, opacity: curseur.visible ? 1 : 0 }} />
          {VUES.map((v) => (
            <button key={v.key} type="button" role="tab" className="v2-switch-bouton"
                    data-vue={v.key} aria-pressed={vue === v.key} aria-selected={vue === v.key}
                    onClick={() => aller(v.key)}>
              {ICONES[v.key as "tableau" | "chat"]}<span>{v.label}</span>
            </button>
          ))}
        </div>

        <button type="button" className="v2-bulle v2-bulle-engrenage" aria-label="Réglages et autres sections"
                aria-expanded={panneau} data-ouvert={panneau ? "oui" : "non"} onClick={() => setPanneau((p) => !p)}>
          {ICONES.engrenage}
        </button>
      </header>

      {/* Le panneau : profil en tête, sections en liste, déconnexion en pied. */}
      <div className="v2-voile" data-ouvert={panneau ? "oui" : "non"} onClick={() => setPanneau(false)} aria-hidden />
      <aside className="v2-panneau" data-ouvert={panneau ? "oui" : "non"} aria-label="Réglages" aria-hidden={!panneau}>
        <div className="v2-panneau-tete">
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ width: 46, height: 46, borderRadius: 16, background: "rgba(255,255,255,.18)", display: "grid", placeItems: "center",
                          fontWeight: 800, fontSize: 16, letterSpacing: ".5px", boxShadow: "inset 0 1px 0 rgba(255,255,255,.25)" }}>
              {initiales}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontWeight: 800, fontSize: 16, letterSpacing: "-.2px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{name || email}</div>
              <div style={{ fontSize: 12.5, opacity: .85, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{email}</div>
              <div style={{ marginTop: 6, display: "inline-block", fontSize: 11, fontWeight: 700, padding: "3px 9px", borderRadius: 999,
                            background: "rgba(255,255,255,.16)", letterSpacing: ".04em", textTransform: "uppercase" }}>
                {ROLE_LABELS[role] || role}
              </div>
            </div>
            <button type="button" onClick={() => setPanneau(false)} aria-label="Fermer"
                    style={{ marginLeft: "auto", border: "none", background: "rgba(255,255,255,.16)", color: "inherit", width: 34, height: 34,
                             borderRadius: 12, cursor: "pointer", fontSize: 18, lineHeight: 1 }}>×</button>
          </div>
        </div>
        <nav className="v2-panneau-corps" aria-label="Autres sections">
          {sections.map((s) => (
            <Link key={s.key} href={s.href} className="v2-section" onClick={() => setPanneau(false)}
                  data-actif={pathname?.startsWith(s.href) ? "oui" : "non"} data-dev={s.dev ? "oui" : "non"}>
              <span className="v2-section-ico">{ICONES_SECTIONS[s.key]}</span>
              <span style={{ minWidth: 0 }}>
                <b>{s.label}</b>
                <small>{SOUS_TITRES[s.key]}</small>
              </span>
            </Link>
          ))}
          <div style={{ flex: 1 }} />
          <button type="button" className="v2-section" onClick={() => signOut({ callbackUrl: "/login" })}>
            <span className="v2-section-ico">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></svg>
            </span>
            <span><b>Se déconnecter</b><small>Fermer la session sur cet appareil</small></span>
          </button>
        </nav>
      </aside>
    </>
  )
}
