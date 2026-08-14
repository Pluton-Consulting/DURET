import type { ReactNode } from "react"

/** Texte simple avec styles : gras, italique, souligné, couleur. */
export function RichText({ children }: { children?: ReactNode }) {
  return (
    <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.65, color: "var(--marque-text-body)" }}>
      {children ?? (
        <>
          Texte normal, avec du <B>gras</B>, de l'<I>italique</I>, du <U>souligné</U>, et un mot en{" "}
          <Accent>couleur de marque</Accent>. On peut aussi <Muted>atténuer</Muted> une partie du texte.
        </>
      )}
    </p>
  )
}

export const B = ({ children }: { children: ReactNode }) => <strong style={{ fontWeight: 700, color: "var(--marque-text-primary)" }}>{children}</strong>
export const I = ({ children }: { children: ReactNode }) => <em>{children}</em>
export const U = ({ children }: { children: ReactNode }) => <span style={{ textDecoration: "underline", textUnderlineOffset: 2 }}>{children}</span>
export const Accent = ({ children }: { children: ReactNode }) => <span style={{ color: "var(--marque-primary-mid)", fontWeight: 600 }}>{children}</span>
export const Muted = ({ children }: { children: ReactNode }) => <span style={{ color: "var(--marque-text-muted)" }}>{children}</span>
