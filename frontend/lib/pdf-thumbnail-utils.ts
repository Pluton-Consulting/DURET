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

// UN MOTEUR QUI NE VIENT PAS DOIT LE DIRE, PAS TOURNER À L'INFINI (08/09).
//
// Relevé de Noa sur Duret : « les PDF se mettent bien dans le chat et sont
// téléchargeables, mais leur prévisualisation charge à l'infini ». Lu dans le
// moteur : il crée son worker depuis un Blob et lui envoie l'adresse du
// binaire ; si le chargement échoue dans le worker (adresse relative qu'un
// worker Blob ne sait pas résoudre, 404, mauvais type MIME, réseau lent), le
// worker répond `{ type: "wasmError" }` SANS identifiant de tâche — et le fil
// principal l'écarte comme « tâche inconnue ». La promesse du moteur ne se
// règle jamais, la visionneuse reste sur « chargement ». Trois parades :
//   1. une adresse ABSOLUE — un worker créé depuis un Blob a pour base une
//      adresse `blob:` qui ne sait pas résoudre « /pdfium/… » ;
//   2. une vérification PRÉALABLE depuis la page (HEAD) : un 404 ou un type
//      MIME qui n'est pas `application/wasm` se dit avec sa cause ;
//   3. un CHIEN DE GARDE : passé le délai, la promesse est rejetée avec un
//      message, et le prochain essai repart de zéro.
const DELAI_MOTEUR_MS = 45_000

let sharedEnginePromise: Promise<PdfEngine> | null = null
const pdfDocumentCache = new Map<string, Promise<PdfDocumentObject>>()
const thumbnailUrlCache = new Map<string, Promise<string | null>>()

function adresseAbsolueDuWasm(): string {
  if (typeof window === "undefined") return PDFIUM_WASM_URL
  return new URL(PDFIUM_WASM_URL, window.location.origin).href
}

async function verifierLeBinaire(url: string): Promise<void> {
  let reponse: Response
  try {
    reponse = await fetch(url, { method: "HEAD", cache: "force-cache" })
  } catch (e) {
    throw new Error(`pdfium.wasm injoignable (${e instanceof Error ? e.message : String(e)})`)
  }
  if (!reponse.ok) throw new Error(`pdfium.wasm introuvable (réponse ${reponse.status})`)
  const type = (reponse.headers.get("content-type") || "").split(";")[0].trim()
  if (type && type !== "application/wasm") {
    throw new Error(`pdfium.wasm servi en « ${type} » au lieu de application/wasm`)
  }
}

export function loadSharedPdfEngine() {
  sharedEnginePromise ??= (async () => {
    const url = adresseAbsolueDuWasm()
    await verifierLeBinaire(url)
    const { createPdfiumEngine } = await import("@embedpdf/engines/pdfium-worker-engine")
    let garde: ReturnType<typeof setTimeout> | undefined
    const chienDeGarde = new Promise<never>((_, rejeter) => {
      garde = setTimeout(
        () => rejeter(new Error(`le moteur PDF n'a pas répondu en ${DELAI_MOTEUR_MS / 1000} s`)),
        DELAI_MOTEUR_MS)
    })
    try {
      return await Promise.race([createPdfiumEngine(url, {}), chienDeGarde])
    } finally {
      if (garde) clearTimeout(garde)
    }
  })().catch((e) => {
    // Un échec ne se grave pas : le prochain aperçu retentera.
    sharedEnginePromise = null
    throw e
  })

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
