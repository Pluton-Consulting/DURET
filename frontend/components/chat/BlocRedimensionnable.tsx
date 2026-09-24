"use client"
import { useEffect, useRef, useState } from "react"

/**
 * UN BLOC DU CHAT SE REDIMENSIONNE À LA MAIN (24/09, Noa : « comme des tableaux
 * par exemple, on doit pouvoir les agrandir en largeur ou en hauteur »).
 *
 * La poignée est celle du navigateur (`resize: both`, coin bas-droit) : rien à
 * réinventer, elle marche à la souris et au trackpad. Tant que personne n'a tiré
 * dessus, le bloc garde sa largeur commune (`--bloc-largeur`) et sa hauteur qui
 * défile (les grands tableaux, 04/09). Dès le premier redimensionnement, l'enfant
 * suit le cadre : sa largeur maximale et sa hauteur maximale cèdent, c'est la
 * personne qui décide. Au téléphone (≤ 640 px), pas de poignée : elle ne se
 * saisit pas au doigt et prendrait la place du contenu (mobile.css).
 */
export default function BlocRedimensionnable({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [redimensionne, setRedimensionne] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === "undefined") return
    let initiale: { w: number; h: number } | null = null
    const obs = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect
      if (!initiale) { initiale = { w: width, h: height }; return }
      // Une différence de quelques pixels vient d'un reflow (police chargée,
      // fenêtre réduite), pas d'une main : on n'y touche pas.
      if (Math.abs(width - initiale.w) > 12 || Math.abs(height - initiale.h) > 12) setRedimensionne(true)
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])
  return (
    <div ref={ref} className="sym-bloc-redim" data-redim={redimensionne ? "1" : "0"}
         title={redimensionne ? undefined : "Tirer le coin pour agrandir"}>
      {children}
    </div>
  )
}
