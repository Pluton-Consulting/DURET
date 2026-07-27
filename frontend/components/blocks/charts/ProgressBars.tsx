type Item = { label: string; pct: number }

/** Barres de PROGRESSION horizontales (avancement par poste). */
export function ProgressBars({
  items = [
    { label: "Ragréage", pct: 100 }, { label: "Carrelage RDC", pct: 72 },
    { label: "Plinthes", pct: 40 }, { label: "Joints", pct: 15 },
  ] as Item[],
}: { items?: Item[] }) {
  return (
    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", padding: 18, display: "flex", flexDirection: "column", gap: 13, maxWidth: 380 }}>
      {items.map((it, i) => (
        <div key={i}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 5 }}>
            <span style={{ color: "var(--color-text-body)", fontWeight: 500 }}>{it.label}</span>
            <span style={{ color: "var(--color-primary)", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{it.pct}%</span>
          </div>
          <div style={{ height: 8, borderRadius: 999, background: "var(--color-primary-subtle)", overflow: "hidden" }}>
            <div style={{ width: `${it.pct}%`, height: "100%", borderRadius: 999, background: "linear-gradient(90deg, var(--color-primary-mid), var(--color-primary))" }} />
          </div>
        </div>
      ))}
    </div>
  )
}
