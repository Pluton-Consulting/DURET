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
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden", maxWidth: 380 }}>
      {rows.map(([k, v], i) => (
        <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 16, padding: "11px 16px", borderTop: i ? "1px solid var(--marque-border)" : "none" }}>
          <span style={{ fontSize: 12.5, color: "var(--marque-text-muted)" }}>{k}</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--marque-text-primary)", textAlign: "right" }}>{v}</span>
        </div>
      ))}
    </div>
  )
}
