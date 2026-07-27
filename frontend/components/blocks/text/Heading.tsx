import type { ReactNode } from "react"

/** Titres de plusieurs tailles (level 1 = grand, 3 = petit). */
export function Heading({ level = 1, eyebrow, children }: { level?: 1 | 2 | 3; eyebrow?: string; children: ReactNode }) {
  const size = { 1: 28, 2: 21, 3: 16 }[level]
  return (
    <div>
      {eyebrow && (
        <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".13em", textTransform: "uppercase", color: "var(--color-primary-mid)", marginBottom: 6 }}>
          {eyebrow}
        </div>
      )}
      <div style={{ fontSize: size, fontWeight: level === 1 ? 800 : 700, letterSpacing: "-.02em", color: "var(--color-text-primary)", lineHeight: 1.2 }}>
        {children}
      </div>
    </div>
  )
}
