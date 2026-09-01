/**
 * Arborescence de dossiers — bloc MÉCANIQUE, écrit par le backend
 * (`skills/affichage.py`), jamais par le modèle.
 *
 * POURQUOI. Relevé le 01/09 : « liste les dossiers du Drive » — le modèle
 * devait recopier le schéma texte dans un bloc ``` ; il a inventé à la place
 * une carte de document (« TXT — Arborescence du Drive ») qui ne montrait
 * rien. L'arbre arrive désormais tout construit dans un bloc `arbre`, et ce
 * composant se contente de l'afficher : monospace (les branches ne tiennent
 * qu'à l'alignement), défilement au-delà d'une hauteur raisonnable — un Drive
 * de mille dossiers ne doit pas faire mille lignes de chat.
 */
export function Arbre({ titre, sous_titre, schema = "" }:
  { titre?: string; sous_titre?: string; schema?: string }) {
  return (
    <div style={{
      background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
      borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)",
      maxWidth: "min(var(--bloc-largeur), 100%)", width: "100%", overflow: "hidden",
    }}>
      {(titre || sous_titre) && (
        <div style={{
          display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap",
          padding: "10px 14px", borderBottom: "1px solid var(--marque-border)",
        }}>
          {titre && (
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--marque-text-primary)" }}>
              {titre}
            </div>
          )}
          {sous_titre && (
            <div style={{ fontSize: 11.5, color: "var(--marque-text-muted)" }}>{sous_titre}</div>
          )}
        </div>
      )}
      <pre style={{
        margin: 0, padding: "12px 16px", maxHeight: 340, overflow: "auto",
        fontSize: 12, lineHeight: 1.55, color: "var(--marque-text-body)",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        whiteSpace: "pre",
      }}>{schema}</pre>
    </div>
  )
}
