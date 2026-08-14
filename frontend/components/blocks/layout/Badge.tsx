import type { ReactNode } from "react"

type Tone = "primary" | "success" | "warning" | "error" | "neutral"
const TONES: Record<Tone, { bg: string; fg: string }> = {
  primary: { bg: "var(--marque-primary-subtle)", fg: "var(--marque-primary)" },
  success: { bg: "var(--marque-paid-bg)",        fg: "var(--marque-paid-text)" },
  warning: { bg: "var(--marque-pending-bg)",     fg: "var(--marque-pending-text)" },
  error:   { bg: "var(--marque-error-bg)",       fg: "var(--marque-error-text)" },
  neutral: { bg: "var(--marque-canvas)",         fg: "var(--marque-text-muted)" },
}

/** Étiquette / pastille de statut. */
export function Badge({ tone = "primary", children }: { tone?: Tone; children: ReactNode }) {
  const t = TONES[tone]
  return (
    <span style={{ display: "inline-block", fontSize: 11.5, fontWeight: 700, padding: "4px 11px", borderRadius: "var(--marque-radius-pill)", background: t.bg, color: t.fg }}>{children}</span>
  )
}
