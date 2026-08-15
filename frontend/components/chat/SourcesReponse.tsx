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

import { useState } from "react"
import { Sources, SourcesTrigger, SourcesContent, Source } from "@/components/ai-elements/sources"
import { WebPreview, WebPreviewNavigation, WebPreviewUrl, WebPreviewBody } from "@/components/ai-elements/web-preview"

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

/** LA PAGE CONSULTÉE, MONTRÉE SUR PLACE.
 *
 *  L'agent lit des pages web pour répondre. Jusqu'ici on n'en voyait que
 *  l'adresse : pour vérifier ce qu'il y avait dessus, il fallait ouvrir un
 *  onglet et perdre le fil.
 *
 *  TROIS PRÉCAUTIONS, parce qu'on fait entrer une page étrangère dans l'écran :
 *
 *  1. Rien ne se charge tant que personne ne déplie. Un aperçu replié ne va
 *     chercher aucune page, et n'annonce donc rien au site visité.
 *  2. Seules les adresses en `https` sont proposées. L'application étant
 *     servie en HTTPS, une page en clair serait bloquée par le navigateur, et
 *     l'utilisateur verrait un cadre vide sans explication.
 *  3. Le lien vers l'onglet reste TOUJOURS offert. Beaucoup de sites refusent
 *     d'être encadrés (en-tête `X-Frame-Options`), et cela ne se détecte pas
 *     depuis la page : le cadre reste alors blanc. Sans porte de sortie, cet
 *     échec-là se lit comme une panne de l'application.
 */
function ApercuPage({ url }: { url: string }) {
  const [ouvert, setOuvert] = useState(false)
  const encadrable = url.startsWith("https://")

  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex items-center gap-2">
        {encadrable && (
          <button type="button" onClick={() => setOuvert((v) => !v)}
                  className="sym-tap shrink-0 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground"
                  aria-expanded={ouvert}>
            {ouvert ? "Masquer la page" : "Voir la page"}
          </button>
        )}
        <a href={url} target="_blank" rel="noopener noreferrer"
           className="min-w-0 flex-1 truncate text-xs text-muted-foreground underline-offset-2 hover:underline">
          {url}
        </a>
      </div>
      {ouvert && encadrable && (
        <WebPreview defaultUrl={url} className="h-80 overflow-hidden rounded-lg border border-border">
          <WebPreviewNavigation>
            <WebPreviewUrl readOnly />
          </WebPreviewNavigation>
          <WebPreviewBody title={`Aperçu de ${url}`} />
        </WebPreview>
      )}
    </div>
  )
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
              <ApercuPage key={`w-${u}`} url={u} />
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
