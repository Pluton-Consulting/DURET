"use client"
import { useEffect, useState } from "react"

/** L'APERÇU DES PIÈCES JOINTES, dans la bulle de la personne (07/09).
 *
 *  Jusqu'ici la bulle ne portait que « 📎 nom, nom » — et, une fois la
 *  conversation rechargée, plus rien du tout : la table `messages` ne gardait
 *  que le texte de la question. On ne savait plus ce qu'on avait montré à
 *  l'assistant. Relevé par Noa : « tu n'as pas fait la petite
 *  prévisualisation sur les pièces jointes ».
 *
 *  Une pièce a DEUX sources possibles, jamais les deux à la fois :
 *   · `b64` — le contenu, quand le message vient d'être envoyé : la vignette
 *     se dessine sans aller-retour serveur ;
 *   · `cle` — la clé sous laquelle le tour a rangé la photo NETTOYÉE au dépôt
 *     (`messages.metadata.pieces`), quand le fil est rechargé. L'image est
 *     alors lue par `/api/visuels/{clé}` avec le jeton de session, comme le
 *     bloc `visuel` : une balise <img> ne porte pas d'en-tête d'autorisation.
 *  Un fichier qui n'a ni l'un ni l'autre (Excel, Word, ou une image dont le
 *  dépôt ne répond plus) se montre en PASTILLE : son extension et son nom.
 *  Un PDF de plan a une clé — sa première page rendue — et se montre donc en
 *  vignette, avec son extension par-dessus pour ne pas passer pour une photo.
 */
export interface PieceAffichee {
  nom: string
  mime?: string
  b64?: string
  cle?: string | null
}

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|heic|heif|tiff?)$/i

export function estImage(p: PieceAffichee): boolean {
  return (p.mime || "").toLowerCase().startsWith("image/") || IMAGE_EXT.test(p.nom || "")
}

export function extensionDe(nom: string): string {
  const i = (nom || "").lastIndexOf(".")
  const ext = i > 0 ? nom.slice(i + 1) : ""
  return ext.slice(0, 5).toUpperCase() || "FICHIER"
}

/** Une pastille : l'extension en badge, le nom tronqué. Sur fond sombre. */
function Pastille({ piece }: { piece: PieceAffichee }) {
  return (
    <span data-testid="piece-pastille" title={piece.nom} style={{
      display: "inline-flex", alignItems: "center", gap: 7, maxWidth: 220,
      background: "rgb(255 255 255 / .16)", border: "1px solid rgb(255 255 255 / .28)",
      borderRadius: 10, padding: "5px 9px 5px 6px", color: "inherit",
    }}>
      <span style={{
        fontSize: 10, fontWeight: 700, letterSpacing: .4, lineHeight: 1,
        background: "rgb(255 255 255 / .92)", color: "var(--marque-bulle-moi, #333)",
        borderRadius: 5, padding: "4px 5px",
      }}>{extensionDe(piece.nom)}</span>
      <span style={{ fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {piece.nom}
      </span>
    </span>
  )
}

function Vignette({ piece, apiUrl, backendToken, taille }: {
  piece: PieceAffichee; apiUrl?: string; backendToken?: string; taille: number
}) {
  const [src, setSrc] = useState<string | null>(
    piece.b64 ? `data:${piece.mime || "image/jpeg"};base64,${piece.b64}` : null)
  const [absent, setAbsent] = useState(!piece.b64 && !piece.cle)

  useEffect(() => {
    if (piece.b64 || !piece.cle) return
    if (!apiUrl) { setAbsent(true); return }
    let vivant = true
    let objet: string | null = null
    fetch(`${apiUrl}/api/visuels/${encodeURIComponent(piece.cle)}`,
          { headers: backendToken ? { Authorization: `Bearer ${backendToken}` } : {}, cache: "force-cache" })
      .then(async (r) => { if (!r.ok) throw new Error(String(r.status)); return r.blob() })
      .then((b) => {
        if (!vivant) return
        objet = URL.createObjectURL(b)
        setSrc(objet)
      })
      .catch(() => { if (vivant) setAbsent(true) })
    return () => { vivant = false; if (objet) URL.revokeObjectURL(objet) }
  }, [piece.b64, piece.cle, apiUrl, backendToken])

  if (absent) return <Pastille piece={piece} />

  const ouvrir = () => { if (src) window.open(src, "_blank", "noopener") }
  return (
    <span data-testid="piece-vignette" title={piece.nom} onClick={ouvrir} style={{
      position: "relative", display: "inline-block", width: taille, height: taille,
      borderRadius: 10, overflow: "hidden", flex: "0 0 auto",
      background: "rgb(255 255 255 / .16)", border: "1px solid rgb(255 255 255 / .28)",
      cursor: src ? "zoom-in" : "default",
    }}>
      {src && (
        <img src={src} alt={piece.nom}
             style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
      )}
      {!estImage(piece) && (
        <span style={{
          position: "absolute", left: 4, bottom: 4, fontSize: 9.5, fontWeight: 700, lineHeight: 1,
          background: "rgb(255 255 255 / .92)", color: "var(--marque-bulle-moi, #333)",
          borderRadius: 4, padding: "3px 4px",
        }}>{extensionDe(piece.nom)}</span>
      )}
    </span>
  )
}

export function PiecesJointes({ pieces, apiUrl, backendToken, taille = 72 }: {
  pieces?: PieceAffichee[]; apiUrl?: string; backendToken?: string; taille?: number
}) {
  if (!pieces?.length) return null
  return (
    <span data-testid="pieces-jointes" style={{
      display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginBottom: 6,
    }}>
      {pieces.map((p, i) =>
        (p.b64 || p.cle) ? (
          <Vignette key={`${p.nom}-${i}`} piece={p} apiUrl={apiUrl} backendToken={backendToken} taille={taille} />
        ) : (
          <Pastille key={`${p.nom}-${i}`} piece={p} />
        ))}
    </span>
  )
}
