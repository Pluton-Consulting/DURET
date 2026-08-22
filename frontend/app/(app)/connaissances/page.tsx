import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import ConnaissancesClient from "./ConnaissancesClient"

export default async function ConnaissancesPage() {
  const session = await auth()
  const role = (session as any)?.user?.role || ""
  if (!["super_admin", "direction"].includes(role)) redirect("/accueil")
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  const token = (session as any)?.backendToken || ""
  return <ConnaissancesClient apiUrl={apiUrl} token={token} />
}
