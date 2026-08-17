"use client"

/**
 * LE RAISONNEMENT QUI DÉFILE PENDANT L'ATTENTE.
 *
 * Une ligne unique disait ce que l'assistant fait à l'instant. C'est utile,
 * mais ça efface tout : au bout de quarante secondes, on ne sait plus combien
 * d'étapes il a franchies. La ligne dit donc l'étape en cours pendant le
 * travail, puis devient un bilan — « 17 étapes, 335 s » — une fois fini.
 *
 * LE DÉPLIANT A ÉTÉ RETIRÉ. Il listait les étapes déjà franchies, c'est-à-dire
 * exactement les phrases qui venaient de défiler ici même, et que la colonne
 * de droite résume déjà par grandes étapes. Ouvrir ne montrait rien de neuf.
 * Il traînait en plus deux défauts que ce retrait supprime avec lui : la carte
 * ne se refermait pas tant que le tour durait (un effet la rouvrait à chaque
 * clic), et son fond blanc posait un rectangle de plus dans le fil.
 *
 * COÛT EN JETONS : ZÉRO. Rien n'est demandé au modèle. Chaque phrase vient
 * d'un événement que le serveur émettait déjà et que l'écran jetait.
 */

import { useEffect, useRef, useState } from "react"
import { Shimmer } from "@/components/ai-elements/shimmer"

/** La grille de neuf points, reprise du repère d'attente. */
function Grille() {
  return (
    <span className="sym-grille shrink-0" aria-hidden="true">
      <i /><i /><i /><i /><i /><i /><i /><i /><i />
    </span>
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
  // LA DURÉE EST MESURÉE ICI, faute de dépliant pour la tenir. Le départ est
  // pris au premier rendu où le tour est en cours, l'arrêt quand il retombe.
  const debut = useRef<number | null>(null)
  const [duree, setDuree] = useState<number | null>(null)

  useEffect(() => {
    if (enCours) {
      if (debut.current === null) { debut.current = Date.now(); setDuree(null) }
    } else if (debut.current !== null) {
      setDuree(Math.ceil((Date.now() - debut.current) / 1000))
      debut.current = null
    }
  }, [enCours])

  if (!enCours && trace.length === 0) return null

  const etapes = trace.length > 1 ? `${trace.length} étapes` : "1 étape"
  const secondes = duree && duree > 0 ? `, ${duree} s` : ""

  return (
    <div className="px-8 py-2" role="status" aria-live="polite">
      {/* Pas de fond : la ligne se pose sur le fil, elle n'y ajoute pas une
          carte. Seul un liseré discret la rattache au message qui vient. */}
      <div className="flex w-full items-center gap-3 rounded-lg border border-border bg-transparent px-3 py-2 text-muted-foreground">
        <Grille />
        {enCours ? (
          // La `key` remonte l'élément à chaque changement d'étape et rejoue
          // l'apparition : sans elle, le texte se remplacerait sur place, et
          // rien ne signalerait que l'assistant a avancé.
          <span className="sym-step min-w-0 flex-1 text-left" key={activite || "depart"}>
            <Shimmer as="span">{activite || "je démarre"}</Shimmer>
          </span>
        ) : (
          <span className="min-w-0 flex-1 text-left text-[13px]">
            Raisonnement ({etapes}{secondes})
          </span>
        )}
      </div>
    </div>
  )
}
