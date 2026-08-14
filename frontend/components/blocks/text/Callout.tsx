import type { ReactNode } from "react"

type Tone = "info" | "success" | "warning" | "error"

const TONES: Record<Tone, { bg: string; fg: string; icon: string }> = {
  info:    { bg: "var(--marque-primary-subtle)", fg: "var(--marque-primary)",      icon: "ℹ" },
  success: { bg: "var(--marque-paid-bg)",        fg: "var(--marque-paid-text)",    icon: "✓" },
  warning: { bg: "var(--marque-pending-bg)",     fg: "var(--marque-pending-text)", icon: "!" },
  error:   { bg: "var(--marque-error-bg)",       fg: "var(--marque-error-text)",   icon: "✕" },
}

/** Encadré / note colorée (info, succès, alerte, erreur). */
export function Callout({ tone = "info", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  const t = TONES[tone]
  return (
    <div style={{ display: "flex", gap: 11, background: t.bg, borderRadius: "var(--marque-radius-card-sm)", padding: "12px 14px" }}>
      <span style={{ color: t.fg, fontWeight: 800, fontSize: 14, lineHeight: "20px" }}>{t.icon}</span>
      <div style={{ fontSize: 13.5, lineHeight: 1.55, color: t.fg }}>
        {title && <div style={{ fontWeight: 700, marginBottom: 2 }}>{title}</div>}
        {children}
      </div>
    </div>
  )
}
