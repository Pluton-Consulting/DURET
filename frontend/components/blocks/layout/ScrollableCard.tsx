import type { ReactNode } from "react"

/** Carte à hauteur fixe avec DÉFILEMENT interne (liste longue, historique…). */
export function ScrollableCard({ title = "Historique du chantier", height = 190, children }: { title?: string; height?: number; children?: ReactNode }) {
  const demo = Array.from({ length: 9 }, (_, i) => `Événement ${i + 1} : mise à jour du dossier`)
  return (
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden", maxWidth: "min(var(--bloc-largeur), 100%)" }}>
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--marque-border)", fontSize: 13.5, fontWeight: 700, color: "var(--marque-text-primary)", background: "var(--marque-primary-subtle)" }}>{title}</div>
      <div style={{ maxHeight: height, overflowY: "auto", padding: "6px 0" }}>
        {(children as any) ?? demo.map((d, i) => (
          <div key={i} style={{ display: "flex", gap: 10, padding: "10px 16px", borderTop: i ? "1px solid var(--marque-border)" : "none", fontSize: 13, color: "var(--marque-text-body)" }}>
            <span style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--marque-primary-mid)", marginTop: 6, flexShrink: 0 }} />
            {d}
          </div>
        ))}
      </div>
    </div>
  )
}
