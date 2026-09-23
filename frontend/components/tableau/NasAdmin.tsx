"use client"
import { useCallback, useEffect, useState } from "react"
import { MessageRenderer } from "@/components/chat/MessageRenderer"

/**
 * LE NAS DANS LE TABLEAU DE BORD — DEUX OPTIONS À COMPARER (23/09, Duret).
 *
 * Demande de Noa : naviguer dans le serveur de fichiers sans quitter
 * l'application. Deux voies, montrées côte à côte le temps de choisir, au
 * SUPER_ADMIN SEUL — ce n'est pas l'écran qui le décide : il demande au
 * serveur (`/api/nas-explorateur/acces`), qui répond 403 à tout autre rôle, et
 * alors rien ne s'affiche.
 *
 *  1. L'EXPLORATEUR : refait ici, il passe par le serveur de l'application
 *     (mêmes droits que l'assistant, dossiers ouverts, niveau par dossier) et
 *     ouvre un fichier dans la carte du chat (aperçu, téléchargement).
 *  2. LE SITE SYNOLOGY : l'interface officielle du NAS dans un cadre, où l'on
 *     se connecte avec son compte Synology. Synology refuse par défaut d'être
 *     affiché dans une autre page : le réglage à poser est dit sous le cadre.
 */
interface Props { apiUrl: string; token: string }

type Entree = { nom: string; chemin: string; dossier: boolean; octets?: number | null; modifie?: number | null }

