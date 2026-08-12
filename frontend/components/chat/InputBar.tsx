"use client"
import { useRef, useState, KeyboardEvent } from "react"

export interface PieceJointe {
  name: string
  mime: string
  b64: string
}

interface InputBarProps {
  onSend: (text: string, piece?: PieceJointe) => void
  disabled?: boolean
  // Une tache tourne deja : ecrire reste possible, l'envoi MET EN FILE au lieu
  // d'interrompre. Le champ et le bouton le disent, sinon l'utilisateur croit
  // interrompre la tache en cours.
  modeFile?: boolean
}

/** Trois barres indentées : la file d'attente, dessinée plutôt que dite. */
function IconeFile() {
  return (
    <svg width="18" height="14" viewBox="0 0 18 14" fill="none" aria-hidden="true">
      <rect x="0" y="0" width="14" height="2.6" rx="1.3" fill="currentColor" />
      <rect x="2.5" y="5.7" width="14" height="2.6" rx="1.3" fill="currentColor" opacity="0.75" />
      <rect x="5" y="11.4" width="13" height="2.6" rx="1.3" fill="currentColor" opacity="0.5" />
    </svg>
  )
}

// Limite alignée sur MAX_BODY_MB côté backend : mieux vaut refuser tout de suite
// avec un message clair que de laisser partir un envoi qui sera rejeté.
const TAILLE_MAX_MO = 10

/** Lit le fichier en base64 (sans le préfixe « data:...;base64, »). */
function lireBase64(fichier: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const r = String(reader.result || "")
      const i = r.indexOf(",")
      resolve(i >= 0 ? r.slice(i + 1) : r)
    }
    reader.onerror = () => reject(new Error("Lecture du fichier impossible"))
    reader.readAsDataURL(fichier)
  })
}

export default function InputBar({ onSend, disabled, modeFile }: InputBarProps) {
  const [value, setValue] = useState("")
  const [piece, setPiece] = useState<PieceJointe | null>(null)
  const [erreur, setErreur] = useState("")
  const [survol, setSurvol] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const attacher = async (fichier: File) => {
    setErreur("")
    if (fichier.size > TAILLE_MAX_MO * 1024 * 1024) {
      setErreur(`Fichier trop volumineux (${(fichier.size / 1024 / 1024).toFixed(1)} Mo, maximum ${TAILLE_MAX_MO} Mo).`)
      return
    }
    try {
      setPiece({
        name: fichier.name,
        // Certains navigateurs ne renseignent pas le type pour les formats rares :
        // le backend se rabat alors sur l'extension du nom.
        mime: fichier.type || "application/octet-stream",
        b64: await lireBase64(fichier),
      })
    } catch {
      setErreur("Lecture du fichier impossible.")
    }
  }

  const envoyer = () => {
    if (disabled) return
    if (!value.trim() && !piece) return
    // Un fichier envoyé sans question : on formule l'intention par défaut.
    onSend(value.trim() || `Analyse ce fichier : ${piece?.name}`, piece || undefined)
    setValue("")
    setPiece(null)
    setErreur("")
    if (inputRef.current) inputRef.current.value = ""
  }

  const surTouche = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      envoyer()
    }
  }

  const peutEnvoyer = !disabled && (Boolean(value.trim()) || Boolean(piece))

  return (
    <div
      className="sym-in"
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setSurvol(true) }}
      onDragLeave={() => setSurvol(false)}
      onDrop={(e) => {
        e.preventDefault(); setSurvol(false)
        const f = e.dataTransfer.files?.[0]
        if (f && !disabled) attacher(f)
      }}
      style={{
        padding: "16px 32px",
        background: survol ? "var(--color-primary-subtle)" : "var(--color-surface)",
        borderTop: `1px solid ${survol ? "var(--color-primary)" : "var(--color-border)"}`,
        transition: "background .15s ease, border-color .15s ease",
      }}
    >
      {survol && (
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-primary)", marginBottom: 10 }}>
          Déposez le fichier pour le joindre
        </div>
      )}

      {piece && (
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 10, marginBottom: 10,
          background: "var(--color-primary-subtle)", border: "1px solid var(--color-primary-light)",
          borderRadius: "var(--radius-pill)", padding: "6px 8px 6px 14px", maxWidth: "100%",
        }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {piece.name}
          </span>
          <button onClick={() => setPiece(null)} aria-label="Retirer le fichier" style={{
            border: "none", background: "transparent", cursor: "pointer", color: "var(--color-primary)",
            fontSize: 17, lineHeight: 1, padding: "0 4px", fontWeight: 700,
          }}>×</button>
        </div>
      )}

      {erreur && (
        <div style={{ fontSize: 13, color: "var(--color-error)", marginBottom: 10 }}>{erreur}</div>
      )}

      <div style={{ display: "flex", gap: 10, alignItems: "flex-end" }}>
        <input ref={inputRef} type="file" style={{ display: "none" }}
               onChange={(e) => { const f = e.target.files?.[0]; if (f) attacher(f) }} />

        <button
          className="sym-tap"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
          title="Joindre un fichier (Excel, Word, PDF, image, texte…)"
          aria-label="Joindre un fichier"
          style={{
            background: "transparent", border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-pill)", width: 40, height: 40, flexShrink: 0,
            cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
            color: "var(--color-text-muted)", fontSize: 17, display: "flex",
            alignItems: "center", justifyContent: "center",
          }}
        >
          📎
        </button>

        <textarea
          data-testid="saisie-message"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={surTouche}
          placeholder={modeFile
            ? "Écrivez pour mettre une autre tâche dans la file d'attente"
            : "Posez votre question... (Entrée pour envoyer, Maj+Entrée pour saut de ligne)"}
          disabled={disabled}
          rows={1}
          style={{
            flex: 1, resize: "none", border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-pill)", padding: "10px 16px", fontSize: 14,
            fontFamily: "var(--font)", color: "var(--color-text-body)", outline: "none",
            transition: "border-color .2s ease, box-shadow .2s ease",
          }}
        />

        <button
          className="sym-tap"
          data-testid="envoyer-message"
          onClick={envoyer}
          disabled={!peutEnvoyer}
          title={modeFile ? "Mettre en file d'attente" : "Envoyer"}
          aria-label={modeFile ? "Mettre en file d'attente" : "Envoyer"}
          style={{
            background: "linear-gradient(180deg, var(--color-primary-hover), var(--color-primary))",
            color: "var(--color-text-on-dark)", border: "none",
            borderRadius: "var(--radius-pill)", padding: "10px 20px", fontSize: 14,
            fontWeight: 500, cursor: peutEnvoyer ? "pointer" : "not-allowed",
            opacity: peutEnvoyer ? 1 : 0.6, whiteSpace: "nowrap", boxShadow: "var(--shadow-card)",
            display: "flex", alignItems: "center", gap: 8,
          }}
        >
          {modeFile ? <><IconeFile /> En file</> : "Envoyer"}
        </button>
      </div>
    </div>
  )
}
