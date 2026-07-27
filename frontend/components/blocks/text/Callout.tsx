import type { ReactNode } from "react"

type Tone = "info" | "success" | "warning" | "error"

const TONES: Record<Tone, { bg: string; fg: string; icon: string }> = {
  info:    { bg: "var(--color-primary-subtle)", fg: "var(--color-primary)",      icon: "ℹ" },
  success: { bg: "var(--color-paid-bg)",        fg: "var(--color-paid-text)",    icon: "✓" },
  warning: { bg: "var(--color-pending-bg)",     fg: "var(--color-pending-text)", icon: "!" },
  error:   { bg: "var(--color-error-bg)",       fg: "var(--color-error-text)",   icon: "✕" },
}

/** Encadré / note colorée (info, succès, alerte, erreur). */
export function Callout({ tone = "info", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  const t = TONES[tone]
  return (
    <div style={{ display: "flex", gap: 11, background: t.bg, borderRadius: "var(--radius-card-sm)", padding: "12px 14px" }}>
      <span style={{ color: t.fg, fontWeight: 800, fontSize: 14, lineHeight: "20px" }}>{t.icon}</span>
      <div style={{ fontSize: 13.5, lineHeight: 1.55, color: t.fg }}>
        {title && <div style={{ fontWeight: 700, marginBottom: 2 }}>{title}</div>}
        {children}
      </div>
    </div>
  )
}
