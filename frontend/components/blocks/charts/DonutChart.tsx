type Seg = { label: string; value: number; color?: string }

/** LA COULEUR NE SE DEMANDE PAS AU MODÈLE.
 *
 *  Le segment portait une couleur OBLIGATOIRE. Pour produire un camembert, le
 *  modèle aurait donc dû inventer des valeurs CSS : soit il reprend des
 *  teintes qui n'appartiennent pas au client, soit il omet le champ et
 *  l'anneau se dessine avec des trous. Or toute la chaîne repose sur l'idée
 *  que l'IA n'émet que des DONNÉES, jamais de style.
 *
 *  Les nuances viennent donc d'ici, prises dans la charte et distribuées dans
 *  l'ordre. Le camembert d'un client est vert, celui d'un autre bleu, sans que
 *  le modèle ait à le savoir. Une couleur explicite reste acceptée, pour les
 *  cas où une teinte porte un sens (un segment « en retard », par exemple). */
const NUANCES = [
  "var(--marque-primary)",
  "var(--marque-primary-mid)",
  "var(--marque-primary-light)",
  "var(--marque-primary-subtle)",
  "var(--marque-border)",
]

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
  const teinte = (s: Seg, i: number) => s.color || NUANCES[i % NUANCES.length]
  let acc = 0
  const stops = segments.map((s, i) => {
    const from = (acc / total) * 360; acc += s.value; const to = (acc / total) * 360
    return `${teinte(s, i)} ${from}deg ${to}deg`
  }).join(", ")
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 22, background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", padding: 18, maxWidth: "min(var(--bloc-largeur), 100%)" }}>
      <div style={{ width: 108, height: 108, borderRadius: "50%", background: `conic-gradient(${stops})`, flexShrink: 0, display: "grid", placeItems: "center" }}>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: "var(--marque-surface)", display: "grid", placeItems: "center", fontSize: 13, fontWeight: 800, color: "var(--marque-text-primary)" }}>100%</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {segments.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12.5 }}>
            <span style={{ width: 11, height: 11, borderRadius: 3, background: teinte(s, i), flexShrink: 0 }} />
            <span style={{ color: "var(--marque-text-body)" }}>{s.label}</span>
            <span style={{ color: "var(--marque-text-muted)", fontWeight: 600 }}>{s.value}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}
