/** Tuile KPI. `signature` = fond dégradé de marque (élément mis en avant). */
export function StatTile({ label = "Devis en cours", value = "12", hint, signature = false }: { label?: string; value?: string; hint?: string; signature?: boolean }) {
  return (
    <div style={{
      minWidth: 150, borderRadius: "var(--marque-radius-card)", padding: 20, boxShadow: "var(--marque-shadow-card)",
      background: signature ? "linear-gradient(160deg, var(--marque-primary), var(--marque-primary-hover))" : "var(--marque-surface)",
      border: signature ? "none" : "1px solid var(--marque-border)",
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 10, color: signature ? "var(--marque-on-dark-accent)" : "var(--marque-text-muted)" }}>{label}</div>
      <div style={{ fontSize: 34, fontWeight: 800, lineHeight: 1, letterSpacing: "-1px", color: signature ? "var(--marque-text-on-dark)" : "var(--marque-text-primary)" }}>{value}</div>
      {hint && <div style={{ fontSize: 12, marginTop: 8, color: signature ? "var(--marque-on-dark-accent)" : "var(--marque-text-muted)" }}>{hint}</div>}
    </div>
  )
}
