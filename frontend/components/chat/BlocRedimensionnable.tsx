"use client"
import { useCallback, useRef, useState } from "react"

/**
 * UN BLOC DU CHAT SE REDIMENSIONNE À LA MAIN (24/09, Noa : « comme des tableaux
 * par exemple, on doit pouvoir les agrandir en largeur ou en hauteur »).
 *
 * Première écriture : la poignée NATIVE du navigateur (`resize: both`). Noa, sur
 * la version déployée : « j'arrive pas à redimensionner les tableaux ». La poignée
 * native tient à des détails qu'on ne maîtrise pas — elle se dessine dans le coin
 * de défilement, que le tableau (lui-même défilant) recouvre, elle n'existe pas
 * partout, et rien ne dit qu'elle est là. Elle est remplacée par UNE POIGNÉE
 * MAISON : un coin visible, tiré à la souris ou au trackpad (pointer capture :
 * le geste tient même quand le curseur sort du bloc), qui pose largeur et
 * hauteur en style. Double-clic sur le coin : taille d'origine.
 *
 * Deux couches : le cadre (`sym-bloc-redim`, position relative, taille fixée par
 * la personne) et le contenu (`sym-bloc-redim-contenu`, qui défile dans le cadre).
 * La poignée est un enfant du cadre, pas du contenu : elle reste au coin quoi
 * qu'on fasse défiler. Tant que personne n'a tiré, le bloc garde sa largeur
 * commune (`--bloc-largeur`) et sa hauteur qui défile (les grands tableaux,
 * 04/09) ; dès le premier geste, l'enfant suit le cadre (`data-redim="1"`).
 * Au téléphone (≤ 640 px) la poignée n'est pas là : elle ne se saisit pas au
 * doigt et prendrait la place du contenu (mobile.css).
 */
const LARGEUR_MIN = 220
const HAUTEUR_MIN = 48

export default function BlocRedimensionnable({ children }: { children: React.ReactNode }) {
  const cadre = useRef<HTMLDivElement>(null)
  const [redimensionne, setRedimensionne] = useState(false)

  const tirer = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const el = cadre.current
    if (!el || e.button !== 0) return
    // La scène du chat écoute les gestes (balayage) : ce tirage ne la concerne pas.
    e.preventDefault()
    e.stopPropagation()
    const poignee = e.currentTarget
    const depart = { x: e.clientX, y: e.clientY, w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height }
    // Jamais plus large que la colonne du fil : au-delà, le bloc sortirait de l'écran.
    const largeurMax = el.parentElement ? el.parentElement.getBoundingClientRect().width : Infinity
    const bouger = (ev: PointerEvent) => {
      el.style.width = `${Math.round(Math.min(largeurMax, Math.max(LARGEUR_MIN, depart.w + ev.clientX - depart.x)))}px`
      el.style.height = `${Math.round(Math.max(HAUTEUR_MIN, depart.h + ev.clientY - depart.y))}px`
      setRedimensionne(true)
    }
    const lacher = () => {
      poignee.removeEventListener("pointermove", bouger)
      poignee.removeEventListener("pointerup", lacher)
      poignee.removeEventListener("pointercancel", lacher)
      try { poignee.releasePointerCapture(e.pointerId) } catch { /* déjà relâchée */ }
    }
    try { poignee.setPointerCapture(e.pointerId) } catch { /* navigateur sans capture : le geste tient tant que le curseur reste sur la poignée */ }
    poignee.addEventListener("pointermove", bouger)
    poignee.addEventListener("pointerup", lacher)
    poignee.addEventListener("pointercancel", lacher)
  }, [])

  const remettre = useCallback(() => {
    const el = cadre.current
    if (!el) return
    el.style.width = ""
    el.style.height = ""
    setRedimensionne(false)
  }, [])

  return (
    <div ref={cadre} className="sym-bloc-redim" data-redim={redimensionne ? "1" : "0"}>
      <div className="sym-bloc-redim-contenu">{children}</div>
      <div className="sym-redim-coin" role="separator" aria-label="Redimensionner le bloc"
           title={redimensionne ? "Tirer pour redimensionner · double-clic : taille d'origine" : "Tirer pour agrandir"}
           onPointerDown={tirer} onDoubleClick={remettre} />
    </div>
  )
}
