type Seg = { label: string; value: number; color: string }

/** Graphique en ANNEAU (donut) + légende. Couleurs = nuances de marque. */
export function DonutChart({
  segments = [
    { label: "Main d'œuvre", value: 45, color: "var(--marque-primary)" },
    { label: "Fournitures", value: 35, color: "var(--marque-primary-mid)" },
    { label: "Sous-traitance", value: 12, color: "var(--marque-primary-light)" },
    { label: "Divers", value: 8, color: "var(--marque-border)" },
  ] as Seg[],
}: { segments?: Seg[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1
  let acc = 0
  const stops = segments.map((s) => {
    const from = (acc / total) * 360; acc += s.value; const to = (acc / total) * 360
    return `${s.color} ${from}deg ${to}deg`
  }).join(", ")
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 22, background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", padding: 18, maxWidth: 380 }}>
      <div style={{ width: 108, height: 108, borderRadius: "50%", background: `conic-gradient(${stops})`, flexShrink: 0, display: "grid", placeItems: "center" }}>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: "var(--marque-surface)", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 800, color: "var(--marque-text-primary)" }}>100%</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {segments.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
            <span style={{ width: 11, height: 11, borderRadius: 3, background: s.color, flexShrink: 0 }} />
            <span style={{ color: "var(--marque-text-body)" }}>{s.label}</span>
            <span style={{ color: "var(--marque-text-muted)", fontWeight: 600 }}>{s.value}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}
