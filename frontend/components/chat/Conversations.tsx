"use client"

/**
 * Le choix de la conversation — la même sur PC et sur téléphone (09/09).
 *
 * Demande de Noa : « pour chaque utilisateur, la conversation doit se
 * conserver sur téléphone et PC pour qu'il ait la suite de la conversation
 * sur PC, téléphone, etc. ». Les fils vivaient déjà sur le serveur, par
 * personne ; mais l'écran ne retenait le fil courant QUE dans le stockage
 * local du navigateur : un autre appareil ouvrait une conversation neuve, et
 * rien ne permettait de reprendre une conversation passée — ni d'en ouvrir
 * une nouvelle volontairement.
 *
 * Ici : la liste des conversations de la personne (celle du serveur, donc
 * la même partout), la reprise d'une conversation, et « Nouvelle
 * conversation ». Bibliothèque d'abord (menu shadcn), pas de sur-mesure.
 */
import { Button } from "@/components/ui/button"
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

export interface FilConversation {
  thread_id: string
  titre: string
  updated_at?: string | null
  agent_type?: string | null
}

/** Une date en mots courts : « à l'instant », « il y a 12 min », « hier 14:02 », « 3 sept. ». */
export function libelleDate(iso?: string | null, maintenant: Date = new Date()): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const ecart = (maintenant.getTime() - d.getTime()) / 1000
  if (ecart < 60) return "à l'instant"
  if (ecart < 3600) return `il y a ${Math.floor(ecart / 60)} min`
  const heure = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
  const memeJour = d.toDateString() === maintenant.toDateString()
  if (memeJour) return heure
  const hier = new Date(maintenant); hier.setDate(hier.getDate() - 1)
  if (d.toDateString() === hier.toDateString()) return `hier ${heure}`
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "short" })
}

export function titreCourt(titre?: string | null, max = 48): string {
  const t = (titre || "").replace(/\s+/g, " ").trim()
  if (!t) return "Nouvelle conversation"
  return t.length > max ? t.slice(0, max - 1).trimEnd() + "…" : t
}

interface Props {
  fils: FilConversation[]
  courant: string | null
  /** Un tour en vol : on ne change pas de conversation sous lui. */
  occupe: boolean
  onNouvelle: () => void
  onReprendre: (threadId: string) => void
}

export default function Conversations({ fils, courant, occupe, onNouvelle, onReprendre }: Props) {
  const actuel = fils.find((f) => f.thread_id === courant)
  const libelle = courant ? titreCourt(actuel?.titre || "Conversation en cours") : "Nouvelle conversation"
  return (
    <div className="v2-fils" data-testid="conversations">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button type="button" variant="ghost" size="sm" className="v2-fils-choix"
                  title="Vos conversations — les mêmes sur tous vos appareils"
                  data-testid="conversations-choix">
            <span className="v2-fils-titre">{libelle}</span>
            <span aria-hidden="true" className="v2-fils-chevron">▾</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="v2-fils-menu">
          <DropdownMenuLabel>Vos conversations</DropdownMenuLabel>
          {fils.length === 0 && (
            <DropdownMenuItem disabled>Aucune conversation encore</DropdownMenuItem>
          )}
          {fils.map((f) => (
            <DropdownMenuItem key={f.thread_id} disabled={occupe || f.thread_id === courant}
                              onSelect={() => onReprendre(f.thread_id)}
                              data-testid="conversation-item">
              <span className="v2-fils-item-titre">{titreCourt(f.titre, 60)}</span>
              <span className="v2-fils-item-date">{libelleDate(f.updated_at)}</span>
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled={occupe} onSelect={onNouvelle} data-testid="conversation-nouvelle">
            + Nouvelle conversation
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Button type="button" variant="ghost" size="sm" onClick={onNouvelle} disabled={occupe}
              title={occupe ? "Attendez la fin de la demande en cours" : "Commencer une nouvelle conversation"}
              data-testid="nouvelle-conversation">
        + Nouvelle
      </Button>
    </div>
  )
}
