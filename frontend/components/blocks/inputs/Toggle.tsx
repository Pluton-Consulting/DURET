import { useState } from "react"

/** Interrupteur (switch) on/off. */
export function Toggle({ label = "Notifications", defaultOn = true }: { label?: string; defaultOn?: boolean }) {
  const [on, setOn] = useState(defaultOn)
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 11, cursor: "pointer", fontSize: 14, color: "var(--color-text-body)", userSelect: "none" }}>
      <span onClick={() => setOn((v) => !v)} style={{
        width: 40, height: 23, borderRadius: 999, padding: 2, flexShrink: 0, transition: "background .18s ease",
        background: on ? "var(--color-primary)" : "var(--color-border)", display: "flex",
        justifyContent: on ? "flex-end" : "flex-start",
      }}>
        <span style={{ width: 19, height: 19, borderRadius: "50%", background: "#fff", boxShadow: "0 1px 2px rgba(0,0,0,.25)" }} />
      </span>
      {label}
    </label>
  )
}
