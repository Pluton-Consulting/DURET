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

/** Le refus est-il celui d'un jeton mort (401) ? */
export function estSessionExpiree(e: unknown): boolean {
  return (e as { status?: number } | null)?.status === 401
}

/**
 * UN SONDAGE QUI REÇOIT 401 NE REDEMANDE PAS INDÉFINIMENT (22/09, Duret).
 *
 * Le suivi des rédactions (toutes les 3 s) et l'état de la file (toutes les 4 s)
 * ignoraient le refus : un onglet resté ouvert sur un poste dont la session avait
 * expiré a envoyé plus de 7 000 requêtes refusées en 2 h 40. Au premier 401, UNE
 * reprise pour tout l'écran, quel que soit le nombre de sondages qui la
 * déclenchent : un jeton frais recharge la page ; sinon (session vraiment fermée)
 * le sondage s'arrête — la prochaine action de la personne la renverra à la
 * connexion. Rend vrai quand la page va se recharger.
 */
let reprise: Promise<boolean> | null = null
export function reprendreSession(): Promise<boolean> {
  if (!reprise) {
    reprise = (async () => {
      const frais = await jetonFrais()
      if (frais) {
        window.location.reload()
        return true
      }
      return false
    })()
  }
  return reprise
}
