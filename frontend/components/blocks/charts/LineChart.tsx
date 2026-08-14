/** Graphique en COURBE (SVG) avec aire de remplissage. */
export function LineChart({
  values = [12, 19, 15, 27, 22, 34, 30, 41],
  width = 360, height = 130,
}: { values?: number[]; width?: number; height?: number }) {
  const max = Math.max(...values), min = Math.min(...values)
  const pad = 8, w = width - pad * 2, h = height - pad * 2
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * w
    const y = pad + h - ((v - min) / (max - min || 1)) * h
    return [x, y]
  })
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ")
  const area = `${line} L${pad + w},${pad + h} L${pad},${pad + h} Z`
  const last = pts[pts.length - 1]
  return (
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", padding: 16, maxWidth: width + 34 }}>
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: "block" }}>
        <defs>
          <linearGradient id="lc-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: "var(--marque-primary-mid)", stopOpacity: 0.28 }} />
            <stop offset="100%" style={{ stopColor: "var(--marque-primary-mid)", stopOpacity: 0 }} />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#lc-fill)" />
        <path d={line} fill="none" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" style={{ stroke: "var(--marque-primary)" }} />
        <circle cx={last[0]} cy={last[1]} r={4} strokeWidth={2} style={{ fill: "var(--marque-primary)", stroke: "var(--marque-surface)" }} />
      </svg>
    </div>
  )
}
