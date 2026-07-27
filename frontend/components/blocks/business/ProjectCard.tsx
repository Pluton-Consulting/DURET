/** Carte CHANTIER / projet (avancement + statut). */
export function ProjectCard({ name = "Résidence Les Tilleuls", client = "SCI Dupont", progress = 62, status = "En cours" }: { name?: string; client?: string; progress?: number; status?: string }) {
  return (
    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", boxShadow: "var(--shadow-card)", padding: 18, maxWidth: 320 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>{name}</div>
          <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginTop: 2 }}>{client}</div>
        </div>
        <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: "var(--radius-pill)", background: "var(--color-primary-subtle)", color: "var(--color-primary)", whiteSpace: "nowrap" }}>{status}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, margin: "16px 0 5px", color: "var(--color-text-muted)" }}>
        <span>Avancement</span><span style={{ fontWeight: 700, color: "var(--color-primary)" }}>{progress}%</span>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: "var(--color-primary-subtle)", overflow: "hidden" }}>
        <div style={{ width: `${progress}%`, height: "100%", borderRadius: 999, background: "linear-gradient(90deg, var(--color-primary-mid), var(--color-primary))" }} />
      </div>
    </div>
  )
}
