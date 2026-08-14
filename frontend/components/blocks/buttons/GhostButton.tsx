import type { ReactNode } from "react"

/** Bouton secondaire (contour). Variante "danger" possible.
 *
 * `disabled` : symétrique de PrimaryButton — le temps d'un appel réseau, les
 * deux boutons d'un choix se ferment ensemble, sans quoi on peut refuser une
 * action déjà approuvée.
 */
export function GhostButton({ children = "Annuler", danger = false, onClick, disabled = false }: { children?: ReactNode; danger?: boolean; onClick?: () => void; disabled?: boolean }) {
  const fg = danger ? "var(--marque-error-text)" : "var(--marque-primary)"
  const bd = danger ? "var(--marque-error-text)" : "var(--marque-primary-light)"
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        fontFamily: "var(--marque-font)", fontSize: 14, fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
        color: fg, background: "var(--marque-surface)", border: `1.5px solid ${bd}`,
        padding: "9px 18px", borderRadius: "var(--marque-radius-pill)", transition: "background .15s ease",
        opacity: disabled ? 0.55 : 1,
      }}
      onMouseEnter={(e) => { if (disabled) return; e.currentTarget.style.background = "var(--marque-primary-subtle)" }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "var(--marque-surface)" }}
    >
      {children}
    </button>
  )
}
