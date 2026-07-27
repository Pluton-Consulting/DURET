/** Tuile KPI. `signature` = fond dégradé de marque (élément mis en avant). */
export function StatTile({ label = "Devis en cours", value = "12", hint, signature = false }: { label?: string; value?: string; hint?: string; signature?: boolean }) {
  return (
    <div style={{
      minWidth: 150, borderRadius: "var(--radius-card)", padding: 20, boxShadow: "var(--shadow-card)",
      background: signature ? "linear-gradient(160deg, var(--color-primary), var(--color-primary-hover))" : "var(--color-surface)",
      border: signature ? "none" : "1px solid var(--color-border)",
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 10, color: signature ? "var(--color-on-dark-accent)" : "var(--color-text-muted)" }}>{label}</div>
      <div style={{ fontSize: 34, fontWeight: 800, lineHeight: 1, letterSpacing: "-1px", color: signature ? "var(--color-text-on-dark)" : "var(--color-text-primary)" }}>{value}</div>
      {hint && <div style={{ fontSize: 12, marginTop: 8, color: signature ? "var(--color-on-dark-accent)" : "var(--color-text-muted)" }}>{hint}</div>}
    </div>
  )
}
