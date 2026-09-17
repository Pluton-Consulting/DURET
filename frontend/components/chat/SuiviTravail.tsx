"use client"
import { useEffect, useState } from "react"
import { apiRequest } from "@/lib/api"

type Travail = { objectif?: string; contraintes?: { id: string; citation: string; active: boolean }[]; etapes?: unknown[]; resultats?: { skill?: string; ok?: boolean; effect_status?: string }[] }
export default function SuiviTravail({ threadId, token, enCours }: { threadId: string | null; token: string | null; enCours: boolean }) {
  const [travail, setTravail] = useState<Travail | null>(null)
  const [erreur, setErreur] = useState("")
  useEffect(() => {
    let actif = true
    setTravail(null); setErreur("")
    if (!threadId || !token) return
    apiRequest<Travail>(`/api/chat/threads/${encodeURIComponent(threadId)}/travail`, { token })
      .then(v => { if (actif) setTravail(v) })
      .catch(() => { if (actif) setErreur("Suivi temporairement indisponible") })
    return () => { actif = false }
  }, [threadId, token, enCours])
  if (!travail?.objectif && !erreur) return null
  return <details style={{ padding: "8px 16px", borderBottom: "1px solid var(--marque-border)", maxHeight: 220, overflowY: "auto", fontSize: 13 }}>
    <summary style={{ cursor: "pointer" }}>Travail en cours</summary>
    {erreur && <p>{erreur}</p>}
    <p>{travail?.objectif}</p>
    {!!travail?.contraintes?.filter(c => c.active).length && <><strong>Précisions retenues</strong><ul>{travail.contraintes.filter(c => c.active).map(c => <li key={c.id}>{c.citation}</li>)}</ul></>}
    {!!travail?.resultats?.length && <><strong>Derniers résultats observés</strong><ul>{travail.resultats.slice(-5).map((r,i) => <li key={i}>{r.skill} : {r.effect_status === "unknown" ? "résultat à vérifier" : r.ok ? "résultat reçu" : "non abouti"}</li>)}</ul></>}
  </details>
}
