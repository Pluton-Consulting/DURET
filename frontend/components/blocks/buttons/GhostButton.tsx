import type { ReactNode } from "react"

/** Bouton secondaire (contour). Variante "danger" possible. */
export function GhostButton({ children = "Annuler", danger = false, onClick }: { children?: ReactNode; danger?: boolean; onClick?: () => void }) {
  const fg = danger ? "var(--color-error-text)" : "var(--color-primary)"
  const bd = danger ? "var(--color-error-text)" : "var(--color-primary-light)"
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: "var(--font)", fontSize: 14, fontWeight: 600, cursor: "pointer",
        color: fg, background: "var(--color-surface)", border: `1.5px solid ${bd}`,
        padding: "9px 18px", borderRadius: "var(--radius-pill)", transition: "background .15s ease",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--color-primary-subtle)" }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "var(--color-surface)" }}
    >
      {children}
    </button>
  )
}
