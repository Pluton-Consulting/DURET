/**
 * Aperçu du CONTENU d'un document — produit par l'assistant, ou lu sur le
 * serveur. La carte `doc` dit qu'un fichier existe ; celle-ci montre ce qu'il
 * y a DEDANS, sans obliger à le télécharger pour vérifier.
 *
 * L'extrait vient du backend : c'est le DÉBUT RÉEL du fichier rendu, pas un
 * résumé du modèle. Le composant ne reformate presque rien — les lignes `#`
 * deviennent des titres, les puces restent des puces, le reste s'affiche tel
 * quel, avec un fondu qui dit qu'il y a une suite.
 */
const COULEURS: Record<string, string> = {
  pdf: "#B23B3B",
  docx: "#2B579A",
  xlsx: "#1D6F42",
}

function Ligne({ texte }: { texte: string }) {
  const titre = texte.match(/^(#{1,4})\s+(.*)$/)
  if (titre) {
    const niveau = titre[1].length
    return (
      <div style={{
        fontSize: niveau === 1 ? 15 : 13.5, fontWeight: 700,
        color: "var(--marque-text-primary)",
        margin: niveau === 1 ? "2px 0 6px" : "8px 0 3px",
      }}>{titre[2]}</div>
    )
  }
  if (texte.startsWith("- ")) {
    return (
      <div style={{ display: "flex", gap: 7, paddingLeft: 6, fontSize: 12.5, lineHeight: 1.55, color: "var(--marque-text-body)" }}>
        <span aria-hidden style={{ color: "var(--marque-text-muted)" }}>•</span>
        <span>{texte.slice(2)}</span>
      </div>
    )
  }
  if (!texte.trim()) return <div style={{ height: 7 }} />
  return (
    <div style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--marque-text-body)" }}>{texte}</div>
  )
}

export function DocApercu({ titre, format = "docx", extrait = "", pages }:
  { titre?: string; format?: string; extrait?: string; pages?: number }) {
  const ext = (format || "").toLowerCase()
  const couleur = COULEURS[ext] || "var(--marque-primary)"
  return (
    <div style={{
      background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
      borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)",
      maxWidth: "min(var(--bloc-largeur), 100%)", width: "100%", overflow: "hidden",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderBottom: "1px solid var(--marque-border)" }}>
        <span style={{
          padding: "3px 8px", borderRadius: 6, background: couleur, color: "#fff",
          fontSize: 10, fontWeight: 800, letterSpacing: 0.4, flexShrink: 0,
        }}>{(ext || "?").toUpperCase()}</span>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 13, fontWeight: 700, color: "var(--marque-text-primary)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{titre || "Document"}</div>
          {pages ? (
            <div style={{ fontSize: 11, color: "var(--marque-text-muted)" }}>{pages} page{pages > 1 ? "s" : ""}</div>
          ) : null}
        </div>
      </div>
      <div style={{ position: "relative", maxHeight: 250, overflow: "hidden", padding: "12px 16px 20px" }}>
        {String(extrait).split("\n").map((l, i) => <Ligne key={i} texte={l} />)}
        {/* Le fondu dit « il y a une suite » : un extrait coupé net se lit
            comme un document qui s'arrête là. */}
        <div aria-hidden style={{
          position: "absolute", left: 0, right: 0, bottom: 0, height: 34,
          background: "linear-gradient(transparent, var(--marque-surface))",
          pointerEvents: "none",
        }} />
      </div>
    </div>
  )
}
