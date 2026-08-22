"use client"
import { useCallback, useEffect, useRef, useState } from "react"

/**
 * LE RENDU VISUEL GÉNÉRÉ, affiché dans le chat comme une planche.
 *
 * Quand l'assistant génère un visuel d'aménagement, les images sont rangées
 * côté serveur (elles ont été payées, elles ne dépendent plus d'un CDN
 * externe) et le modèle insère ce bloc avec leurs clés. Chargées avec le
 * jeton de session (une balise <img> ne porte pas d'en-tête d'autorisation),
 * affichées en planche, cliquables pour l'échelle 1. Le bandeau dit ce que
 * c'est — une ILLUSTRATION d'intention, pas une simulation du terrain réel —
 * parce que cette confusion-là se paie en rendez-vous client.
 *
 * LE TÉLÉCHARGEMENT PASSE PAR LE BLOB DÉJÀ CHARGÉ, pas par un lien vers
 * l'API. La route `/api/visuels/{clé}` exige un en-tête d'autorisation, qu'un
 * clic droit « Enregistrer l'image sous… » ou un <a href> n'emportent pas :
 * l'un et l'autre rapportaient une erreur 401 au lieu du fichier. L'image est
 * déjà en mémoire pour être affichée — on la donne depuis là, ce qui la rend
 * disponible sans deuxième aller-retour et sans jeton dans une URL.
 */
type ImageVisuel = { cle?: string; url?: string; legende?: string }

/** Un nom de fichier lisible dans le dossier Téléchargements, pas une clé sha256. */
function nomFichier(image: ImageVisuel, titre: string | undefined, type: string, index: number): string {
  const ext = type.includes("png") ? "png"
    : type.includes("webp") ? "webp"
    : type.includes("jpeg") || type.includes("jpg") ? "jpg"
    : "img"
  const base = (image.legende || titre || "visuel")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")  // sans accents : certains systèmes de fichiers les rendent mal
    .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "visuel"
  const suffixe = image.cle ? image.cle.slice(0, 8) : String(index + 1)
  return `${base}-${suffixe}.${ext}`
}

function BoutonTelecharger({ onClick, titre }: { onClick: (e: React.MouseEvent) => void; titre: string }) {
  return (
    <button
      onClick={onClick} title={titre} aria-label={titre}
      style={{
        position: "absolute", right: 8, bottom: 8, width: 32, height: 32,
        display: "grid", placeItems: "center", cursor: "pointer",
        borderRadius: 999, border: "none",
        // Fond sombre translucide plutôt qu'une couleur de charte : le bouton
        // se pose sur une photo dont on ne connaît pas les teintes, et doit
        // rester lisible aussi bien sur un ciel clair que sur une haie sombre.
        background: "rgba(11,14,17,0.55)", backdropFilter: "blur(4px)",
        color: "#fff", fontSize: 15, lineHeight: 1,
      }}
    >
      ⤓
    </button>
  )
}

