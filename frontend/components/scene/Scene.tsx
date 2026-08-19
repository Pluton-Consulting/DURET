"use client"
import { useCallback, useEffect, useState, type ReactNode } from "react"
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

  // Au montage, l'en-tête apprend la vue réelle (utile quand on arrive par /chat).
  useEffect(() => { window.dispatchEvent(new CustomEvent(EVENEMENT_VUE, { detail: vueInitiale })) }, [vueInitiale])

  return (
    <div className="v2-scene" data-vue={vue}>
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
