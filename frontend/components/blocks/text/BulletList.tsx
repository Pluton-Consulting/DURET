/** Liste à puces stylée (puce = couleur de marque). */
export function BulletList({ items = ["Premier point important", "Deuxième élément de la liste", "Troisième point à retenir"] }: { items?: string[] }) {
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 9 }}>
      {items.map((it, i) => (
        <li key={i} style={{ display: "flex", gap: 10, alignItems: "flex-start", fontSize: 14, color: "var(--marque-text-body)", lineHeight: 1.5 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--marque-primary-mid)", marginTop: 7, flexShrink: 0 }} />
          {it}
        </li>
      ))}
    </ul>
  )
}
