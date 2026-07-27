/** Aperçu d'un EMAIL (barre d'accent + sujet + expéditeur + extrait). */
export function EmailCard({
  subject = "RE : Situation n°3 — Chantier Les Tilleuls",
  from = "compta@scidupont.fr", date = "aujourd'hui 09:14",
  preview = "Bonjour, merci de nous transmettre la situation n°3 avant vendredi pour validation par la maîtrise d'ouvrage…",
}: { subject?: string; from?: string; date?: string; preview?: string }) {
  return (
    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderLeft: "4px solid var(--color-primary-mid)", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", padding: "13px 15px", maxWidth: 420 }}>
      <div style={{ fontSize: 13.5, fontWeight: 700, color: "var(--color-text-primary)" }}>{subject}</div>
      <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", margin: "2px 0 7px" }}>de {from} · {date}</div>
      <div style={{ fontSize: 12.5, color: "var(--color-text-body)", lineHeight: 1.5 }}>{preview}</div>
    </div>
  )
}
