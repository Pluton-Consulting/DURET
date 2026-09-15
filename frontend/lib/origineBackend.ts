/**
 * LE JETON NE SORT JAMAIS VERS UN AUTRE SITE (16/09, audit D-03).
 *
 * L'aperçu d'un document et le bouton « Télécharger » faisaient un `fetch` avec
 * `Authorization: Bearer <jeton>` sur l'URL reçue du bloc — y compris une URL
 * ABSOLUE. Si un bloc portait l'adresse d'un site tiers (une URL recopiée d'une
 * page web, d'un mail), le jeton de session partait chez ce tiers.
 *
 * Règle : l'en-tête n'est ajouté que si l'adresse, résolue avec `URL()`, a la
 * MÊME ORIGINE que le backend configuré (ou que la page, quand le backend est
 * servi derrière le même domaine). Une adresse externe se charge sans jeton.
 */
export function cibleDocument(url: string, apiUrl?: string): { adresse: string; authentifier: boolean } {
  const page = typeof window !== "undefined" ? window.location.origin : "http://localhost"
  let backend: string
  let adresse: URL
  try {
    backend = new URL(apiUrl || page, page).origin
    // Une adresse relative (« /api/documents/… ») se colle au backend, comme avant.
    adresse = new URL(url.startsWith("/") ? `${apiUrl || ""}${url}` : url, page)
  } catch {
    return { adresse: url, authentifier: false }
  }
  const web = adresse.protocol === "https:" || adresse.protocol === "http:"
  const interne = web && (adresse.origin === backend || adresse.origin === page)
  return { adresse: adresse.href, authentifier: interne }
}

/** Les en-têtes à poser pour cette adresse : le jeton seulement si elle est interne. */
export function entetesPour(url: string, apiUrl?: string, jeton?: string): Record<string, string> {
  const { authentifier } = cibleDocument(url, apiUrl)
  return authentifier && jeton ? { Authorization: `Bearer ${jeton}` } : {}
}
