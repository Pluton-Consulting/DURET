import { md } from "../text/inline"
/** Tableau simple (colonnes + lignes), en-tête coloré. */
export function SimpleTable({
  columns = ["Poste", "Quantité", "Unité", "P.U. HT"],
  rows = [
    ["Ragréage P3", "120", "m²", "18,00 €"],
    ["Carrelage 60×60", "120", "m²", "45,00 €"],
    ["Plinthes", "85", "ml", "12,00 €"],
  ],
}: { columns?: string[]; rows?: (string | number)[][] }) {
  return (
    <div className="sym-fluide" style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", overflow: "auto", maxWidth: "min(var(--bloc-largeur), 100%)" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>{columns.map((c, i) => (
            <th key={i} style={{ textAlign: i === 0 ? "left" : "right", padding: "10px 14px", background: "var(--marque-primary-subtle)", color: "var(--marque-text-muted)", fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 700 }}>{c}</th>
          ))}</tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri}>{r.map((cell, ci) => (
              <td key={ci} style={{ textAlign: ci === 0 ? "left" : "right", padding: "10px 14px", borderTop: "1px solid var(--marque-border)", color: ci === 0 ? "var(--marque-text-primary)" : "var(--marque-text-body)", fontWeight: ci === 0 ? 600 : 400, fontVariantNumeric: "tabular-nums" }}>{md(cell)}</td>
            ))}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
