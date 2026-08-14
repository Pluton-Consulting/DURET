/** Avatar avec initiales (fond dégradé de marque). */
export function Avatar({ name = "Benoît Martin", size = 40 }: { name?: string; size?: number }) {
  const initials = name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()
  return (
    <span style={{
      width: size, height: size, borderRadius: "50%", display: "inline-grid", placeItems: "center",
      background: "linear-gradient(160deg, var(--marque-primary-mid), var(--marque-primary))",
      color: "var(--marque-text-on-dark)", fontWeight: 700, fontSize: size * 0.38, flexShrink: 0,
    }}>{initials}</span>
  )
}
