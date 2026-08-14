import { useState } from "react"

/** Choix unique (boutons radio) — puce sélectionnée = couleur de marque. */
export function RadioGroup({ options = ["Par email", "Par courrier", "Retrait sur place"] }: { options?: string[] }) {
  const [sel, setSel] = useState(options[0])
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {options.map((o) => {
        const on = o === sel
        return (
          <label key={o} onClick={() => setSel(o)} style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", fontSize: 14, color: "var(--marque-text-body)", userSelect: "none" }}>
            <span style={{ width: 20, height: 20, borderRadius: "50%", flexShrink: 0, display: "grid", placeItems: "center", transition: "border-color .15s", border: `2px solid ${on ? "var(--marque-primary)" : "var(--marque-border)"}` }}>
              {on && <span style={{ width: 10, height: 10, borderRadius: "50%", background: "var(--marque-primary)" }} />}
            </span>
            {o}
          </label>
        )
      })}
    </div>
  )
}
