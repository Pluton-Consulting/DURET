import "next-auth"

declare module "next-auth" {
  interface Session {
    backendToken: string
    user: {
      name?: string | null
      email?: string | null
      image?: string | null
      role: string
    }
  }

  interface User {
    backendToken?: string
    // Le jeton d'appareil (03/09) : il ne quitte jamais le cookie de session,
    // et c'est lui qui évite de redemander un lien magique chaque jour.
    refreshToken?: string | null
    role?: string
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    backendToken?: string
    refreshToken?: string | null
    backendExp?: number
    role?: string
  }
}
