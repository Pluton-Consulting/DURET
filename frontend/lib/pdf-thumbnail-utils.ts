import type { PdfDocumentObject, PdfEngine } from "@embedpdf/models"

// LE MOTEUR PDF EST SERVI PAR NOUS, PAS PAR UN CDN.
//
// Le composant d'origine chargeait ce binaire depuis cdn.jsdelivr.net. Cette
// application tourne en HTTP sur un VPN Headscale fermé : rien ne garantit
// qu'un poste puisse joindre un CDN public, et l'aperçu d'un PDF échouerait
// alors sans que la cause soit visible à l'écran.
//
// Le fichier vient du paquet `@embedpdf/pdfium` déjà installé, copié dans
// `public/pdfium/`. Il pèse 4,5 Mo, mais il n'est téléchargé qu'à la PREMIÈRE
// ouverture d'un PDF (l'import est dynamique), puis mis en cache par le
// navigateur : aucun coût pour les tours qui n'affichent pas de document.
//
// À la mise à jour du paquet, recopier le binaire :
//   cp node_modules/@embedpdf/pdfium/dist/pdfium.wasm public/pdfium/
const PDFIUM_WASM_URL = "/pdfium/pdfium.wasm"

let sharedEnginePromise: Promise<PdfEngine> | null = null
const pdfDocumentCache = new Map<string, Promise<PdfDocumentObject>>()
const thumbnailUrlCache = new Map<string, Promise<string | null>>()

export function loadSharedPdfEngine() {
  sharedEnginePromise ??= import("@embedpdf/engines/pdfium-worker-engine").then(
    ({ createPdfiumEngine }) => createPdfiumEngine(PDFIUM_WASM_URL, {})
  )

  return sharedEnginePromise
}

export async function loadPdfDocument(url: string) {
  let documentPromise = pdfDocumentCache.get(url)

  if (!documentPromise) {
    documentPromise = loadSharedPdfEngine().then((engine) =>
      engine
        .openDocumentUrl(
          { id: url, url },
          { mode: url.startsWith("blob:") ? "full-fetch" : "auto" }
        )
        .toPromise()
    )
    pdfDocumentCache.set(url, documentPromise)
  }

  return documentPromise
}

export async function getPdfPageCount(url: string) {
  return (await loadPdfDocument(url)).pageCount
}

export function renderPdfThumbnailUrl({
  dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1,
  pageIndex,
  url,
  width,
}: {
  dpr?: number
  pageIndex: number
  url: string
  width: number
}) {
  const cacheKey = `${url}#${pageIndex}@${width}x${dpr}`
  let thumbnailPromise = thumbnailUrlCache.get(cacheKey)

  if (!thumbnailPromise) {
    thumbnailPromise = (async () => {
      const [engine, document] = await Promise.all([
        loadSharedPdfEngine(),
        loadPdfDocument(url),
      ])
      const page = document.pages[pageIndex]

      if (!page) return null

      const blob = await engine
        .renderThumbnail(document, page, {
          dpr,
          imageType: "image/png",
          scaleFactor: width / page.size.width,
          withAnnotations: true,
        })
        .toPromise()

      return URL.createObjectURL(blob)
    })()
    thumbnailUrlCache.set(cacheKey, thumbnailPromise)
  }

  return thumbnailPromise
}
