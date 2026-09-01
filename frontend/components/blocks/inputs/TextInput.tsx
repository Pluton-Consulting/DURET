/** Champ de saisie avec libellé (focus = couleur de marque). */
export function TextInput({ label = "Référence chantier", placeholder = "ex. CH-2024-08" }: { label?: string; placeholder?: string }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6, fontSize: 13, maxWidth: "min(var(--bloc-largeur), 100%)" }}>
      <span style={{ fontWeight: 600, color: "var(--marque-text-primary)" }}>{label}</span>
      <input
        placeholder={placeholder}
        style={{
          fontFamily: "var(--marque-font)", fontSize: 14, color: "var(--marque-text-primary)", padding: "10px 13px",
          border: "1.5px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", outline: "none",
          transition: "border-color .15s ease, box-shadow .15s ease", background: "var(--marque-surface)",
        }}
        onFocus={(e) => { e.currentTarget.style.borderColor = "var(--marque-primary-mid)"; e.currentTarget.style.boxShadow = "0 0 0 3px var(--marque-primary-subtle)" }}
        onBlur={(e) => { e.currentTarget.style.borderColor = "var(--marque-border)"; e.currentTarget.style.boxShadow = "none" }}
      />
    </label>
  )
}
