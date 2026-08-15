"use client"

/**
 * LE RAISONNEMENT QUI DÉFILE PENDANT L'ATTENTE.
 *
 * Une ligne unique disait ce que l'assistant fait à l'instant. C'est utile,
 * mais ça efface tout : au bout de quarante secondes, on ne sait plus par où
 * il est passé, ni combien d'étapes il a franchies. Et quand rien n'aboutit,
 * on n'a aucun moyen de dire OÙ ça a coincé.
 *
 * Ici, l'étape en cours reste en tête, et les précédentes s'empilent en
 * dessous, consultables d'un clic. Le repli est ouvert pendant le travail et
 * se referme seul une seconde après la fin, pour ne pas encombrer le fil une
 * fois la réponse arrivée.
 *
 * COÛT EN JETONS : ZÉRO. Rien n'est demandé au modèle. Chaque phrase vient
 * d'un événement que le serveur émettait déjà et que l'écran jetait.
 */

import { useEffect, useRef } from "react"
import {
  Reasoning,
  ReasoningTrigger,
  ReasoningContent,
  useReasoning,
} from "@/components/ai-elements/reasoning"
import { Shimmer } from "@/components/ai-elements/shimmer"

/** La grille de neuf points, reprise du repère d'attente. */
function Grille() {
  return (
    <span className="sym-grille shrink-0" aria-hidden="true">
      <i /><i /><i /><i /><i /><i /><i /><i /><i />
    </span>
  )
}

/** Ce que porte la ligne d'en-tête : l'étape en cours, ou le bilan une fois fini. */
function Entete({ activite, nombre }: { activite: string; nombre: number }) {
  const { isStreaming, isOpen, duration } = useReasoning()

  if (isStreaming) {
    return (
      <>
        <Grille />
        {/* La `key` remonte l'élément à chaque changement d'étape et rejoue
            l'apparition : sans elle, le texte se remplacerait sur place, et
            rien ne signalerait que l'assistant a avancé. */}
        <span className="sym-step min-w-0 flex-1 text-left" key={activite || "depart"}>
          <Shimmer as="span">{activite || "je démarre"}</Shimmer>
        </span>
        <ChevronReplie ouvert={isOpen} />
      </>
    )
  }

  // Une fois terminé, la ligne devient un bilan consultable plutôt qu'un
  // indicateur : « 7 étapes, 12 secondes » situe le travail fourni.
  const etapes = nombre > 1 ? `${nombre} étapes` : "1 étape"
  const secondes = typeof duration === "number" && duration > 0 ? `, ${duration} s` : ""
  return (
    <>
      <Grille />
      <span className="min-w-0 flex-1 text-left text-[13px]">
        Raisonnement ({etapes}{secondes})
      </span>
      <ChevronReplie ouvert={isOpen} />
    </>
  )
}

function ChevronReplie({ ouvert }: { ouvert: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" aria-hidden="true"
         className="shrink-0 transition-transform duration-200"
         style={{ transform: ouvert ? "rotate(180deg)" : undefined, opacity: .55 }}>
      <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2"
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

type Props = {
  /** Ce que l'assistant fait à l'instant. */
  activite: string
  /** Toutes les étapes franchies, dans l'ordre. */
  trace: string[]
  /** Un tour est-il en cours ? */
  enCours: boolean
}

export function ReflexionEnCours({ activite, trace, enCours }: Props) {
  const zone = useRef<HTMLDivElement>(null)

  // LA VUE SUIT LA DERNIÈRE ÉTAPE. Sans cela, le dépliant garde le début du
  // raisonnement à l'écran pendant que le travail continue plus bas : on
  // regarde une trace figée en croyant qu'elle est à jour.
  useEffect(() => {
    const boite = zone.current
    if (boite) boite.scrollTop = boite.scrollHeight
  }, [trace.length])

  if (!enCours && trace.length === 0) return null

  // Une liste markdown : Streamdown la rend en puces, et chaque étape garde
  // sa ligne même quand elle est longue.
  const contenu = trace.map((l) => `- ${l}`).join("\n")

  return (
    <div className="px-8 py-2" role="status" aria-live="polite">
      <Reasoning
        isStreaming={enCours}
        className="rounded-lg border border-border bg-card px-3 py-2"
      >
        <ReasoningTrigger className="gap-3 text-foreground">
          <Entete activite={activite} nombre={trace.length} />
        </ReasoningTrigger>
        <ReasoningContent
          ref={zone}
          className="mt-2 max-h-44 overflow-y-auto pr-1 text-[13px] leading-relaxed"
        >
          {contenu}
        </ReasoningContent>
      </Reasoning>
    </div>
  )
}
