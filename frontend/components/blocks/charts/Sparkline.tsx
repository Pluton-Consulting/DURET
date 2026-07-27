/** Mini-courbe en ligne (tendance compacte, inline). */
export function Sparkline({ values = [4, 6, 5, 8, 7, 11, 9, 13, 12, 16], width = 120, height = 34 }: { values?: number[]; width?: number; height?: number }) {
  const max = Math.max(...values), min = Math.min(...values)
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width
    const y = height - 3 - ((v - min) / (max - min || 1)) * (height - 6)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(" ")
  return (
    <svg width={width} height={height} style={{ display: "inline-block", verticalAlign: "middle" }}>
      <polyline points={pts} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" style={{ stroke: "var(--color-primary-mid)" }} />
    </svg>
  )
}
