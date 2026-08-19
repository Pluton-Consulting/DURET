import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import PilotageClient from "./PilotageClient"

/**
 * PILOTAGE — ce que la direction regarde : qui se sert de l'assistant, pour
 * quoi faire, ce que ça coûte, et ce qui a échoué.
 *
 * Cette page était une MAQUETTE : indicateurs à « n/d », coûts par personne
 * « non implémentés », instructions de l'IA écrites en dur, et un avertissement
 * renvoyant vers l'onglet Développeur pour « les vrais chiffres ». Le brief
 * client (§15, contrôle des usages ; §4, reporting) en fait pourtant une
 * exigence de la Direction. La donnée existait déjà en base — elle n'était pas
 * servie. Elle l'est désormais par `/api/dashboard/pilotage`, et la page la
 * montre telle quelle.
 *
 * Réservée aux rôles qui ont le droit de voir le tableau de bord global ; le
 * détail des coûts et le journal suivent leurs propres permissions, et le
 * serveur ne les rend qu'à qui peut les voir.
 */
export default async function GestionPage() {
  const session = await auth()
  const role = (session as any)?.user?.role || ""
  if (!["super_admin", "direction"].includes(role)) redirect("/accueil")

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  const token = (session as any)?.backendToken || ""
  return <PilotageClient apiUrl={apiUrl} token={token} />
}
