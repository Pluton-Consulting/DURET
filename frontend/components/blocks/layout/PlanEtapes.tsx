"use client"

import { md } from "../text/inline"
/**
 * LE PLAN D'UNE GROSSE DEMANDE, ET CE QUE CHAQUE ÉTAPE A DONNÉ.
 *
 * Une demande qui tient en une phrase — « analyse les devis du Drive, puis
 * refais-en un et un cahier des charges assortis » — occupe en réalité
 * trente-neuf étapes et seize minutes. Pendant ce temps l'écran ne montrait
 * qu'une ligne d'activité qui se remplace, puis, tout à la fin, deux fichiers.
 * Entre les deux, rien : impossible de savoir ce qui avait été trouvé, ni de
 * corriger le tir avant la fin.
 *
 * Ce bloc rend le plan lui-même : les étapes annoncées, leur état, et sous
 * chacune ce qu'elle a produit. C'est `Plan` d'AI Elements pour le cadre et
 * `Task` pour chaque étape — l'un et l'autre repliables, ce qui compte quand
 * le plan tient dix points.
 *
 * L'ÉTAT EST DIT PAR LE MODÈLE, jamais deviné : une étape sans `etat` est
 * simplement à faire. On ne coche rien à sa place — c'est exactement le
 * travers qu'on venait de corriger sur la frise de validation.
 */

import {
  Plan, PlanHeader, PlanTitle, PlanDescription, PlanContent,
} from "@/components/ai-elements/plan"
import { Task, TaskTrigger, TaskContent, TaskItem } from "@/components/ai-elements/task"

type Etat = "fait" | "en_cours" | "a_faire"

type Etape = {
  titre: string
  etat?: Etat
  /** Ce que l'étape a donné : constats, chiffres, décisions. */
  resultats?: string[]
}

const PUCE: Record<Etat, { signe: string; couleur: string; libelle: string }> = {
  fait:     { signe: "✓", couleur: "var(--marque-primary)",     libelle: "terminée" },
  en_cours: { signe: "•", couleur: "var(--marque-pending-text)", libelle: "en cours" },
  a_faire:  { signe: "",  couleur: "var(--marque-text-muted)",   libelle: "à faire" },
}

export function PlanEtapes({ titre, resume, etapes = [] }: {
  titre?: string
  resume?: string
  etapes?: Etape[]
}) {
  return (
    <Plan className="w-full" defaultOpen>
      {(titre || resume) && (
        <PlanHeader>
          {titre && <PlanTitle>{titre}</PlanTitle>}
          {resume && <PlanDescription>{resume}</PlanDescription>}
        </PlanHeader>
      )}
      <PlanContent className="flex flex-col gap-3">
        {etapes.map((e, i) => {
          const etat = PUCE[e.etat ?? "a_faire"]
          const faits = e.resultats ?? []
          return (
            <Task key={i} defaultOpen={faits.length > 0}>
              <TaskTrigger title={e.titre}>
                <div className="flex w-full cursor-pointer items-center gap-2 text-sm">
                  {/* La pastille porte l'état ET son mot : une couleur seule
                      ne se lit pas quand on distingue mal les teintes. */}
                  <span
                    aria-label={etat.libelle}
                    title={etat.libelle}
                    className="grid size-5 shrink-0 place-items-center rounded-full border text-[11px] font-bold"
                    style={{ borderColor: etat.couleur, color: etat.couleur }}
                  >
                    {etat.signe || i + 1}
                  </span>
                  <span className="min-w-0 flex-1 text-left text-foreground">{e.titre}</span>
                </div>
              </TaskTrigger>
              {faits.length > 0 && (
                <TaskContent className="mt-1 flex flex-col gap-1 pl-7">
                  {faits.map((r, j) => (
                    <TaskItem key={j}>{md(r)}</TaskItem>
                  ))}
                </TaskContent>
              )}
            </Task>
          )
        })}
      </PlanContent>
    </Plan>
  )
}
