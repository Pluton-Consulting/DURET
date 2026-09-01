/** Carte CHANTIER / projet (avancement + statut). */
export function ProjectCard({ name = "Résidence Les Tilleuls", client = "SCI Dupont", progress = 62, status = "En cours" }: { name?: string; client?: string; progress?: number; status?: string }) {
  return (
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", padding: 18, maxWidth: "min(var(--bloc-largeur), 100%)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>{name}</div>
          <div style={{ fontSize: 12.5, color: "var(--marque-text-muted)", marginTop: 2 }}>{client}</div>
        </div>
        <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: "var(--marque-radius-pill)", background: "var(--marque-primary-subtle)", color: "var(--marque-primary)", whiteSpace: "nowrap" }}>{status}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, margin: "16px 0 5px", color: "var(--marque-text-muted)" }}>
        <span>Avancement</span><span style={{ fontWeight: 700, color: "var(--marque-primary)" }}>{progress}%</span>
      </div>
      <div style={{ height: 8, borderRadius: 999, background: "var(--marque-primary-subtle)", overflow: "hidden" }}>
        <div style={{ width: `${progress}%`, height: "100%", borderRadius: 999, background: "linear-gradient(90deg, var(--marque-primary-mid), var(--marque-primary))" }} />
      </div>
    </div>
  )
}
