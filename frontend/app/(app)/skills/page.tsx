import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import SkillsClient from "./SkillsClient"

export default async function SkillsPage() {
  const session = await auth()
  const role = (session as any)?.user?.role || ""
  if (!["super_admin", "direction"].includes(role)) redirect("/accueil")

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  const token = (session as any)?.backendToken || ""
  return <SkillsClient apiUrl={apiUrl} token={token} />
}
