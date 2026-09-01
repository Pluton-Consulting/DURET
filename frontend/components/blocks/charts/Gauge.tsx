/** Jauge en demi-cercle (ex. taux de marge, satisfaction…). */
export function Gauge({ value = 68, label = "Marge estimée" }: { value?: number; label?: string }) {
  const w = 180, h = 100, cx = w / 2, cy = h - 6, r = 74, stroke = 12
  const semi = Math.PI * r
  const off = semi * (1 - value / 100)
  const arc = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`
  return (
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", padding: "16px 18px 12px", textAlign: "center", maxWidth: "min(var(--bloc-largeur), 100%)" }}>
      <svg width={w} height={h}>
        <path d={arc} fill="none" strokeWidth={stroke} strokeLinecap="round" style={{ stroke: "var(--marque-primary-subtle)" }} />
        <path d={arc} fill="none" strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={semi} strokeDashoffset={off} style={{ stroke: "var(--marque-primary)", transition: "stroke-dashoffset .5s ease" }} />
      </svg>
      <div style={{ marginTop: -20 }}>
        <div style={{ fontSize: 26, fontWeight: 800, color: "var(--marque-primary)" }}>{value}%</div>
        <div style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>{label}</div>
      </div>
    </div>
  )
}
