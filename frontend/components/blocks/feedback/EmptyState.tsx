/** État vide (aucune donnée) avec action. */
export function EmptyState({ icon = "🗂", title = "Aucun devis en mémoire", subtitle = "La base n'a pas encore été alimentée sur ce sujet.", action = "Importer un document" }: { icon?: string; title?: string; subtitle?: string; action?: string }) {
  return (
    <div style={{ textAlign: "center", padding: "32px 24px", background: "var(--marque-surface)", border: "1.5px dashed var(--marque-border)", borderRadius: "var(--marque-radius-card)", maxWidth: 340 }}>
      <div style={{ width: 48, height: 48, margin: "0 auto 14px", borderRadius: "50%", background: "var(--marque-primary-subtle)", display: "grid", placeItems: "center", fontSize: 22 }}>{icon}</div>
      <div style={{ fontSize: 14.5, fontWeight: 700, color: "var(--marque-text-primary)" }}>{title}</div>
      <div style={{ fontSize: 12.5, color: "var(--marque-text-muted)", margin: "5px 0 16px", lineHeight: 1.5 }}>{subtitle}</div>
      <button style={{ fontFamily: "var(--marque-font)", fontSize: 13, fontWeight: 600, cursor: "pointer", color: "var(--marque-text-on-dark)", border: "none", padding: "8px 18px", borderRadius: "var(--marque-radius-pill)", background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))" }}>{action}</button>
    </div>
  )
}
