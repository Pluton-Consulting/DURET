import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import Scene from "@/components/scene/Scene"
import TableauDeBord from "@/components/tableau/TableauDeBord"
import ChatWindow from "@/components/chat/ChatWindow"
import Fichiers from "@/components/fichiers/Fichiers"

// L'onglet Fichiers (23/09, Duret) : la même scène, l'explorateur du NAS devant.
// Réservé pour l'instant au super_admin : les autres retombent sur l'accueil.
export default async function FichiersPage() {
  const session = await auth()
  const token = (session as any)?.backendToken || ""
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  if ((session as any)?.user?.role !== "super_admin") redirect("/accueil")
  return (
    <Scene vueInitiale="fichiers"
           tableau={<TableauDeBord apiUrl={apiUrl} token={token} />}
           chat={<ChatWindow token={token} />}
           fichiers={<Fichiers apiUrl={apiUrl} token={token} />} />
  )
}
