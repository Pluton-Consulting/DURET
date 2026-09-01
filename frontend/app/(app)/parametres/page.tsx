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

  // Paramètres est ouvert à TOUS les rôles connectés : chacun y relie sa
  // boîte Google. Ce sont les ONGLETS qui portent les restrictions — un
  // collaborateur ne voit que « Mon compte Google », et le serveur revérifie de
  // toute façon chaque endpoint d'administration.
  if (!user) {
    redirect("/login")
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  const backendToken = (session as any)?.backendToken || ""
  // La liste des utilisateurs ne sert qu'aux onglets d'administration ; pour
  // les autres rôles, l'endpoint refuse et la liste reste simplement vide.
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
