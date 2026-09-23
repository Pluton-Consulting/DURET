import { auth } from "@/lib/auth"
import Scene from "@/components/scene/Scene"
import TableauDeBord from "@/components/tableau/TableauDeBord"
import ChatWindow from "@/components/chat/ChatWindow"
import Fichiers from "@/components/fichiers/Fichiers"

// L'accueil, c'est la SCÈNE : le tableau de bord devant, le chat qui déborde
// à droite. Les deux sont montés ; seul le cadre visible change.
export default async function AccueilPage() {
  const session = await auth()
  const token = (session as any)?.backendToken || ""
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  // L'onglet Fichiers (23/09) : pour tous les comptes, droits par dossier du NAS appliqués.
  const fichiers = <Fichiers apiUrl={apiUrl} token={token} />
  return (
    <Scene vueInitiale="tableau"
           tableau={<TableauDeBord apiUrl={apiUrl} token={token} />}
           chat={<ChatWindow token={token} />} fichiers={fichiers} />
  )
}
