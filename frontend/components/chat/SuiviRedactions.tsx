"use client"
import { useEffect, useRef, useState } from "react"
import { apiRequest } from "@/lib/api"

type Redaction = { id: string; genre: string; statut: string; phase: string; annonce: boolean; titre?: string }
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

  const piloter = async (r: Redaction, geste: "reprendre" | "suspendre" | "retirer") => {
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
  // Un document prêt ET déjà annoncé n'a plus rien à dire ici : sa carte est dans le fil.
  const visibles = redactions.filter(r => !(r.statut === "termine" && r.annonce))
  if (!visibles.length && !erreur) return null
  return <section aria-label="Travaux en cours" data-testid="suivi-redactions" style={{ padding: "2px 32px 8px", maxHeight: 168, overflowY: "auto" }}>
    {visibles.map(r => {
      const actif = ["attente", "en_cours"].includes(r.statut)
      const nom = r.genre === "quantitatif" ? "Quantitatif" : "Document"
      return <div key={r.id} className="sym-step" role="status" aria-live="polite"
                  style={{ alignItems: "flex-start", fontWeight: 500, fontSize: 13, padding: "4px 0", color: "var(--marque-text-secondary)" }}>
        {actif
          ? <span className="sym-grille" aria-hidden style={{ marginTop: 3 }}><i /><i /><i /><i /><i /><i /><i /><i /><i /></span>
          : <span aria-hidden style={{ width: 16, textAlign: "center" }}>•</span>}
        <span style={{ minWidth: 0 }}>
          <b style={{ color: "var(--marque-text-primary)" }}>{nom}{r.titre ? ` « ${r.titre} »` : ""}</b> — {r.phase}{actif && "…"}
          {r.statut !== "termine" && <>{" "}
            <button type="button" disabled={!!action} onClick={() => void piloter(r, actif ? "suspendre" : "reprendre")}
                    style={{ textDecoration: "underline", fontSize: 12, color: "var(--marque-text-secondary)" }}>
              {action === r.id ? "enregistrement…" : actif ? "suspendre" : "reprendre"}
            </button>
            {/* Un travail arrêté ne reste pas collé en bas : on le retire du suivi
                (ses étapes restent conservées côté serveur, rien n'est effacé). */}
            {!actif && <>{" · "}<button type="button" disabled={!!action} onClick={() => void piloter(r, "retirer")}
                    aria-label="Retirer ce travail du suivi"
                    style={{ textDecoration: "underline", fontSize: 12, color: "var(--marque-text-secondary)" }}>retirer</button></>}
          </>}
        </span>
      </div>
    })}
    {erreur && <p role="alert" style={{ fontSize: 12 }}>{erreur}</p>}
  </section>
}
