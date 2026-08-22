import { auth } from "@/lib/auth"
import Scene from "@/components/scene/Scene"
import TableauDeBord from "@/components/tableau/TableauDeBord"
import ChatWindow from "@/components/chat/ChatWindow"

// Même scène que l'accueil, le chat devant : un lien vers /chat ouvre
// directement la conversation, le tableau de bord déborde à gauche.
export default async function ChatPage() {
  const session = await auth()
  const token = (session as any)?.backendToken || ""
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  return (
    <Scene vueInitiale="chat"
           tableau={<TableauDeBord apiUrl={apiUrl} token={token} />}
           chat={<ChatWindow token={token} />} />
  )
}
