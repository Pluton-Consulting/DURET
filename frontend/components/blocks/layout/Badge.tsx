import type { ReactNode } from "react"

type Tone = "primary" | "success" | "warning" | "error" | "neutral"
const TONES: Record<Tone, { bg: string; fg: string }> = {
  primary: { bg: "var(--color-primary-subtle)", fg: "var(--color-primary)" },
  success: { bg: "var(--color-paid-bg)",        fg: "var(--color-paid-text)" },
  warning: { bg: "var(--color-pending-bg)",     fg: "var(--color-pending-text)" },
  error:   { bg: "var(--color-error-bg)",       fg: "var(--color-error-text)" },
  neutral: { bg: "var(--color-canvas)",         fg: "var(--color-text-muted)" },
}

/** Étiquette / pastille de statut. */
export function Badge({ tone = "primary", children }: { tone?: Tone; children: ReactNode }) {
  const t = TONES[tone]
  return (
    <span style={{ display: "inline-block", fontSize: 11.5, fontWeight: 700, padding: "4px 11px", borderRadius: "var(--radius-pill)", background: t.bg, color: t.fg }}>{children}</span>
  )
}
