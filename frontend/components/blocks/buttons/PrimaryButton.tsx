import type { ReactNode } from "react"

/** Bouton principal (dégradé de marque). Tailles sm / md.
 *
 * `disabled` : un bouton qui déclenche un appel réseau doit pouvoir se fermer
 * le temps de la réponse, sinon un double clic envoie deux fois la même
 * décision. Le survol est neutralisé avec lui — un bouton inerte qui se soulève
 * sous la souris se présente comme cliquable.
 */
export function PrimaryButton({ children = "Valider", size = "md", onClick, disabled = false }: { children?: ReactNode; size?: "sm" | "md"; onClick?: () => void; disabled?: boolean }) {
  const pad = size === "sm" ? "7px 14px" : "10px 20px"
  const fs = size === "sm" ? 13 : 14
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        fontFamily: "var(--marque-font)", fontSize: fs, fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer", border: "none",
        color: "var(--marque-text-on-dark)", padding: pad, borderRadius: "var(--marque-radius-pill)",
        background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
        boxShadow: "var(--marque-shadow-card)", transition: "transform .12s ease, box-shadow .2s ease",
        opacity: disabled ? 0.55 : 1,
      }}
      onMouseEnter={(e) => { if (disabled) return; e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "var(--marque-shadow-hover)" }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "var(--marque-shadow-card)" }}
    >
      {children}
    </button>
  )
}
