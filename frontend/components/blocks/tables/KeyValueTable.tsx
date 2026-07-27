/** Fiche clé/valeur (2 colonnes) — pour récapituler des infos. */
export function KeyValueTable({
  rows = [
    ["Chantier", "Résidence Les Tilleuls"],
    ["Client", "SCI Dupont"],
    ["Conducteur", "Benoît M."],
    ["Avancement", "62 %"],
    ["Échéance", "30/06/2024"],
  ],
}: { rows?: [string, string][] }) {
  return (
    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", overflow: "hidden", maxWidth: 380 }}>
      {rows.map(([k, v], i) => (
        <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 16, padding: "11px 16px", borderTop: i ? "1px solid var(--color-border)" : "none" }}>
          <span style={{ fontSize: 12.5, color: "var(--color-text-muted)" }}>{k}</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)", textAlign: "right" }}>{v}</span>
        </div>
      ))}
    </div>
  )
}
