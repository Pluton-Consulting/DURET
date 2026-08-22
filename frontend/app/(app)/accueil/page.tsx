import { auth } from "@/lib/auth"
import Scene from "@/components/scene/Scene"
import TableauDeBord from "@/components/tableau/TableauDeBord"
import ChatWindow from "@/components/chat/ChatWindow"

// L'accueil, c'est la SCÈNE : le tableau de bord devant, le chat qui déborde
// à droite. Les deux sont montés ; seul le cadre visible change.
export default async function AccueilPage() {
  const session = await auth()
  const token = (session as any)?.backendToken || ""
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  return (
    <Scene vueInitiale="tableau"
           tableau={<TableauDeBord apiUrl={apiUrl} token={token} />}
           chat={<ChatWindow token={token} />} />
  )
}
