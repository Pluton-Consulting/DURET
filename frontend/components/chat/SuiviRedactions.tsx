"use client"
import { useEffect, useRef, useState } from "react"
import { apiRequest } from "@/lib/api"

type Redaction = { id: string; genre: string; statut: string; phase: string; annonce: boolean }
type Props = { threadId: string | null; token: string | null; enCours: boolean; actualiser: (fil: string) => Promise<boolean> }

export default function SuiviRedactions({ threadId, token, enCours, actualiser }: Props) {
  const [redactions, setRedactions] = useState<Redaction[]>([])
  const [erreur, setErreur] = useState("")
  const [action, setAction] = useState("")
  const [revision, setRevision] = useState(0)
  const actualiserRef = useRef(actualiser)
  actualiserRef.current = actualiser
  const filRef = useRef(threadId)
  filRef.current = threadId
  const annonces = useRef(new Set<string>())
  useEffect(() => { annonces.current = new Set(); setRedactions([]); setErreur(""); setAction("") }, [threadId])

  useEffect(() => {
    if (!threadId || !token) return
    let actif = true
    let minuterie: ReturnType<typeof setTimeout> | undefined
    const lire = async () => {
      let delai = 5000
      try {
        const rows = await apiRequest<Redaction[]>(`/api/chat/threads/${encodeURIComponent(threadId)}/redactions`, { token })
        if (!actif) return
        setRedactions(rows); setErreur("")
        const nouvelles = rows.filter(r => r.annonce && !annonces.current.has(`${r.id}:${r.statut}`))
        if (nouvelles.length && !enCours && await actualiserRef.current(threadId) && actif) {
          nouvelles.forEach(r => annonces.current.add(`${r.id}:${r.statut}`))
        }
        if (!rows.some(r => ["attente", "en_cours"].includes(r.statut) || (r.statut === "termine" && !r.annonce))) delai = 15000
      } catch (e) {
        // Un nouveau fil n’existe en base qu’après son premier envoi.
        if (actif && (e as Error & { status?: number }).status !== 404) setErreur("Suivi momentanément indisponible. Nouvelle vérification automatique en cours.")
      } finally {
        if (actif) minuterie = setTimeout(lire, delai)
      }
    }
    void lire()
    return () => { actif = false; if (minuterie) clearTimeout(minuterie) }
  }, [threadId, token, enCours, revision])

  const piloter = async (r: Redaction, geste: "reprendre" | "suspendre") => {
    if (!threadId || !token || action) return
    const fil = threadId
    setAction(r.id); setErreur("")
    try {
      await apiRequest(`/api/chat/threads/${encodeURIComponent(fil)}/redactions/${encodeURIComponent(r.id)}/${geste}`, { token, method: "POST" })
      if (filRef.current === fil) setRevision(v => v + 1)
    } catch {
      if (filRef.current === fil) setErreur("L’action n’a pas été confirmée. Vérifiez le suivi avant de réessayer.")
    } finally { if (filRef.current === fil) setAction("") }
  }
  if (!redactions.length && !erreur) return null
  return <section aria-label="Suivi des documents" data-testid="suivi-redactions" style={{ padding: "10px 16px", borderBottom: "1px solid var(--marque-border)", maxHeight: 200, overflowY: "auto", fontSize: 13 }}>
    {redactions.map(r => {
      const actif = ["attente", "en_cours"].includes(r.statut)
      return <div key={r.id} style={{ marginBottom: 8 }}>
        <div role="status" aria-live="polite"><strong>{r.genre === "quantitatif" ? "Quantitatif" : "Document"}</strong> — {r.phase}{actif && "…"}</div>
        {actif && <div>Vous pouvez continuer à utiliser le chat. Le fichier apparaîtra ici après les vérifications.</div>}
        {r.statut !== "termine" && <button type="button" disabled={!!action} onClick={() => void piloter(r, actif ? "suspendre" : "reprendre")} style={{ marginTop: 4, textDecoration: "underline" }}>{action === r.id ? "Enregistrement…" : actif ? "Suspendre la rédaction" : "Reprendre la rédaction"}</button>}
      </div>
    })}
    {erreur && <p role="alert">{erreur}</p>}
  </section>
}
