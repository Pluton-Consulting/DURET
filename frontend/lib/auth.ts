import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"

export const { handlers, signIn, signOut, auth } = NextAuth({
  providers: [
    Credentials({
      credentials: {
        token: { type: "text" },
        email: { type: "email" },
      },
      async authorize({ token, email }) {
        try {
          const apiUrl = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL
          const res = await fetch(
            `${apiUrl}/api/auth/magic-link/verify`,
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
  // La session NextAuth expire en même temps que le JWT backend (24 h, cf. jwt_expire_hours
  // et JWT_EXPIRE_HOURS du .env — les trois ensemble). Sans ça, la session survivrait au
  // token backend → app "accessible" (coquille) avec des 401.
  session: { maxAge: 60 * 60 * 24 },
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.backendToken = (user as any).backendToken
        token.role = (user as any).role
        // Mémorise l'expiration réelle du JWT backend (claim exp, en secondes).
        try {
          const payload = JSON.parse(
            Buffer.from((token.backendToken as string).split(".")[1], "base64").toString()
          )
          ;(token as any).backendExp = payload.exp ?? 0
        } catch {
          ;(token as any).backendExp = 0
        }
      }
      // Sécurité : dès que le token backend est expiré, on invalide la session
      // (auth() renverra null → le layout redirige vers /login). Pas d'accès à l'app.
      const exp = (token as any).backendExp as number | undefined
      if (exp && Date.now() / 1000 >= exp) {
        return null
      }
      return token
    },
    async session({ session, token }) {
      session.backendToken = token.backendToken as string
      session.user.role = token.role as string
      return session
    },
  },
})
