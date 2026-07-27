/** Réponses rapides suggérées par l'IA (pastilles cliquables). */
export function QuickReplies({
  options = ["Envoyer au client", "Ajouter une ligne", "Voir le chantier", "Convertir en facture"],
  onPick,
}: { options?: string[]; onPick?: (value: string) => void }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      {options.map((o) => (
        <button
          key={o}
          onClick={() => onPick?.(o)}
          style={{
            fontFamily: "var(--font)", fontSize: 13, fontWeight: 600, cursor: "pointer",
            color: "var(--color-primary)", background: "var(--color-surface)",
            border: "1.5px solid var(--color-primary-light)", borderRadius: "var(--radius-pill)",
            padding: "7px 15px", transition: "background .15s ease, border-color .15s ease",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-primary-subtle)"; e.currentTarget.style.borderColor = "var(--color-primary-mid)" }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "var(--color-surface)"; e.currentTarget.style.borderColor = "var(--color-primary-light)" }}
        >
          <span style={{ opacity: .5 }}>↳ </span>{o}
        </button>
      ))}
    </div>
  )
}
