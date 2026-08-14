type D = { label: string; value: number }

/** Graphique à BARRES verticales (CSS, dégradé de marque). */
export function BarChart({
  data = [
    { label: "Jan", value: 42 }, { label: "Fév", value: 58 }, { label: "Mar", value: 35 },
    { label: "Avr", value: 71 }, { label: "Mai", value: 64 }, { label: "Juin", value: 88 },
  ],
  height = 150,
}: { data?: D[]; height?: number }) {
  const max = Math.max(...data.map((d) => d.value)) || 1
  return (
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", padding: 18, maxWidth: 420 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 12, height }}>
        {data.map((d, i) => (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 7, height: "100%", justifyContent: "flex-end" }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--marque-text-muted)" }}>{d.value}</div>
            <div style={{ width: "100%", height: `${(d.value / max) * 100}%`, minHeight: 4, borderRadius: "6px 6px 0 0", background: "linear-gradient(180deg, var(--marque-primary-mid), var(--marque-primary))" }} />
            <div style={{ fontSize: 11, color: "var(--marque-text-muted)" }}>{d.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
