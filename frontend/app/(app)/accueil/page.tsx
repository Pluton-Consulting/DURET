import { auth } from "@/lib/auth"
import ChatWindow from "@/components/chat/ChatWindow"

// L'accueil EST le chat Duret & Sols. Le token backend est récupéré côté serveur et
// passé au composant (fiable, indépendant de l'hydratation de la session client).
export default async function AccueilPage() {
  const session = await auth()
  const token = (session as any)?.backendToken || ""
  return <ChatWindow token={token} />
}
