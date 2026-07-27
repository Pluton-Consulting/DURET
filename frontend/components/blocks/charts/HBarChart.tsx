type D = { label: string; value: number }

/** Graphique à BARRES horizontales (classement / comparaison). */
export function HBarChart({
  data = [
    { label: "Point.P", value: 18400 }, { label: "Cedeo", value: 12100 },
    { label: "Frans Bonhomme", value: 8600 }, { label: "Autres", value: 4200 },
  ],
  unit = "€",
}: { data?: D[]; unit?: string }) {
  const max = Math.max(...data.map((d) => d.value)) || 1
  return (
    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", padding: 18, display: "flex", flexDirection: "column", gap: 12, maxWidth: 380 }}>
      {data.map((d, i) => (
        <div key={i}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 5 }}>
            <span style={{ color: "var(--color-text-body)", fontWeight: 500 }}>{d.label}</span>
            <span style={{ color: "var(--color-text-muted)", fontVariantNumeric: "tabular-nums" }}>{d.value.toLocaleString("fr-FR")} {unit}</span>
          </div>
          <div style={{ height: 10, borderRadius: 999, background: "var(--color-primary-subtle)", overflow: "hidden" }}>
            <div style={{ width: `${(d.value / max) * 100}%`, height: "100%", borderRadius: 999, background: "linear-gradient(90deg, var(--color-primary-mid), var(--color-primary))" }} />
          </div>
        </div>
      ))}
    </div>
  )
}
