type Row = { cells: string[]; status: "ok" | "wait" | "late" }
const PILL = {
  ok:   { label: "Livrée",     bg: "var(--color-paid-bg)",    fg: "var(--color-paid-text)" },
  wait: { label: "En attente", bg: "var(--color-pending-bg)", fg: "var(--color-pending-text)" },
  late: { label: "En retard",  bg: "var(--color-error-bg)",   fg: "var(--color-error-text)" },
}

/** Tableau avec colonne de STATUT en pastille colorée. */
export function StatusTable({
  columns = ["Commande", "Fournisseur", "Statut"],
  rows = [
    { cells: ["Carrelage 60×60", "Point.P"], status: "ok" },
    { cells: ["Colle C2 (48 sacs)", "Cedeo"], status: "wait" },
    { cells: ["Plinthes assorties", "Point.P"], status: "late" },
  ] as Row[],
}: { columns?: string[]; rows?: Row[] }) {
  return (
    <div className="sym-fluide" style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", overflow: "auto", maxWidth: 440 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr>{columns.map((c, i) => (
          <th key={i} style={{ textAlign: "left", padding: "10px 14px", background: "var(--color-primary-subtle)", color: "var(--color-text-muted)", fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 700 }}>{c}</th>
        ))}</tr></thead>
        <tbody>
          {rows.map((r, ri) => {
            const p = PILL[r.status]
            return (
              <tr key={ri}>
                {r.cells.map((cell, ci) => (
                  <td key={ci} style={{ padding: "10px 14px", borderTop: "1px solid var(--color-border)", color: ci === 0 ? "var(--color-text-primary)" : "var(--color-text-body)", fontWeight: ci === 0 ? 600 : 400 }}>{cell}</td>
                ))}
                <td style={{ padding: "10px 14px", borderTop: "1px solid var(--color-border)" }}>
                  <span style={{ fontSize: 10.5, fontWeight: 700, padding: "2px 9px", borderRadius: "var(--radius-pill)", background: p.bg, color: p.fg }}>{p.label}</span>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
