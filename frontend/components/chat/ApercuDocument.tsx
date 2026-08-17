"use client"

/**
 * LE PONT ENTRE UN DOCUMENT DE L'ENTREPRISE ET UNE VISIONNEUSE EXTEND UI.
 *
 * Les visionneuses ne savent PAS aller chercher un fichier protégé : elles
 * font un `fetch(url)` nu, sans en-tête. Or tous les documents d'ici sont
 * derrière un jeton. Ce composant fait donc le trajet lui-même — récupération
 * authentifiée, puis URL d'objet locale — et règle au passage les quatre
 * pièges relevés à la lecture du code des visionneuses :
 *
 *   1. AUCUNE n'accepte un Blob. Trois veulent une URL (docx, xlsx, pdf), la
 *      quatrième veut le TEXTE brut (csv).
 *   2. Le DOCX exige un nom finissant par « .docx ». Et l'échec est SILENCIEUX :
 *      le composant guette un message d'erreur qui ne correspond plus à celui
 *      de la version installée de la bibliothèque. Un nom sans extension
 *      donnerait un cadre vide, sans explication. On corrige le nom ici — c'est
 *      exactement la panne qu'on a déjà vue côté serveur avec « test 2 ».
 *   3. Aucune ne révoque l'URL d'objet qu'on lui passe : sans ménage, chaque
 *      aperçu fuit sa mémoire.
 *   4. `isDark` / `onIsDarkChange` sont OBLIGATOIRES sur docx et xlsx, sans
 *      valeur par défaut.
 *
 * Les visionneuses portent leurs propres classes Tailwind, donc les couleurs
 * de la charte via `theme.css` : rien à repeindre ici.
 */

import * as React from "react"
import dynamic from "next/dynamic"

// LES VISIONNEUSES SE TÉLÉCHARGENT QUAND ON REGARDE UN DOCUMENT, PAS AVANT.
//
// Importées normalement, elles entrent dans le paquet de la page de chat :
// mesuré, l'écran passait de 124 ko à 1,64 Mo, payés à CHAQUE ouverture du
// chat — y compris par les conversations qui ne montrent aucun document.
// Sur un VPN, c'est plusieurs secondes d'attente avant le premier message.
//
// Ces quatre-là ne savent de toute façon travailler que dans un navigateur
// (canevas, worker, WebAssembly), d'où `ssr: false` : les rendre côté
// serveur ne produirait rien et coûterait un aller-retour.
const chargement = () => (
  <div className="sym-skeleton" style={{ height: "100%", width: "100%" }}
       aria-label="Chargement de la visionneuse" />
)
const DocxViewerPreview = dynamic(
  () => import("@/components/extend/docx-viewer").then((m) => m.DocxViewerPreview),
  { ssr: false, loading: chargement })
const XlsxViewerPreview = dynamic(
  () => import("@/components/extend/xlsx-viewer").then((m) => m.XlsxViewerPreview),
  { ssr: false, loading: chargement })
const CsvViewer = dynamic(
  () => import("@/components/extend/csv-viewer").then((m) => m.CsvViewer),
  { ssr: false, loading: chargement })
const PDFViewer = dynamic(
  () => import("@/components/extend/pdf-viewer").then((m) => m.PDFViewer),
  { ssr: false, loading: chargement })
const PptxViewerPreview = dynamic(
  () => import("@/components/extend/pptx-viewer").then((m) => m.PptxViewerPreview),
  { ssr: false, loading: chargement })

/** NI TÉLÉCHARGER, NI REMPLACER : LA VISIONNEUSE MONTRE, C'EST TOUT.
 *
 *  Chaque visionneuse arrive avec son propre menu « Download » et « Upload ».
 *
 *  Le téléchargement faisait DOUBLON : la carte au-dessus en porte déjà un,
 *  et c'est celui-là qu'il faut, parce qu'il passe par le jeton et rend le
 *  fichier sous son vrai nom. Deux boutons pour un seul geste, dans un cadre
 *  de quelques centimètres, se lisent comme une erreur d'affichage.
 *
 *  « Upload » était pire que redondant : il remplace le document affiché par
 *  un fichier pris sur le poste. L'aperçu cesserait alors de montrer ce que
 *  l'assistant a réellement produit, sans que rien ne le signale, dans un
 *  cadre où l'on vient justement vérifier le travail rendu. */
const SANS_FICHIER = { showDownload: false, showUpload: false } as const

/** Formats que l'on sait afficher, et rien d'autre. */
export type FormatApercu = "docx" | "xlsx" | "csv" | "pdf" | "pptx"

const EXTENSIONS: Record<FormatApercu, string> = {
  docx: ".docx",
  xlsx: ".xlsx",
  csv: ".csv",
  pdf: ".pdf",
  pptx: ".pptx",
}

/** Le nom que la bibliothèque doit voir : elle valide l'extension, pas le type
 *  MIME. Un « test 2 » sans extension casse le lecteur DOCX en silence. */
function nomValide(nom: string | undefined, format: FormatApercu): string {
  const base = (nom || "document").trim() || "document"
  const attendue = EXTENSIONS[format]
  return base.toLowerCase().endsWith(attendue) ? base : `${base}${attendue}`
}

