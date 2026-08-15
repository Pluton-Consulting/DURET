"use client"

/**
 * D'OÙ VIENT LA RÉPONSE, ET CE QU'ELLE A COÛTÉ.
 *
 * L'assistant annonçait des montants, des références, des dates, sans que rien
 * ne dise sur quoi il s'appuyait. La première question d'un utilisateur devant
 * un chiffre est « tu as vu ça où », et il fallait le croire sur parole.
 *
 * Le serveur connaissait pourtant les documents consultés : chaque extrait du
 * RAG porte sa provenance en tête. Elle servait au modèle et à lui seul.
 *
 * COÛT EN JETONS : ZÉRO. Rien n'est ajouté au prompt. On transmet ce que le
 * serveur produisait déjà et jetait à la porte.
 */

import { Sources, SourcesTrigger, SourcesContent, Source } from "@/components/ai-elements/sources"

type Props = {
  /** Documents de la mémoire d'entreprise ayant nourri la réponse. */
  documents: string[]
  /** Pages web réellement consultées, s'il y en a. */
  web: string[]
  /** Une adresse a-t-elle été écartée par le garde de sécurité ? */
  webFiltre?: boolean
  /** Jetons consommés par le tour. */
  jetons?: { entree: number; sortie: number }
  /** Le modèle qui a répondu, ou « cache » quand le tour n'a rien coûté. */
  modele?: string
}

/** Un nom de fichier lisible : « devis_2026_martin.pdf » se lit mal en un coup. */
function joli(nom: string): string {
  return nom.replace(/_/g, " ").replace(/\.(pdf|docx?|xlsx?|csv|pptx?|txt|md)$/i, "")
}

export function SourcesReponse({ documents, web, webFiltre, jetons, modele }: Props) {
  const total = documents.length + web.length
  const cache = modele === "cache"
  if (!total && !jetons && !cache) return null

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 pt-1">
      {total > 0 && (
        <Sources>
          <SourcesTrigger count={total} />
          <SourcesContent>
            {documents.map((d) => (
              // PAS DE LIEN sur un document de la mémoire : il n'a pas d'adresse
              // publique, et un lien mort se lit comme une panne. Le nom situe
              // la source, c'est ce qu'on lui demande.
              <Source key={`d-${d}`} title={joli(d)}>
                <span className="block truncate text-sm">{joli(d)}</span>
              </Source>
            ))}
            {web.map((u) => (
              <Source key={`w-${u}`} href={u} title={u} target="_blank" rel="noopener noreferrer" />
            ))}
          </SourcesContent>
        </Sources>
      )}

      {webFiltre && (
        // Une réponse incomplète s'explique : sans ça, l'utilisateur croit que
        // l'assistant n'a rien trouvé, alors qu'une adresse a été refusée.
        <span className="text-xs text-muted-foreground">
          une adresse écartée par la sécurité
        </span>
      )}

      {/* LE COÛT, SANS JAUGE INVENTÉE. Le composant Context d'AI Elements
          dessine un anneau de remplissage, qui suppose de connaître la fenêtre
          maximale du modèle. Or la cascade en change à chaud, et aucune table
          fiable n'existe ici : une jauge à 12 % calculée sur un maximum
          approximatif serait un chiffre faux affiché avec assurance. On donne
          donc la mesure réelle, sans le décor. */}
      {cache ? (
        <span className="text-xs text-muted-foreground">réponse déjà connue, aucun appel</span>
      ) : jetons ? (
        <span className="text-xs text-muted-foreground tabular-nums">
          {(jetons.entree + jetons.sortie).toLocaleString("fr-FR")} jetons
          {modele ? ` · ${modele.split(":").pop()}` : ""}
        </span>
      ) : null}
    </div>
  )
}
