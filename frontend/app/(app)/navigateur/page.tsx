import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import NavigateurClient from "./NavigateurClient"

export default async function NavigateurPage() {
  const session = await auth()
  const role = (session as any)?.user?.role || ""
  if (!["super_admin", "direction"].includes(role)) redirect("/accueil")

  const token = (session as any)?.backendToken || ""

  return (
    <div className="sym-page" style={{ padding: 32, maxWidth: 1000, margin: "0 auto" }}>
      <div style={{ marginBottom: 8, fontFamily: "monospace", fontSize: 12, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--marque-primary-mid)", fontWeight: 600 }}>
        Agent Navigateur · navigation autonome supervisée
      </div>
      <h1 style={{ margin: "0 0 8px", fontSize: 28, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-0.5px" }}>
        Navigateur
      </h1>
      <p style={{ margin: "0 0 28px", fontSize: 15, color: "var(--marque-text-body)", maxWidth: "70ch", lineHeight: 1.55 }}>
        L'agent pilote un vrai navigateur pour chercher, se connecter, remplir des formulaires et extraire des données.
        Par défaut il est en <b>lecture seule</b> (navigation + extraction, sans remplir de formulaire). En mode écriture,
        les actions sensibles s'arrêtent pour <b>approbation</b> ci-dessous, capture à l'appui. Un garde-fou à surveiller.
      </p>
      <NavigateurClient token={token} role={role} />
    </div>
  )
}
