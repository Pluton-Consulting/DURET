import { Avatar } from "../layout/Avatar"

/** Fiche CONTACT (client, fournisseur, interlocuteur). */
export function ContactCard({ name = "Benoît Martin", role = "Conducteur de travaux", phone = "06 12 34 56 78", email = "b.martin@duret-sols.fr" }: { name?: string; role?: string; phone?: string; email?: string }) {
  return (
    <div style={{ display: "flex", gap: 13, alignItems: "center", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", boxShadow: "var(--shadow-card)", padding: 16, maxWidth: 340 }}>
      <Avatar name={name} size={46} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14.5, fontWeight: 700, color: "var(--color-text-primary)" }}>{name}</div>
        <div style={{ fontSize: 12, color: "var(--color-primary-mid)", fontWeight: 600, marginBottom: 4 }}>{role}</div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{phone} · {email}</div>
      </div>
    </div>
  )
}
