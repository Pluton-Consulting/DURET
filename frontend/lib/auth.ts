import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"

const API_URL = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL

// On renouvelle le JWT un peu AVANT son terme : servir un jeton qui expire
// dans dix secondes, c'est offrir un « Session expirée » au milieu de la page
// qu'on vient d'ouvrir.
const MARGE_SECONDES = 5 * 60

/** L'échéance inscrite dans le JWT backend (claim `exp`, en secondes). */
function echeance(jwt: string): number {
  try {
    return JSON.parse(Buffer.from(jwt.split(".")[1], "base64").toString()).exp ?? 0
  } catch {
    return 0
  }
}

/**
 * Échange le jeton d'appareil contre un JWT frais — sans mail, sans clic.
 * Rend null quand la session a été fermée (déconnexion, appareil coupé depuis
 * Paramètres, compte désactivé) : l'appelant renvoie alors à la connexion.
 */
async function rafraichir(jetonAppareil: string) {
  try {
    const res = await fetch(`${API_URL}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: jetonAppareil }),
      cache: "no-store",
    })
    if (!res.ok) return null
    return (await res.json()) as { access_token: string; role: string }
  } catch {
    // Le backend ne répond pas (redémarrage, réseau) : ce n'est PAS une
    // session close. On garde la session en vie et on réessaiera au prochain
    // passage — déconnecter tout le monde à chaque redéploiement serait pire
    // que le mal qu'on soigne.
    return undefined
  }
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Credentials({
      credentials: {
        token: { type: "text" },
        email: { type: "email" },
      },
      async authorize({ token, email }) {
        try {
          const res = await fetch(
            `${API_URL}/api/auth/magic-link/verify`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ token, email }),
            }
          )
          if (!res.ok) return null
          const data = await res.json()
          return {
            id: email as string,
            email: email as string,
            backendToken: data.access_token,
            // Le jeton d'appareil (03/09). Absent si la migration 034 n'est pas
            // appliquée : on retombe alors sur le comportement d'avant.
            refreshToken: data.refresh_token ?? null,
            role: data.role,
          }
        } catch {
          return null
        }
      },
    }),
  ],
  pages: {
    signIn: "/login",
  },
  trustHost: true,
  // LA SESSION DURE UN AN (03/09, demande de Noa : ne plus resaisir son mail ni
  // cliquer un lien magique chaque jour). Elle ne survit plus toute seule : ce
  // qui la tient en vie, c'est le jeton d'appareil, révocable d'un clic dans
  // Paramètres > Mes appareils. 400 jours est le plafond qu'imposent les
  // navigateurs à un cookie ; au-delà, la valeur serait rabotée sans le dire.
  //
  // ⚠️ `jwt_expire_hours` (backend) N'EST PLUS lié à cette durée : le JWT reste
  // court (24 h) et se renouvelle tout seul ci-dessous. C'est justement ce qui
  // permet à la session d'être longue sans devenir irrévocable.
  session: { maxAge: 60 * 60 * 24 * 400 },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.backendToken = (user as any).backendToken
        token.refreshToken = (user as any).refreshToken
        token.role = (user as any).role
        ;(token as any).backendExp = echeance(token.backendToken as string)
      }

      const exp = (token as any).backendExp as number | undefined
      if (exp && Date.now() / 1000 < exp - MARGE_SECONDES) return token

      // Le JWT touche à sa fin. Avant (jusqu'au 03/09) la session mourait ici,
      // et il fallait redemander un lien magique. Désormais l'appareil se
      // renouvelle seul — tant que sa session n'a pas été fermée.
      const jetonAppareil = (token as any).refreshToken as string | undefined
      if (!jetonAppareil) return null

      const neuf = await rafraichir(jetonAppareil)
      if (neuf === null) return null          // session close : retour à /login
      if (neuf === undefined) return token    // backend injoignable : on retente plus tard

      token.backendToken = neuf.access_token
      token.role = neuf.role
      ;(token as any).backendExp = echeance(neuf.access_token)
      return token
    },
    async session({ session, token }) {
      session.backendToken = token.backendToken as string
      session.user.role = token.role as string
      return session
    },
  },
  events: {
    // « Se déconnecter » doit fermer l'appareil, pas seulement l'onglet. Sans
    // ceci, la page suivante se reconnecterait toute seule avec le jeton
    // d'appareil — le bouton mentirait.
    async signOut(message: any) {
      const jeton = message?.token?.refreshToken
      if (!jeton) return
      try {
        await fetch(`${API_URL}/api/auth/appareils/fermer-jeton`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: jeton }),
          cache: "no-store",
        })
      } catch {
        // Rien à dire à l'écran : la session locale se ferme de toute façon.
      }
    },
  },
})
