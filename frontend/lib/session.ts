/**
 * REPRENDRE LA MAIN QUAND LE JETON MEURT DANS UN ONGLET RESTÉ OUVERT.
 *
 * Le JWT du backend vit 24 h. Les composants le reçoivent au rendu et le
 * gardent : un onglet ouvert depuis la veille présente donc un jeton mort, et
 * tout répond 401. Jusqu'au 03/09 la seule issue était de renvoyer à /login —
 * la personne retapait son adresse et rouvrait sa boîte mail.
 *
 * Désormais l'appareil a une session durable côté serveur. Interroger NextAuth
 * (`/api/auth/session`) déclenche son rappel `jwt`, qui échange le jeton
 * d'appareil contre un JWT frais ET réécrit le cookie de session. Il ne reste
 * qu'à recharger la page pour que tout l'écran reparte avec le bon jeton.
 *
 * Rend null quand la session a VRAIMENT été fermée (déconnexion, appareil
 * coupé, compte désactivé) : là, et seulement là, il faut retourner se
 * connecter.
 */
export async function jetonFrais(): Promise<string | null> {
  try {
    const res = await fetch("/api/auth/session", { cache: "no-store" })
    if (!res.ok) return null
    const session = await res.json()
    return session?.backendToken ?? null
  } catch {
    return null
  }
}