const taille = (n?: number | null) => {
  if (typeof n !== "number") return ""
  if (n < 1024) return `${n} o`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} Ko`
  return `${(n / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`
}
const date = (s?: number | null) =>
  typeof s === "number" && s > 0
    ? new Date(s * 1000).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })
    : ""

export default function NasAdmin({ apiUrl, token }: Props) {
  const [acces, setAcces] = useState<{ explorateur: boolean; dsm: string | null } | null>(null)
  const [onglet, setOnglet] = useState<"explorateur" | "synology">("explorateur")

  useEffect(() => {
    if (!token) return
    let vivant = true
    fetch(`${apiUrl}/api/nas-explorateur/acces`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (vivant) setAcces(j) })
      .catch(() => { /* pas d'accès, ou serveur ancien : rien ne s'affiche */ })
    return () => { vivant = false }
  }, [apiUrl, token])

  if (!acces) return null

  const bouton = (actif: boolean) => ({
    padding: "6px 14px", borderRadius: "var(--marque-radius-pill)", fontSize: 12.5, fontWeight: 600,
    cursor: "pointer", fontFamily: "inherit",
    border: actif ? "none" : "1px solid var(--marque-border)",
    background: actif ? "var(--marque-primary)" : "var(--marque-surface)",
    color: actif ? "var(--marque-text-on-dark)" : "var(--marque-text-body)",
  })

  return (
    <div className="v2-carte v2-apparait" data-testid="nas-admin"
         style={{ gridColumn: "span 12", transform: "none" }}>
      <div className="v2-carte-titre">
        <h3>Serveur de fichiers (NAS)</h3>
        <small>visible du super administrateur seulement — comparaison de deux options</small>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <button type="button" style={bouton(onglet === "explorateur")} onClick={() => setOnglet("explorateur")}>
          Option 1 · Explorateur
        </button>
        <button type="button" style={bouton(onglet === "synology")} onClick={() => setOnglet("synology")}>
          Option 2 · Site Synology
        </button>
      </div>
      {onglet === "explorateur"
        ? <Explorateur apiUrl={apiUrl} token={token} />
        : <SiteSynology adresse={acces.dsm} />}
    </div>
  )
}

function Explorateur({ apiUrl, token }: Props) {
  const [chemin, setChemin] = useState<string | null>(null)
  const [entrees, setEntrees] = useState<Entree[]>([])
  const [total, setTotal] = useState(0)
  const [charge, setCharge] = useState(false)
  const [erreur, setErreur] = useState("")
  const [motif, setMotif] = useState("")
  const [recherche, setRecherche] = useState<{ motif: string; partiel: boolean } | null>(null)
  const [tri, setTri] = useState<"nom" | "date">("nom")
  const [ouvert, setOuvert] = useState<{ nom: string; bloc?: any; message?: string } | null>(null)
  const [ouverture, setOuverture] = useState("")

  const appeler = useCallback(async (url: string, init?: RequestInit) => {
    const r = await fetch(`${apiUrl}${url}`, {
      ...init, cache: "no-store",
      headers: { Authorization: `Bearer ${token}`, ...(init?.body ? { "Content-Type": "application/json" } : {}) },
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`)
    return j
  }, [apiUrl, token])

  const aller = useCallback(async (vers: string | null) => {
    setCharge(true); setErreur(""); setRecherche(null)
    try {
      const j = await appeler(`/api/nas-explorateur/lister${vers ? `?chemin=${encodeURIComponent(vers)}` : ""}`)
      setChemin(j.chemin); setEntrees(j.entrees || []); setTotal(j.total ?? (j.entrees || []).length)
    } catch (e: any) {
      setErreur(e?.message || "listage impossible")
    } finally {
      setCharge(false)
    }
  }, [appeler])

  useEffect(() => { aller(null) }, [aller])

  const chercher = async () => {
    const m = motif.trim()
    if (m.length < 2) return
    setCharge(true); setErreur("")
    try {
      const j = await appeler(`/api/nas-explorateur/chercher?motif=${encodeURIComponent(m)}${chemin ? `&dossier=${encodeURIComponent(chemin)}` : ""}`)
      setEntrees(j.resultats || []); setTotal(j.total ?? (j.resultats || []).length)
      setRecherche({ motif: m, partiel: !!j.partiel })
    } catch (e: any) {
      setErreur(e?.message || "recherche impossible")
    } finally {
      setCharge(false)
    }
  }

  const ouvrir = async (e: Entree) => {
    setOuverture(e.chemin); setOuvert({ nom: e.nom })
    try {
      const j = await appeler(`/api/nas-explorateur/ouvrir`, { method: "POST", body: JSON.stringify({ chemin: e.chemin }) })
      setOuvert({ nom: e.nom, bloc: j.bloc_ui, message: j.message })
    } catch (err: any) {
      setOuvert({ nom: e.nom, message: err?.message || "ouverture impossible" })
    } finally {
      setOuverture("")
    }
  }

  // Fil d'Ariane : chaque segment du chemin est cliquable ; « Racines » revient au début.
  const segments = (chemin || "").split("/").filter(Boolean)
  const tries = [...entrees].sort((a, b) => {
    if (a.dossier !== b.dossier) return a.dossier ? -1 : 1
    if (tri === "date") return (b.modifie || 0) - (a.modifie || 0)
    return a.nom.localeCompare(b.nom, "fr", { numeric: true })
  })
  const lien = { border: "none", background: "transparent", padding: 0, cursor: "pointer", fontFamily: "inherit",
                 fontSize: 13, color: "var(--marque-primary)", fontWeight: 600 }
  const secondaire = { padding: "8px 14px", borderRadius: "var(--marque-radius-pill)", border: "1px solid var(--marque-border)",
                       background: "var(--marque-surface)", color: "var(--marque-text-body)", fontSize: 13, cursor: "pointer" }

  return (
    <div>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", alignItems: "center", fontSize: 13, marginBottom: 10 }}>
        <button type="button" style={lien} onClick={() => aller(null)}>Racines</button>
        {segments.map((s, i) => (
          <span key={i} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
            <span style={{ color: "var(--marque-text-muted)" }}>›</span>
            <button type="button" style={lien} onClick={() => aller("/" + segments.slice(0, i + 1).join("/"))}>{s}</button>
          </span>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <input value={motif} onChange={(e) => setMotif(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") chercher() }}
               placeholder={chemin ? "Chercher un nom dans ce dossier…" : "Chercher un nom sur tout le NAS…"}
               style={{ flex: 1, minWidth: 200, padding: "8px 12px", fontSize: 13, border: "1px solid var(--marque-border)",
                        borderRadius: "var(--marque-radius-pill)", color: "var(--marque-text-body)", outline: "none",
                        background: "var(--marque-surface)" }} />
        <button type="button" onClick={chercher} disabled={motif.trim().length < 2 || charge} className="sym-tap" style={secondaire}>
          Chercher
        </button>
        <button type="button" onClick={() => setTri(tri === "nom" ? "date" : "nom")} className="sym-tap" style={secondaire}>
          Tri : {tri === "nom" ? "nom" : "plus récent"}
        </button>
      </div>
      {recherche && (
        <div style={{ fontSize: 12.5, color: "var(--marque-text-muted)", marginBottom: 8 }}>
          {total} résultat(s) pour « {recherche.motif} »{recherche.partiel ? " — recherche partielle, le catalogue se construit encore" : ""}.{" "}
          <button type="button" style={{ ...lien, fontSize: 12.5 }} onClick={() => aller(chemin)}>Revenir au dossier</button>
        </div>
      )}
      {erreur && <div style={{ fontSize: 13, color: "var(--marque-error-text)", marginBottom: 8 }}>⚠ {erreur}</div>}
      <div style={{ maxHeight: 420, overflowY: "auto", border: "1px solid var(--marque-border)", borderRadius: 12 }}
           aria-busy={charge}>
        {charge && <div className="v2-vide" style={{ padding: 12 }}>Lecture du NAS…</div>}
        {!charge && tries.length === 0 && !erreur && <div className="v2-vide" style={{ padding: 12 }}>Dossier vide.</div>}
        {!charge && tries.map((e) => (
          <button key={e.chemin} type="button" onClick={() => (e.dossier ? aller(e.chemin) : ouvrir(e))}
                  title={e.chemin}
                  style={{ display: "flex", width: "100%", gap: 10, alignItems: "center", padding: "8px 12px",
                           border: "none", borderBottom: "1px solid color-mix(in srgb, var(--marque-border) 60%, transparent)",
                           background: ouverture === e.chemin ? "var(--marque-canvas)" : "transparent",
                           cursor: "pointer", fontFamily: "inherit", textAlign: "left", fontSize: 13,
                           color: "var(--marque-text-body)" }}>
            <span aria-hidden style={{ width: 18 }}>{e.dossier ? "📁" : "📄"}</span>
            <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                           fontWeight: e.dossier ? 600 : 400 }}>
              {e.nom}
              {recherche && <span style={{ color: "var(--marque-text-muted)", fontWeight: 400 }}> · {e.chemin.split("/").slice(0, -1).join("/")}</span>}
            </span>
            <span style={{ color: "var(--marque-text-muted)", fontSize: 12, whiteSpace: "nowrap" }}>{e.dossier ? "" : taille(e.octets)}</span>
            <span style={{ color: "var(--marque-text-muted)", fontSize: 12, whiteSpace: "nowrap", minWidth: 90, textAlign: "right" }}>{date(e.modifie)}</span>
          </button>
        ))}
      </div>
      {ouvert && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <strong style={{ fontSize: 13, color: "var(--marque-text-primary)" }}>{ouvert.nom}</strong>
            <button type="button" style={{ ...lien, fontSize: 12.5 }} onClick={() => setOuvert(null)}>Fermer</button>
          </div>
          {!ouvert.bloc && !ouvert.message && <div className="v2-vide">Téléchargement depuis le NAS…</div>}
          {ouvert.message && <div style={{ fontSize: 13, color: "var(--marque-text-body)" }}>{ouvert.message}</div>}
          {ouvert.bloc && (
            <MessageRenderer content={"```ui\n" + JSON.stringify(ouvert.bloc) + "\n```"}
                             apiUrl={apiUrl} backendToken={token} dernier />
          )}
        </div>
      )}
    </div>
  )
}

function SiteSynology({ adresse }: { adresse: string | null }) {
  if (!adresse) {
    return <div className="v2-vide">Aucune adresse du NAS n'est configurée sur le serveur.</div>
  }
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 12.5, color: "var(--marque-text-muted)" }}>
          Connexion avec votre compte Synology · {adresse}
        </span>
        <a href={adresse} target="_blank" rel="noopener noreferrer"
           style={{ fontSize: 12.5, fontWeight: 600, color: "var(--marque-primary)" }}>Ouvrir dans un onglet ↗</a>
      </div>
      <iframe src={adresse} title="Site Synology du NAS" data-testid="nas-synology"
              allow="clipboard-read; clipboard-write; fullscreen"
              style={{ width: "100%", height: 640, border: "1px solid var(--marque-border)", borderRadius: 12,
                       background: "var(--marque-surface)" }} />
      <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 8, lineHeight: 1.5 }}>
        Cadre blanc ou refus d'affichage : Synology interdit par défaut d'être affiché dans une autre page.
        Sur le NAS : Panneau de configuration → Sécurité → onglet Sécurité → « Protection iFrame » :
        autoriser le domaine de l'application. Si la connexion revient en boucle (Safari, iPhone), c'est le
        navigateur qui bloque les cookies du relais QuickConnect dans un cadre : utilisez « Ouvrir dans un onglet ».
      </div>
    </div>
  )
}
