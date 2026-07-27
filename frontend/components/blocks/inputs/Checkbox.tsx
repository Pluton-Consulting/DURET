import { useState } from "react"

/** Case à cocher graphique (cochée = couleur de marque). */
export function Checkbox({ label = "Inclure la TVA", defaultChecked = true }: { label?: string; defaultChecked?: boolean }) {
  const [on, setOn] = useState(defaultChecked)
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 10, cursor: "pointer", fontSize: 14, color: "var(--color-text-body)", userSelect: "none" }}>
      <span onClick={() => setOn((v) => !v)} style={{
        width: 20, height: 20, borderRadius: 6, display: "grid", placeItems: "center", flexShrink: 0,
        transition: "all .15s ease", color: "#fff", fontSize: 12, fontWeight: 800,
        background: on ? "var(--color-primary)" : "var(--color-surface)",
        border: `2px solid ${on ? "var(--color-primary)" : "var(--color-border)"}`,
      }}>{on ? "✓" : ""}</span>
      {label}
    </label>
  )
}
