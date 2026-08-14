import { useState } from "react"

/** Onglets (navigation par section). */
export function Tabs({ tabs = ["Résumé", "Lignes", "Documents", "Historique"] }: { tabs?: string[] }) {
  const [active, setActive] = useState(0)
  return (
    <div style={{ maxWidth: 400 }}>
      <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--marque-border)" }}>
        {tabs.map((t, i) => {
          const on = i === active
          return (
            <button key={t} onClick={() => setActive(i)} style={{
              fontFamily: "var(--marque-font)", fontSize: 13, fontWeight: 600, cursor: "pointer", background: "none", border: "none",
              padding: "10px 14px", color: on ? "var(--marque-primary)" : "var(--marque-text-muted)",
              borderBottom: `2px solid ${on ? "var(--marque-primary)" : "transparent"}`, marginBottom: -1, transition: "color .15s",
            }}>{t}</button>
          )
        })}
      </div>
      <div style={{ padding: "16px 4px", fontSize: 13.5, color: "var(--marque-text-body)" }}>
        Contenu de l'onglet « <strong style={{ color: "var(--marque-text-primary)" }}>{tabs[active]}</strong> ».
      </div>
    </div>
  )
}
