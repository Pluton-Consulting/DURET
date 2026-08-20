"use client"
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { EVENEMENT_VUE } from "@/components/nav/EnTete"

/**
 * LA SCÈNE : deux vues côte à côte, et l'autre qui déborde toujours un peu.
 *
 * Le tableau de bord et le chat ne sont pas deux pages : ce sont deux cadres
 * posés sur une même piste deux fois plus large que l'écran. On en voit un ;
 * l'autre dépasse de quelques pour cent sur le bord, légèrement reculé — son
 * coin arrondi suffit à dire qu'il est là. Cliquer sur le switch de l'en-tête,
 * ou sur ce bord qui dépasse, fait GLISSER la piste : la vue arrive de la
 * droite (le chat) ou de la gauche (le tableau de bord), en une courbe unique.
 *
 * Les deux vues restent MONTÉES. C'est ce qui rend le passage instantané et
 * ce qui garde le chat exactement où on l'a laissé — une réponse en cours ne
 * se perd pas parce qu'on est allé jeter un œil au tableau de bord.
 *
 * L'URL suit (`/accueil`, `/chat`) sans navigation : l'historique du
 * navigateur reste juste, un lien partagé ouvre la bonne vue, et le bouton
 * « précédent » refait glisser la piste au lieu de recharger.
 */
interface Props {
  vueInitiale: "tableau" | "chat"
  tableau: ReactNode
  chat: ReactNode
}

const CHEMINS: Record<"tableau" | "chat", string> = { tableau: "/accueil", chat: "/chat" }

export default function Scene({ vueInitiale, tableau, chat }: Props) {
  const [vue, setVue] = useState<"tableau" | "chat">(vueInitiale)

  const aller = useCallback((cible: "tableau" | "chat", pousser = true) => {
    setVue(cible)
    window.dispatchEvent(new CustomEvent(EVENEMENT_VUE, { detail: cible }))
    if (pousser && typeof window !== "undefined" && window.location.pathname !== CHEMINS[cible]) {
      window.history.pushState({ vue: cible }, "", CHEMINS[cible])
    }
  }, [])

  // Le switch de l'en-tête demande ; la scène dispose.
  useEffect(() => {
    const h = (e: Event) => aller((e as CustomEvent).detail)
    window.addEventListener(EVENEMENT_VUE + ":demande", h)
    return () => window.removeEventListener(EVENEMENT_VUE + ":demande", h)
  }, [aller])

  // Le bouton « précédent » du navigateur refait glisser au lieu de recharger.
  useEffect(() => {
    const h = () => {
      const p = window.location.pathname
      aller(p.startsWith("/chat") ? "chat" : "tableau", false)
    }
    window.addEventListener("popstate", h)
    return () => window.removeEventListener("popstate", h)
  }, [aller])

  // Au montage, la scène SE DÉCLARE (l'en-tête saura que cliquer sur le switch
  // doit faire glisser, pas naviguer) et annonce la vue réelle — utile quand
  // on arrive directement par /chat.
  useEffect(() => {
    document.documentElement.setAttribute("data-v2-scene", "oui")
    window.dispatchEvent(new CustomEvent(EVENEMENT_VUE, { detail: vueInitiale }))
    return () => { document.documentElement.removeAttribute("data-v2-scene") }
  }, [vueInitiale])

  // ── LE GESTE : deux doigts vers la gauche ou la droite, et la vue suit ──
  //
  // Trois gardes, toutes indispensables :
  //  * le geste doit être FRANCHEMENT horizontal (deux fois plus large que
  //    haut), sinon le défilement vertical du tableau de bord déclencherait
  //    des allers-retours ;
  //  * il ne compte pas au-dessus d'un contenu qui défile horizontalement
  //    (un tableau large, une rangée de suggestions) : ce défilement-là a
  //    la priorité, c'est lui que la personne visait ;
  //  * un seul déclenchement par geste — un trackpad émet des dizaines
  //    d'événements par seconde, on s'arme, on tire, on attend le calme.
  const cumulRef = useRef(0)
  const armeRef = useRef(true)
  const reposRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const vueRef = useRef(vue)
  vueRef.current = vue

  const surUnDefilementHorizontal = (depart: EventTarget | null): boolean => {
    let e = depart as HTMLElement | null
    while (e && !e.classList?.contains("v2-scene")) {
      if (e.scrollWidth > e.clientWidth + 2) {
        const s = getComputedStyle(e)
        if (s.overflowX === "auto" || s.overflowX === "scroll") return true
      }
      e = e.parentElement
    }
    return false
  }

  const surMolette = (e: React.WheelEvent) => {
    if (Math.abs(e.deltaX) < Math.abs(e.deltaY) * 2) return
    if (surUnDefilementHorizontal(e.target)) return
    if (reposRef.current) clearTimeout(reposRef.current)
    reposRef.current = setTimeout(() => { cumulRef.current = 0; armeRef.current = true }, 220)
    if (!armeRef.current) return
    cumulRef.current += e.deltaX
    const SEUIL = 90
    if (cumulRef.current > SEUIL && vueRef.current === "tableau") {
      armeRef.current = false; aller("chat")
    } else if (cumulRef.current < -SEUIL && vueRef.current === "chat") {
      armeRef.current = false; aller("tableau")
    }
  }

  const toucheRef = useRef<{ x: number; y: number } | null>(null)
  const surToucheDebut = (e: React.TouchEvent) => {
    toucheRef.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }
  }
  const surToucheFin = (e: React.TouchEvent) => {
    const d = toucheRef.current; toucheRef.current = null
    if (!d) return
    const dx = e.changedTouches[0].clientX - d.x
    const dy = e.changedTouches[0].clientY - d.y
    if (Math.abs(dx) < 70 || Math.abs(dx) < Math.abs(dy) * 1.5) return
    if (surUnDefilementHorizontal(e.target)) return
    if (dx < 0 && vueRef.current === "tableau") aller("chat")
    else if (dx > 0 && vueRef.current === "chat") aller("tableau")
  }

  return (
    <div className="v2-scene" data-vue={vue} onWheel={surMolette}
         onTouchStart={surToucheDebut} onTouchEnd={surToucheFin}>
      <div className="v2-piste">
        <section className="v2-vue v2-vue-tableau" aria-hidden={vue !== "tableau"}
                 onClick={vue === "chat" ? () => aller("tableau") : undefined}>
          <div className="v2-vue-cadre" style={{ pointerEvents: vue === "tableau" ? "auto" : "none" }}>
            <div className="v2-vue-defile">{tableau}</div>
          </div>
        </section>
        <section className="v2-vue v2-vue-chat" aria-hidden={vue !== "chat"}
                 onClick={vue === "tableau" ? () => aller("chat") : undefined}>
          <div className="v2-vue-cadre" style={{ pointerEvents: vue === "chat" ? "auto" : "none" }}>
            {chat}
          </div>
        </section>
      </div>
    </div>
  )
}
