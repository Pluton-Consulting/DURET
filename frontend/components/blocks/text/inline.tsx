import { Fragment, type ReactNode } from "react"

/**
 * LE MARKDOWN EN LIGNE, POUR LES CHAMPS TEXTE DES COMPOSANTS.
 *
 * Le fil de la conversation passe par Streamdown : `**gras**` y devient du
 * gras. Mais le texte que le modèle écrit À L'INTÉRIEUR d'un composant ```ui —
 * le `text` d'un encart, les `items` d'une liste, une cellule de tableau, un
 * résultat d'étape — était affiché tel quel, astérisques comprises. Relevé en
 * production : « il répond beaucoup avec des * et le texte est normal après ».
 * Le modèle écrit du markdown partout, parce que c'est ce qu'on lui a appris ;
 * c'est à l'écran de le lire partout.
 *
 * Volontairement MINUSCULE : gras, italique, code, saut de ligne. Rien de plus.
 * Un composant n'a pas vocation à porter un titre ou une liste imbriquée — s'il
 * en fallait, ce serait un autre composant. Aucune dépendance, aucun HTML
 * interprété : le texte du modèle reste du texte, seule sa mise en forme change.
 *
 * Idempotent sur un texte sans balisage : une chaîne ordinaire ressort en un
 * seul nœud, sans coût visible.
 */

// Gras d'abord (deux étoiles), puis italique (une), puis code : l'ordre des
// alternatives dans l'expression fait qu'un `**` n'est jamais lu comme deux `*`.
const BALISAGE = /(\*\*[^*\n]+?\*\*|\*[^*\n]+?\*|`[^`\n]+?`)/g

function segment(morceau: string, cle: number): ReactNode {
  if (morceau.startsWith("**") && morceau.endsWith("**") && morceau.length > 4) {
    return <strong key={cle} style={{ fontWeight: 700 }}>{morceau.slice(2, -2)}</strong>
  }
  if (morceau.startsWith("`") && morceau.endsWith("`") && morceau.length > 2) {
    return (
      <code key={cle} style={{ fontSize: "0.92em", padding: "1px 5px", borderRadius: 4,
                               background: "var(--marque-primary-subtle)" }}>
        {morceau.slice(1, -1)}
      </code>
    )
  }
  if (morceau.startsWith("*") && morceau.endsWith("*") && morceau.length > 2) {
    return <em key={cle}>{morceau.slice(1, -1)}</em>
  }
  return morceau
}

/** Rend une chaîne avec son balisage en ligne. Tout autre type est rendu tel quel. */
export function md(texte: unknown): ReactNode {
  if (typeof texte !== "string") return texte as ReactNode
  if (!/[*`\n]/.test(texte)) return texte
  const lignes = texte.split("\n")
  return lignes.map((ligne, li) => (
    <Fragment key={li}>
      {li > 0 && <br />}
      {ligne.split(BALISAGE).map((m, mi) => (m ? segment(m, mi) : null))}
    </Fragment>
  ))
}
