/** Indicateur de chargement (rotation). */
export function Spinner({ size = 24, label }: { size?: number; label?: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10, color: "var(--marque-text-muted)", fontSize: 13 }}>
      <style>{`@keyframes blkSpin{to{transform:rotate(360deg)}}`}</style>
      <span style={{
        width: size, height: size, borderRadius: "50%", display: "inline-block",
        border: `${Math.max(2, Math.round(size / 9))}px solid var(--marque-primary-subtle)`,
        borderTopColor: "var(--marque-primary)", animation: "blkSpin .7s linear infinite",
      }} />
      {label}
    </span>
  )
}
