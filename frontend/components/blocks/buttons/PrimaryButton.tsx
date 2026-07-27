import type { ReactNode } from "react"

/** Bouton principal (dégradé de marque). Tailles sm / md. */
export function PrimaryButton({ children = "Valider", size = "md", onClick }: { children?: ReactNode; size?: "sm" | "md"; onClick?: () => void }) {
  const pad = size === "sm" ? "7px 14px" : "10px 20px"
  const fs = size === "sm" ? 13 : 14
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: "var(--font)", fontSize: fs, fontWeight: 600, cursor: "pointer", border: "none",
        color: "var(--color-text-on-dark)", padding: pad, borderRadius: "var(--radius-pill)",
        background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
        boxShadow: "var(--shadow-card)", transition: "transform .12s ease, box-shadow .2s ease",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "var(--shadow-hover)" }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = "none"; e.currentTarget.style.boxShadow = "var(--shadow-card)" }}
    >
      {children}
    </button>
  )
}
