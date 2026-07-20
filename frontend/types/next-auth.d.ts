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
    role?: string
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    backendToken?: string
    role?: string
  }
}
