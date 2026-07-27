/** Indicateur de chargement (rotation). */
export function Spinner({ size = 24, label }: { size?: number; label?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10, color: "var(--color-text-muted)", fontSize: 13 }}>
      <style>{`@keyframes blkSpin{to{transform:rotate(360deg)}}`}</style>
      <span style={{
        width: size, height: size, borderRadius: "50%", display: "inline-block",
        border: `${Math.max(2, Math.round(size / 9))}px solid var(--color-primary-subtle)`,
        borderTopColor: "var(--color-primary)", animation: "blkSpin .7s linear infinite",
      }} />
      {label}
    </span>
  )
}
