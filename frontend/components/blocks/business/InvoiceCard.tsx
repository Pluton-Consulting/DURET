type Status = "paid" | "pending" | "late"
const STATUS: Record<Status, { label: string; bg: string; fg: string }> = {
  paid:    { label: "Payée",       bg: "var(--marque-paid-bg)",    fg: "var(--marque-paid-text)" },
  pending: { label: "En attente",  bg: "var(--marque-pending-bg)", fg: "var(--marque-pending-text)" },
  late:    { label: "En retard",   bg: "var(--marque-error-bg)",   fg: "var(--marque-error-text)" },
}

/** Carte FACTURE : montant en avant, échéance, statut de règlement. */
export function InvoiceCard({
  number = "FAC-2024-092", client = "SCI Dupont", amount = "8 640,00 €",
  issued = "12/03/2024", due = "11/04/2024", status = "pending",
}: { number?: string; client?: string; amount?: string; issued?: string; due?: string; status?: Status }) {
  const st = STATUS[status]
  return (
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", padding: 20, maxWidth: 380 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", color: "var(--marque-text-muted)" }}>Facture {number}</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)", marginTop: 3 }}>{client}</div>
        </div>
        <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: "var(--marque-radius-pill)", background: st.bg, color: st.fg }}>{st.label}</span>
      </div>
      <div style={{ fontSize: 30, fontWeight: 800, color: "var(--marque-primary)", letterSpacing: "-.5px", margin: "16px 0 14px", fontVariantNumeric: "tabular-nums" }}>{amount}</div>
      <div style={{ display: "flex", gap: 24, fontSize: 12.5, color: "var(--marque-text-body)", borderTop: "1px solid var(--marque-border)", paddingTop: 12 }}>
        <div><div style={{ color: "var(--marque-text-muted)", marginBottom: 2 }}>Émise le</div>{issued}</div>
        <div><div style={{ color: "var(--marque-text-muted)", marginBottom: 2 }}>Échéance</div>{due}</div>
      </div>
    </div>
  )
}
