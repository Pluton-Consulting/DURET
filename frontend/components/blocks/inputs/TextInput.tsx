/** Champ de saisie avec libellé (focus = couleur de marque). */
export function TextInput({ label = "Référence chantier", placeholder = "ex. CH-2024-08" }: { label?: string; placeholder?: string }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, maxWidth: 300 }}>
      <span style={{ fontWeight: 600, color: "var(--color-text-primary)" }}>{label}</span>
      <input
        placeholder={placeholder}
        style={{
          fontFamily: "var(--font)", fontSize: 14, color: "var(--color-text-primary)", padding: "10px 13px",
          border: "1.5px solid var(--color-border)", borderRadius: "var(--radius-card-sm)", outline: "none",
          transition: "border-color .15s ease, box-shadow .15s ease", background: "var(--color-surface)",
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = "var(--color-primary-mid)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--color-primary-subtle)" }}
        onBlur={(e) => { e.currentTarget.style.borderColor = "var(--color-border)"; e.currentTarget.style.boxShadow = "none" }}
      />
    </label>
  )
}
