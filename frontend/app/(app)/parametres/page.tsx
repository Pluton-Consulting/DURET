import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import SettingsClient from "./SettingsClient"

async function fetchUsers(apiUrl: string, token: string) {
  try {
    const res = await fetch(`${apiUrl}/api/users/`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    })
    if (!res.ok) return []
    return await res.json()
  } catch {
    return []
  }
}

export default async function ParametresPage() {
  const session = await auth()
  const user = (session as any)?.user

  if (!["super_admin", "direction"].includes(user?.role || "")) {
    redirect("/accueil")
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  const backendToken = (session as any)?.backendToken || ""
  const users = await fetchUsers(apiUrl, backendToken)

  return (
    <SettingsClient
      initialUsers={users}
      backendToken={backendToken}
      currentRole={user?.role || "direction"}
      apiUrl={apiUrl}
    />
  )
}
