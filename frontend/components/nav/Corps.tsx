"use client"
import { usePathname } from "next/navigation"
import type { ReactNode } from "react"

/**
 * Le corps de page sous l'en-tête flottant. La scène (tableau de bord + chat)
 * gère elle-même son espace sous les bulles ; les autres pages reçoivent le
 * dégagement ici, pour qu'aucune d'elles n'ait à le connaître.
 */
export default function Corps({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const scene = pathname === "/accueil" || pathname === "/" || pathname?.startsWith("/chat")
  if (scene) return <main>{children}</main>
  return <main className="v2-page sym-fade">{children}</main>
}
