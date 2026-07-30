"use client"
import { Fragment, ReactNode } from "react"

/**
 * Rendu Markdown léger des réponses de l'assistant.
 *
 * Le texte était affiché tel quel : un modèle qui écrit « **Ton et registre** »
 * produisait des astérisques à l'écran au lieu d'un titre. Comme les modèles
 * structurent naturellement leurs réponses en Markdown, tout ce balisage se
 * voyait — et la réponse paraissait mal mise en forme alors qu'elle ne l'était
 * pas.
 *
 * Volontairement MINIMAL et sans dépendance : gras, italique, code, titres,
 * listes à puces et numérotées. Aucune injection d'HTML — on construit des
 * éléments React, donc rien de ce que produit le modèle ne peut être interprété
 * comme du balisage.
 */

const INLINE = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|`[^`\n]+`)/g

function enrichir(ligne: string, cle: string): ReactNode[] {
  return ligne.split(INLINE).filter(Boolean).map((bout, i) => {
    const k = `${cle}-${i}`
    if (/^\*\*.+\*\*$/.test(bout) || /^__.+__$/.test(bout)) {
      return <strong key={k} style={{ fontWeight: 700, color: "var(--color-text-primary)" }}>{bout.slice(2, -2)}</strong>
    }
    if (/^\*[^*]+\*$/.test(bout)) {
      return <em key={k}>{bout.slice(1, -1)}</em>
    }
    if (/^`[^`]+`$/.test(bout)) {
      return (
        <code key={k} style={{
          fontFamily: "ui-monospace, Consolas, monospace", fontSize: "0.92em",
          background: "var(--color-canvas)", border: "1px solid var(--color-border)",
          borderRadius: 5, padding: "1px 5px",
        }}>{bout.slice(1, -1)}</code>
      )
    }
    return <Fragment key={k}>{bout}</Fragment>
  })
}

export function RichText({ texte }: { texte: string }) {
  const lignes = (texte || "").split("\n")
  const blocs: ReactNode[] = []
  let puces: string[] = []
  let numeros: string[] = []

  const viderPuces = () => {
    if (!puces.length) return
    const items = [...puces]
    puces = []
    blocs.push(
      <ul key={`ul-${blocs.length}`} style={{ margin: "6px 0", paddingLeft: 20, display: "flex", flexDirection: "column", gap: 3 }}>
        {items.map((t, i) => <li key={i}>{enrichir(t, `li-${blocs.length}-${i}`)}</li>)}
      </ul>
    )
  }
  const viderNumeros = () => {
    if (!numeros.length) return
    const items = [...numeros]
    numeros = []
    blocs.push(
      <ol key={`ol-${blocs.length}`} style={{ margin: "6px 0", paddingLeft: 22, display: "flex", flexDirection: "column", gap: 3 }}>
        {items.map((t, i) => <li key={i}>{enrichir(t, `oi-${blocs.length}-${i}`)}</li>)}
      </ol>
    )
  }
  const vider = () => { viderPuces(); viderNumeros() }

  lignes.forEach((ligne, index) => {
    const l = ligne.trimEnd()

    const titre = l.match(/^(#{1,4})\s+(.*)$/)
    if (titre) {
      vider()
      const niveau = titre[1].length
      blocs.push(
        <div key={`h-${index}`} style={{
          fontWeight: 700, marginTop: blocs.length ? 10 : 0, marginBottom: 2,
          fontSize: niveau <= 2 ? 15.5 : 14.5, color: "var(--color-text-primary)",
        }}>{enrichir(titre[2], `ht-${index}`)}</div>
      )
      return
    }

    const puce = l.match(/^\s*[-*•]\s+(.*)$/)
    if (puce) { viderNumeros(); puces.push(puce[1]); return }

    const numero = l.match(/^\s*\d+[.)]\s+(.*)$/)
    if (numero) { viderPuces(); numeros.push(numero[1]); return }

    vider()
    if (!l.trim()) {
      // Ligne vide : espace entre paragraphes, sans empiler les vides.
      if (blocs.length && blocs[blocs.length - 1] !== null) blocs.push(null)
      return
    }
    blocs.push(<p key={`p-${index}`} style={{ margin: 0 }}>{enrichir(l, `pt-${index}`)}</p>)
  })
  vider()

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {blocs.map((b, i) => b === null
        ? <div key={`sp-${i}`} style={{ height: 4 }} />
        : <Fragment key={i}>{b}</Fragment>)}
    </div>
  )
}
