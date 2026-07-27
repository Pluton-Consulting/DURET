import type { CSSProperties } from "react"

type Line = { label: string; qty?: string; price?: string }
type Status = "draft" | "sent" | "accepted"

const STATUS: Record<Status, { label: string; bg: string; fg: string }> = {
  draft:    { label: "Brouillon", bg: "var(--color-pending-bg)", fg: "var(--color-pending-text)" },
  sent:     { label: "Envoyé",    bg: "var(--color-paid-bg)",    fg: "var(--color-paid-text)" },
  accepted: { label: "Accepté",   bg: "var(--color-paid-bg)",    fg: "var(--color-paid-text)" },
}

/** Carte DEVIS : en-tête coloré, lignes, total surligné, actions. */
export function QuoteCard({
  id = "DEV-2024-017",
  client = "SCI Dupont · Résidence Les Tilleuls",
  status = "draft",
  total = "10 380,00 €",
  lines = [
    { label: "Ragréage sol P3", qty: "120 m²", price: "2 160,00 €" },
    { label: "Carrelage grès cérame 60×60", qty: "120 m²", price: "5 400,00 €" },
    { label: "Plinthes assorties", qty: "85 ml", price: "1 020,00 €" },
    { label: "Pose + joints (forfait)", qty: "1", price: "1 800,00 €" },
  ],
}: { id?: string; client?: string; status?: Status; total?: string; lines?: Line[] }) {
  const st = STATUS[status]
  return (
    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", boxShadow: "var(--shadow-card)", overflow: "hidden", maxWidth: 480 }}>
      <div style={{ background: "linear-gradient(135deg, var(--color-primary), var(--color-primary-hover))", color: "var(--color-text-on-dark)", padding: "15px 18px", display: "flex", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: "-.2px" }}>Devis {id}</div>
          <div style={{ fontSize: 12, color: "var(--color-on-dark-accent)", marginTop: 2 }}>{client}</div>
        </div>
        <span style={{ fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: "var(--radius-pill)", height: "fit-content", whiteSpace: "nowrap", background: st.bg, color: st.fg }}>{st.label}</span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            <th style={thh}>Poste</th><th style={{ ...thh, textAlign: "right" }}>Qté</th><th style={{ ...thh, textAlign: "right" }}>Total HT</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td style={{ ...td, color: "var(--color-text-primary)", fontWeight: 600 }}>{l.label}</td>
              <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{l.qty}</td>
              <td style={{ ...td, textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{l.price}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "13px 18px", borderTop: "2px solid var(--color-primary-light)", background: "var(--color-primary-subtle)" }}>
        <span style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--color-text-muted)" }}>Total HT</span>
        <span style={{ fontSize: 19, fontWeight: 800, color: "var(--color-primary)", fontVariantNumeric: "tabular-nums" }}>{total}</span>
      </div>
    </div>
  )
}

const thh: CSSProperties = { textAlign: "left", fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--color-text-muted)", fontWeight: 700, padding: "10px 18px", background: "var(--color-primary-subtle)" }
const td: CSSProperties = { padding: "11px 18px", borderTop: "1px solid var(--color-border)", color: "var(--color-text-body)" }
