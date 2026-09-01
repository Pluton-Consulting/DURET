type Step = { title: string; time: string; done?: boolean }

/** Frise chronologique verticale (suivi d'étapes). */
export function Timeline({
  steps = [
    { title: "Devis envoyé", time: "12 mars", done: true },
    { title: "Devis accepté", time: "18 mars", done: true },
    { title: "Chantier démarré", time: "2 avril", done: true },
    { title: "Situation n°3", time: "en cours", done: false },
  ] as Step[],
}: { steps?: Step[] }) {
  return (
    <div style={{ maxWidth: "min(var(--bloc-largeur), 100%)", paddingLeft: 4 }}>
      {steps.map((s, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "20px 1fr", gap: 12, position: "relative", paddingBottom: i < steps.length - 1 ? 20 : 0 }}>
          {i < steps.length - 1 && <span style={{ position: "absolute", left: 9, top: 18, bottom: 0, width: 2, background: s.done ? "var(--marque-primary-mid)" : "var(--marque-border)" }} />}
          <span style={{ width: 20, height: 20, borderRadius: "50%", zIndex: 1, display: "grid", placeItems: "center", fontSize: 10, fontWeight: 800, color: "#fff",
            background: s.done ? "var(--marque-primary)" : "var(--marque-surface)", border: `2px solid ${s.done ? "var(--marque-primary)" : "var(--marque-border)"}` }}>{s.done ? "✓" : ""}</span>
          <div>
            <div style={{ fontSize: 13.5, fontWeight: 600, color: s.done ? "var(--marque-text-primary)" : "var(--marque-text-muted)" }}>{s.title}</div>
            <div style={{ fontSize: 11.5, color: "var(--marque-text-muted)" }}>{s.time}</div>
          </div>
        </div>
      ))}
    </div>
  )
}