function Image({
  image, apiUrl, backendToken, titre, index, surBlob,
}: {
  image: ImageVisuel; apiUrl?: string; backendToken?: string; titre?: string
  index: number; surBlob: (index: number, telecharger: () => void) => void
}) {
  const [src, setSrc] = useState<string | null>(image.url || null)
  const [etat, setEtat] = useState<"charge" | "pret" | "absent">(image.url ? "pret" : image.cle ? "charge" : "absent")
  const blob = useRef<Blob | null>(null)

  useEffect(() => {
    if (!image.cle || !apiUrl) return
    let vivant = true
    let objet: string | null = null
    fetch(`${apiUrl}/api/visuels/${encodeURIComponent(image.cle)}`,
          { headers: backendToken ? { Authorization: `Bearer ${backendToken}` } : {}, cache: "force-cache" })
      .then(async (r) => { if (!r.ok) throw new Error(String(r.status)); return r.blob() })
      .then((b) => {
        if (!vivant) return
        blob.current = b
        objet = URL.createObjectURL(b)
        setSrc(objet); setEtat("pret")
      })
      .catch(() => { if (vivant) setEtat("absent") })
    return () => { vivant = false; if (objet) URL.revokeObjectURL(objet) }
  }, [image.cle, apiUrl, backendToken])

  const telecharger = useCallback(() => {
    const b = blob.current
    if (!b) return
    // Une URL éphémère, révoquée juste après : la garder ouverte retiendrait
    // l'image entière en mémoire pour toute la durée de la conversation.
    const url = URL.createObjectURL(b)
    const a = document.createElement("a")
    a.href = url
    a.download = nomFichier(image, titre, b.type || "", index)
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }, [image, titre, index])

  // La planche a besoin de savoir télécharger CHAQUE image pour proposer
  // « Tout télécharger » ; l'enfant remonte donc son geste quand il est prêt.
  useEffect(() => {
    if (etat === "pret" && blob.current) surBlob(index, telecharger)
  }, [etat, index, telecharger, surBlob])

  const ouvrir = () => { if (src) window.open(src, "_blank", "noopener") }

  return (
    <figure style={{ margin: 0, borderRadius: 14, overflow: "hidden", background: "var(--marque-primary-subtle)",
                     position: "relative", aspectRatio: "16 / 10", cursor: src ? "zoom-in" : "default" }}
            onClick={ouvrir} title={src ? "Ouvrir en grand" : undefined}>
      {etat === "pret" && src && (
        <img src={src} alt={image.legende || "Visuel d'aménagement"}
             style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
      )}
      {etat === "pret" && blob.current && (
        <BoutonTelecharger titre="Télécharger cette image"
                           onClick={(e) => { e.stopPropagation(); telecharger() }} />
      )}
      {etat === "charge" && <div className="sym-skeleton" style={{ position: "absolute", inset: 0 }} />}
      {etat === "absent" && (
        <figcaption style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center",
                             color: "var(--marque-text-muted)", fontSize: 12.5, padding: 12, textAlign: "center" }}>
          Visuel indisponible (supprimé ou expiré)
        </figcaption>
      )}
    </figure>
  )
}

export function VisuelPaysager({
  titre, images = [], apiUrl, backendToken,
}: { titre?: string; images?: ImageVisuel[]; apiUrl?: string; backendToken?: string }) {
  const liste = images.filter((i) => i && (i.cle || i.url))
  const gestes = useRef<Map<number, () => void>>(new Map())
  const [prets, setPrets] = useState(0)

  const surBlob = useCallback((index: number, telecharger: () => void) => {
    gestes.current.set(index, telecharger)
    setPrets(gestes.current.size)
  }, [])

  // Les navigateurs bloquent une rafale de téléchargements simultanés : on les
  // espace de 300 ms, sinon seule la première image arrive réellement.
  const toutTelecharger = () => {
    Array.from(gestes.current.values()).forEach((g, i) => setTimeout(g, i * 300))
  }

  return (
    <div className="sym-card" style={{ maxWidth: 640, borderRadius: "var(--marque-radius-card)", overflow: "hidden",
                                        background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
                                        boxShadow: "var(--marque-shadow-card)" }}>
      <div style={{ padding: "12px 16px 10px", display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
        <div style={{ fontWeight: 700, fontSize: 14.5, color: "var(--marque-text-primary)" }}>{titre || "Visuel d'aménagement"}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, whiteSpace: "nowrap" }}>
          {prets > 1 && (
            <button onClick={toutTelecharger} className="sym-tap"
                    style={{ border: "1px solid var(--marque-border)", background: "var(--marque-canvas)",
                             color: "var(--marque-text-body)", fontSize: 11.5, fontWeight: 600, cursor: "pointer",
                             padding: "4px 10px", borderRadius: "var(--marque-radius-pill)" }}>
              ⤓ Tout télécharger
            </button>
          )}
          <span style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)" }}>généré par IA</span>
        </div>
      </div>
      <div style={{ display: "grid", gap: 6, padding: "0 10px",
                    gridTemplateColumns: liste.length > 1 ? "1fr 1fr" : "1fr" }}>
        {liste.map((img, i) => (
          <Image key={img.cle || img.url || i} image={img} apiUrl={apiUrl} backendToken={backendToken}
                 titre={titre} index={i} surBlob={surBlob} />
        ))}
        {liste.length === 0 && <div style={{ padding: 24, textAlign: "center", color: "var(--marque-text-muted)", fontSize: 13 }}>Aucune image.</div>}
      </div>
      <div style={{ padding: "9px 16px 12px", fontSize: 11.5, color: "var(--marque-text-muted)", lineHeight: 1.45 }}>
        Illustration d'intention d'aménagement, générée à partir d'une description — ce n'est ni un plan
        ni une simulation du terrain réel.
      </div>
    </div>
  )
}
