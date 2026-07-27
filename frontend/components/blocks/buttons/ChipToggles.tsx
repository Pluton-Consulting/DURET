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
              fontFamily: "var(--font)", fontSize: 13, fontWeight: 600, cursor: "pointer",
              borderRadius: "var(--radius-pill)", padding: "6px 14px", transition: "all .15s ease",
              color: on ? "var(--color-text-on-dark)" : "var(--color-text-body)",
              background: on ? "var(--color-primary)" : "var(--color-surface)",
              border: `1.5px solid ${on ? "var(--color-primary)" : "var(--color-border)"}`,
            }}
          >
            {on ? "✓ " : ""}{o}
          </button>
        )
      })}
    </div>
  )
}
