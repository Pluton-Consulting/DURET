import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import SuperviseurClient from "./SuperviseurClient"

// Console développeur brute (logs en direct, état système). Super_admin uniquement.
export default async function SuperviseurPage() {
  const session = await auth()
  const role = (session as any)?.user?.role || ""
  if (role !== "super_admin") redirect("/accueil")

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  const token = (session as any)?.backendToken || ""
  return <SuperviseurClient apiUrl={apiUrl} token={token} />
}
