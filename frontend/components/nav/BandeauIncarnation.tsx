"use client"
import { signOut } from "next-auth/react"

/**
 * LE BANDEAU « CONNECTÉ EN TANT QUE » (23/09, Duret). Tant qu'un super_admin est sur
 * le profil d'un autre (session de 2 h ouverte depuis Paramètres → Utilisateurs), il le
 * voit en permanence : ce qu'il fait ici est fait AU NOM de cette personne. « Quitter »
 * ferme cette session ; on revient à son compte par le bouton Admin de la connexion.
 */
export default function BandeauIncarnation({ nom }: { nom: string }) {
  return (
    <div role="status" style={{
      position: "fixed", left: "50%", bottom: 14, transform: "translateX(-50%)", zIndex: 140,
      display: "flex", gap: 12, alignItems: "center", padding: "8px 16px", borderRadius: 999,
      background: "var(--marque-pending-bg)", color: "var(--marque-pending-text)",
      border: "1px solid var(--marque-border)", boxShadow: "var(--marque-shadow-card)", fontSize: 13, fontWeight: 600,
    }}>
      <span>Vous êtes sur le profil de {nom} (session administrateur, 2 h)</span>
      <button type="button" onClick={() => signOut({ callbackUrl: "/login" })} style={{
        border: "none", background: "var(--marque-surface)", color: "var(--marque-text-body)", borderRadius: 999,
        padding: "4px 12px", fontSize: 12.5, fontWeight: 600, cursor: "pointer",
      }}>Quitter</button>
    </div>
  )
}
