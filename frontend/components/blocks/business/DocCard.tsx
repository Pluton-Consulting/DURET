// Couleurs de FORMAT, pas de marque : chacune reprend celle que l'éditeur du
// format a rendue familière (rouge Acrobat, vert Excel, bleu Word). Le DWG, lui,
// n'en a pas d'établie — il prend donc le bleu de Duret, assombri pour porter du
// texte blanc. C'est le seul de la liste qui relève de la charte.
const KIND: Record<string, string> = { PDF: "#C0392B", XLSX: "#1E7D46", DWG: "#0A6FB4", DOCX: "#2B579A", ZIP: "#7A5C29" }

/** Chip DOCUMENT (badge type de fichier + nom + méta). */
export function DocCard({ name = "CCTP_lot_revetements.pdf", kind = "PDF", meta = "1,4 Mo · 24 p." }: { name?: string; kind?: string; meta?: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 11, background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", padding: "9px 12px", boxShadow: "var(--marque-shadow-card)", maxWidth: "min(var(--bloc-largeur), 100%)" }}>
      <span style={{ width: 34, height: 34, borderRadius: 8, display: "grid", placeItems: "center", fontSize: 10, fontWeight: 800, color: "#fff", flexShrink: 0, background: KIND[kind] ?? "var(--marque-text-muted)" }}>{kind}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--marque-text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{name}</div>
        <div style={{ fontSize: 11, color: "var(--marque-text-muted)" }}>{meta}</div>
      </div>
    </div>
  )
}
