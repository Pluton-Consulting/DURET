/** État vide (aucune donnée) avec action. */
export function EmptyState({ icon = "🗂", title = "Aucun devis en mémoire", subtitle = "La base n'a pas encore été alimentée sur ce sujet.", action = "Importer un document" }: { icon?: string; title?: string; subtitle?: string; action?: string }) {
  return (
    <div style={{ textAlign: "center", padding: "32px 24px", background: "var(--color-surface)", border: "1.5px dashed var(--color-border)", borderRadius: "var(--radius-card)", maxWidth: 340 }}>
      <div style={{ width: 48, height: 48, margin: "0 auto 14px", borderRadius: "50%", background: "var(--color-primary-subtle)", display: "grid", placeItems: "center", fontSize: 22 }}>{icon}</div>
      <div style={{ fontSize: 14.5, fontWeight: 700, color: "var(--color-text-primary)" }}>{title}</div>
      <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", margin: "5px 0 16px", lineHeight: 1.5 }}>{subtitle}</div>
      <button style={{ fontFamily: "var(--font)", fontSize: 13, fontWeight: 600, cursor: "pointer", color: "var(--color-text-on-dark)", border: "none", padding: "8px 18px", borderRadius: "var(--radius-pill)", background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))" }}>{action}</button>
    </div>
  )
}
