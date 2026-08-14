/** Aperçu d'un EMAIL (barre d'accent + sujet + expéditeur + extrait). */
export function EmailCard({
  subject = "RE : Situation n°3, chantier Les Tilleuls",
  from = "compta@scidupont.fr", date = "aujourd'hui 09:14",
  preview = "Bonjour, merci de nous transmettre la situation n°3 avant vendredi pour validation par la maîtrise d'ouvrage…",
}: { subject?: string; from?: string; date?: string; preview?: string }) {
  return (
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderLeft: "4px solid var(--marque-primary-mid)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", padding: "13px 15px", maxWidth: 420 }}>
      <div style={{ fontSize: 13.5, fontWeight: 700, color: "var(--marque-text-primary)" }}>{subject}</div>
      <div style={{ fontSize: 11.5, color: "var(--marque-text-muted)", margin: "2px 0 7px" }}>de {from} · {date}</div>
      <div style={{ fontSize: 12.5, color: "var(--marque-text-body)", lineHeight: 1.5 }}>{preview}</div>
    </div>
  )
}
