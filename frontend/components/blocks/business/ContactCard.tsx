import { Avatar } from "../layout/Avatar"

/** Fiche CONTACT (client, fournisseur, interlocuteur). */
export function ContactCard({ name = "Benoît Martin", role = "Conducteur de travaux", phone = "06 12 34 56 78", email = "b.martin@exemple.fr" }: { name?: string; role?: string; phone?: string; email?: string }) {
  return (
    <div style={{ display: "flex", gap: 13, alignItems: "center", background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", padding: 16, maxWidth: 340 }}>
      <Avatar name={name} size={46} />
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 14.5, fontWeight: 700, color: "var(--marque-text-primary)" }}>{name}</div>
        <div style={{ fontSize: 12, color: "var(--marque-primary-mid)", fontWeight: 600, marginBottom: 4 }}>{role}</div>
        <div style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>{phone} · {email}</div>
      </div>
    </div>
  )
}
