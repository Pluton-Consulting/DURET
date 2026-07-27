/** Jauge circulaire (pourcentage). */
export function ProgressCircle({ value = 62, size = 96, label = "Avancement" }: { value?: number; size?: number; label?: string }) {
  const stroke = 9, r = (size - stroke) / 2, c = 2 * Math.PI * r
  const off = c * (1 - value / 100)
  return (
    <div style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
      <div style={{ position: "relative", width: size, height: size }}>
        <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} style={{ stroke: "var(--color-primary-subtle)" }} />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} strokeLinecap="round"
            strokeDasharray={c} strokeDashoffset={off} style={{ stroke: "var(--color-primary)", transition: "stroke-dashoffset .5s ease" }} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", fontSize: size / 4.5, fontWeight: 800, color: "var(--color-primary)" }}>{value}%</div>
      </div>
      {label && <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{label}</span>}
    </div>
  )
}
