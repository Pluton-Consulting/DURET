/** Placeholder de chargement (effet shimmer). */
export function Skeleton({ lines = 3, width = 280 }: { lines?: number; width?: number }) {
  return (
    <div style={{ width, display: "flex", flexDirection: "column", gap: 10 }}>
      <style>{`@keyframes blkShim{0%{background-position:-450px 0}100%{background-position:450px 0}}`}</style>
      {Array.from({ length: lines }).map((_, i) => (
        <span key={i} style={{
          height: 12, borderRadius: 6, width: i === lines - 1 ? "60%" : "100%",
          background: "linear-gradient(90deg, var(--color-border) 25%, var(--color-primary-subtle) 50%, var(--color-border) 75%)",
          backgroundSize: "900px 100%", animation: "blkShim 1.3s infinite linear",
        }} />
      ))}
    </div>
  )
}