export function formatDepuisNom(nom: string | undefined): FormatApercu | null {
  const n = (nom || "").toLowerCase()
  if (n.endsWith(".docx") || n.endsWith(".doc")) return "docx"
  if (n.endsWith(".xlsx") || n.endsWith(".xls")) return "xlsx"
  if (n.endsWith(".csv") || n.endsWith(".tsv")) return "csv"
  if (n.endsWith(".pdf")) return "pdf"
  if (n.endsWith(".pptx") || n.endsWith(".ppt")) return "pptx"
  return null
}

type Props = {
  /** Chemin de l'API, ex. « /api/documents/<jeton> ». */
  url: string
  format: FormatApercu
  nom?: string
  apiUrl?: string
  backendToken?: string
  /** Hauteur de la zone. Les visionneuses posent 640px en dur ; on surcharge. */
  hauteur?: number
}

export function ApercuDocument({
  url,
  format,
  nom,
  apiUrl,
  backendToken,
  hauteur = 460,
}: Props) {
  const [objectUrl, setObjectUrl] = React.useState<string>()
  const [texte, setTexte] = React.useState<string>()
  const [erreur, setErreur] = React.useState<string>()
  const [sombre, setSombre] = React.useState(false)
  // Un incident réseau ne doit pas être une impasse : incrémenter relance
  // l'effet de récupération, sans rien remonter ni recharger la visionneuse.
  const [essai, setEssai] = React.useState(0)

  React.useEffect(() => {
    let vivant = true
    let cree: string | undefined

    const recuperer = async () => {
      setErreur(undefined)
      try {
        const base = apiUrl || ""
        const reponse = await fetch(url.startsWith("http") ? url : `${base}${url}`, {
          headers: backendToken ? { Authorization: `Bearer ${backendToken}` } : {},
        })
        if (!reponse.ok) throw new Error(`réponse ${reponse.status}`)
        const blob = await reponse.blob()
        if (!vivant) return

        if (format === "csv") {
          // Le CSV veut du TEXTE, pas une URL. `blob.text()` décode en UTF-8 ;
          // un export Excel français est souvent en windows-1252, et les
          // accents sortiraient en charabia. On détecte le cas plutôt que de
          // livrer un tableau illisible.
          const octets = await blob.arrayBuffer()
          if (!vivant) return
          const utf8 = new TextDecoder("utf-8", { fatal: false }).decode(octets)
          const suspect = utf8.includes("�")
          setTexte(suspect
            ? new TextDecoder("windows-1252").decode(octets)
            : utf8)
          return
        }

        cree = URL.createObjectURL(blob)
        setObjectUrl(cree)
      } catch (e) {
        if (vivant) {
          setErreur(e instanceof Error ? e.message : "document illisible")
        }
      }
    }

    recuperer()
    return () => {
      vivant = false
      // AUCUNE visionneuse ne libère l'URL qu'on lui a passée : sans ce
      // ménage, chaque aperçu affiché garde son fichier en mémoire.
      if (cree) URL.revokeObjectURL(cree)
    }
  }, [url, format, apiUrl, backendToken, essai])

  if (erreur) {
    return (
      <div
        className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
        role="status"
      >
        <span>Aperçu indisponible ({erreur}). Le fichier reste téléchargeable.</span>
        <button
          type="button"
          onClick={() => { setErreur(undefined); setEssai((n) => n + 1) }}
          className="sym-tap rounded-full border border-border px-3 py-1 text-[12.5px]"
          data-testid="reessayer-apercu"
        >
          Réessayer
        </button>
      </div>
    )
  }

  const enAttente = format === "csv" ? texte === undefined : objectUrl === undefined
  if (enAttente) {
    return (
      <div
        className="sym-skeleton"
        style={{ height: hauteur, width: "100%" }}
        aria-label="Chargement de l'aperçu"
      />
    )
  }

  const nomFichier = nomValide(nom, format)
  const cadre = "overflow-hidden rounded-lg border border-border bg-card"

  if (format === "csv") {
    return (
      <div className={cadre} style={{ height: hauteur }}>
        <CsvViewer data={texte} search className="h-full w-full" />
      </div>
    )
  }

  if (format === "xlsx") {
    return (
      <div className={cadre} style={{ height: hauteur }}>
        <XlsxViewerPreview
          src={objectUrl}
          fileName={nomFichier}
          isDark={sombre}
          onIsDarkChange={setSombre}
          {...SANS_FICHIER}
          className="h-full w-full"
        />
      </div>
    )
  }

  if (format === "pptx") {
    return (
      <div className={cadre} style={{ height: hauteur }}>
        <PptxViewerPreview src={objectUrl} fileName={nomFichier} {...SANS_FICHIER}
                           className="h-full w-full" />
      </div>
    )
  }

  if (format === "pdf") {
    return (
      <div className={cadre} style={{ height: hauteur }}>
        <PDFViewer src={objectUrl} fileName={nomFichier} {...SANS_FICHIER}
                   className="h-full w-full" />
      </div>
    )
  }

  return (
    <div className={cadre} style={{ height: hauteur }}>
      <DocxViewerPreview
        src={objectUrl}
        fileName={nomFichier}
        isDark={sombre}
        onIsDarkChange={setSombre}
        {...SANS_FICHIER}
        className="h-full w-full"
      />
    </div>
  )
}
