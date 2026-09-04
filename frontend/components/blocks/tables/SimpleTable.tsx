import { md } from "../text/inline"
/** Tableau simple (colonnes + lignes), en-tête coloré. */
export function SimpleTable({
  titre,
  columns = ["Poste", "Quantité", "Unité", "P.U. HT"],
  rows = [
    ["Ragréage P3", "120", "m²", "18,00 €"],
    ["Carrelage 60×60", "120", "m²", "45,00 €"],
    ["Plinthes", "85", "ml", "12,00 €"],
  ],
}: { titre?: string; columns?: string[]; rows?: (string | number)[][] }) {
  return (
    <div className="sym-fluide" style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", overflow: "auto", maxWidth: "min(var(--bloc-largeur), 100%)",
                 // GRAND, MAIS QUI DÉFILE (04/09, Noa : « les grands tableaux c'est top,
                 // mais ils sont vraiment trop grands ») : au-delà d'une hauteur
                 // d'écran raisonnable, le tableau défile à l'intérieur de sa carte
                 // au lieu d'étirer tout le fil. L'en-tête reste visible.
                 maxHeight: "min(70vh, 560px)" }}>
      {titre && (
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--marque-border)",
                      fontSize: 13, fontWeight: 700, color: "var(--marque-text-primary)" }}>
          {titre}
        </div>
      )}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead style={{ position: "sticky", top: 0, zIndex: 1, background: "var(--marque-surface)" }}>
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
