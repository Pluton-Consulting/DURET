import { useState } from "react"

/** Puces sélectionnables (cases à cocher graphiques / filtres). */
export function ChipToggles({ options = ["Devis", "Factures", "Chantiers", "Fournisseurs"], multiple = true }: { options?: string[]; multiple?: boolean }) {
  const [sel, setSel] = useState<string[]>([options[0]])
  const toggle = (o: string) =>
    setSel((s) => (multiple ? (s.includes(o) ? s.filter((x) => x !== o) : [...s, o]) : [o]))
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {options.map((o) => {
        const on = sel.includes(o)
        return (
          <button
            key={o}
            onClick={() => toggle(o)}
            style={{
              fontFamily: "var(--marque-font)", fontSize: 13, fontWeight: 600, cursor: "pointer",
              borderRadius: "var(--marque-radius-pill)", padding: "6px 14px", transition: "all .15s ease",
              color: on ? "var(--marque-text-on-dark)" : "var(--marque-text-body)",
              background: on ? "var(--marque-primary)" : "var(--marque-surface)",
              border: `1.5px solid ${on ? "var(--marque-primary)" : "var(--marque-border)"}`,
            }}
          >
            {on ? "✓ " : ""}{o}
          </button>
        )
      })}
    </div>
  )
}
