/** Jauge en demi-cercle (ex. taux de marge, satisfaction…). */
export function Gauge({ value = 68, label = "Marge estimée" }: { value?: number; label?: string }) {
  const w = 180, h = 100, cx = w / 2, cy = h - 6, r = 74, stroke = 12
  const semi = Math.PI * r
  const off = semi * (1 - value / 100)
  const arc = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`
  return (
    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", padding: "16px 18px 12px", textAlign: "center", maxWidth: 220 }}>
      <svg width={w} height={h}>
        <path d={arc} fill="none" strokeWidth={stroke} strokeLinecap="round" style={{ stroke: "var(--color-primary-subtle)" }} />
        <path d={arc} fill="none" strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={semi} strokeDashoffset={off} style={{ stroke: "var(--color-primary)", transition: "stroke-dashoffset .5s ease" }} />
      </svg>
      <div style={{ marginTop: -20 }}>
        <div style={{ fontSize: 26, fontWeight: 800, color: "var(--color-primary)" }}>{value}%</div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{label}</div>
      </div>
    </div>
  )
}
