"use client"

/**
 * Fichier produit par l'assistant, prêt à télécharger.
 *
 * Le lien passe par l'API et non par un fichier statique : le téléchargement
 * est contrôlé côté serveur (propriétaire du document), donc il faut porter le
 * jeton d'authentification. Un <a href> simple partirait sans en-tête et se
 * ferait refuser — on récupère donc le fichier, puis on le remet au navigateur.
 */
import { useState } from "react"

type Props = {
  url: string
  nom?: string
  format?: string
  octets?: number
  apiUrl?: string
  backendToken?: string
}

const COULEURS: Record<string, string> = {
  pdf: "#B23B3B",
  docx: "#2B579A",
  xlsx: "#1D6F42",
}

function taille(octets?: number): string {
  if (!octets || octets < 0) return ""
  if (octets < 1024) return `${octets} o`
  if (octets < 1024 * 1024) return `${Math.round(octets / 1024)} Ko`
  return `${(octets / (1024 * 1024)).toFixed(1)} Mo`
}

export function FileCard({ url, nom, format, octets, apiUrl, backendToken }: Props) {
  const [etat, setEtat] = useState<"" | "en_cours" | "erreur">("")
  const ext = (format || url.split(".").pop() || "").toLowerCase()
  const couleur = COULEURS[ext] || "var(--marque-primary)"
  const libelle = nom || `Document.${ext || "fichier"}`

  const telecharger = async () => {
    setEtat("en_cours")
    try {
      const base = apiUrl || ""
      const r = await fetch(url.startsWith("http") ? url : `${base}${url}`, {
        headers: backendToken ? { Authorization: `Bearer ${backendToken}` } : {},
      })
      if (!r.ok) throw new Error(String(r.status))
      const blob = await r.blob()
      // On passe par un lien temporaire : c'est ce qui laisse le navigateur
      // proposer sa boîte « Enregistrer sous » avec le bon nom de fichier.
      const lien = document.createElement("a")
      lien.href = URL.createObjectURL(blob)
      lien.download = libelle
      document.body.appendChild(lien)
      lien.click()
      lien.remove()
      URL.revokeObjectURL(lien.href)
      setEtat("")
    } catch {
      setEtat("erreur")
    }
  }

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, padding: 12,
      border: "1px solid var(--marque-border)", borderRadius: 10,
      background: "var(--marque-surface)", margin: "8px 0", maxWidth: 460,
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 8, background: couleur,
        color: "#fff", display: "flex", alignItems: "center",
        justifyContent: "center", fontSize: 11, fontWeight: 700, flexShrink: 0,
      }}>
        {(ext || "?").toUpperCase().slice(0, 4)}
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 14, fontWeight: 600, color: "var(--marque-text-body)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>{libelle}</div>
        <div style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>
          {[taille(octets), "disponible 24 h"].filter(Boolean).join(" · ")}
        </div>
      </div>

      <button
        onClick={telecharger}
        disabled={etat === "en_cours"}
        style={{
          padding: "8px 14px", borderRadius: 8, border: "none", color: "#fff",
          background: etat === "erreur" ? "var(--marque-error-text)" : couleur,
          fontSize: 13, fontWeight: 600,
          cursor: etat === "en_cours" ? "default" : "pointer",
          opacity: etat === "en_cours" ? 0.6 : 1, flexShrink: 0,
        }}
      >
        {etat === "en_cours" ? "…" : etat === "erreur" ? "Réessayer" : "Télécharger"}
      </button>
    </div>
  )
}
