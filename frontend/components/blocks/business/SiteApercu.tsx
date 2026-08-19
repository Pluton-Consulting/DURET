"use client"
import { useEffect, useState } from "react"

/**
 * L'APERÇU D'UNE PAGE WEB, comme on la verrait dans un navigateur.
 *
 * Quand l'assistant lit une page, le conteneur navigateur la capture en même
 * temps ; le backend garde l'image sous une clé et le modèle insère ce bloc
 * avec la clé, le titre et l'adresse. L'image est chargée AVEC le jeton de
 * session (une balise <img> ne sait pas porter l'en-tête d'autorisation) :
 * on la récupère, on en fait une URL locale, et on l'affiche. Sans image
 * (aperçu expiré après un redémarrage, capture refusée), la carte garde le
 * titre et le lien — on ne perd jamais l'essentiel.
 */
export function SiteApercu({
  url, titre, apercu, apiUrl, backendToken,
}: { url: string; titre?: string; apercu?: string; apiUrl?: string; backendToken?: string }) {
  const [src, setSrc] = useState<string | null>(null)
  const [etat, setEtat] = useState<"charge" | "pret" | "absent">(apercu ? "charge" : "absent")

  useEffect(() => {
    if (!apercu || !apiUrl) { setEtat("absent"); return }
    let vivant = true
    let objet: string | null = null
    fetch(`${apiUrl}/api/browser/apercu/${encodeURIComponent(apercu)}`,
          { headers: backendToken ? { Authorization: `Bearer ${backendToken}` } : {}, cache: "force-cache" })
      .then(async (r) => { if (!r.ok) throw new Error(String(r.status)); return r.blob() })
      .then((b) => { if (!vivant) return; objet = URL.createObjectURL(b); setSrc(objet); setEtat("pret") })
      .catch(() => { if (vivant) setEtat("absent") })
    return () => { vivant = false; if (objet) URL.revokeObjectURL(objet) }
  }, [apercu, apiUrl, backendToken])

  let hote = url
  try { hote = new URL(url).hostname.replace(/^www\./, "") } catch { /* adresse brute */ }

  return (
    <a href={url} target="_blank" rel="noopener noreferrer" className="sym-card sym-tap"
       style={{ display: "block", maxWidth: 560, borderRadius: "var(--marque-radius-card)", overflow: "hidden",
                background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
                boxShadow: "var(--marque-shadow-card)", textDecoration: "none", color: "inherit" }}>
      <div style={{ position: "relative", aspectRatio: "16 / 10", background: "var(--marque-primary-subtle)", overflow: "hidden" }}>
        {etat === "pret" && src && (
          <img src={src} alt={`Aperçu de ${hote}`} style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "top", display: "block" }} />
        )}
        {etat === "charge" && <div className="sym-skeleton" style={{ position: "absolute", inset: 0 }} />}
        {etat === "absent" && (
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "var(--marque-text-muted)", fontSize: 13 }}>
            Aperçu indisponible — ouvrir la page
          </div>
        )}
        {/* La barre d'adresse, comme un navigateur. */}
        <div style={{ position: "absolute", top: 10, left: 10, right: 10, display: "flex", alignItems: "center", gap: 8,
                      background: "rgba(255,255,255,.86)", backdropFilter: "blur(6px)", borderRadius: 999, padding: "6px 12px",
                      fontSize: 12, color: "var(--marque-text-body)", boxShadow: "0 1px 4px rgba(0,0,0,.08)" }}>
          <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--marque-paid-text)", flexShrink: 0 }} />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{url}</span>
        </div>
      </div>
      <div style={{ padding: "12px 14px", display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontWeight: 700, fontSize: 14, color: "var(--marque-text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{titre || hote}</div>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>{hote} · source externe, lue par l'assistant</div>
        </div>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--marque-primary)", whiteSpace: "nowrap" }}>Ouvrir ↗</span>
      </div>
    </a>
  )
}
