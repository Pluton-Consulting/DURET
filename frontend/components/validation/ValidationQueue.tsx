"use client"

import { useCallback, useEffect, useState } from "react"
import { apiRequest } from "@/lib/api"

// File d'attente des validations humaines (HITL). Unifiée : skills (agent3),
// chiffrage (agent2) et actions de l'agent Navigateur (agent='browser', avec capture).
// Le backend expose GET /api/validations et POST /api/validations/{id}/resolve.

interface ValidationItem {
  id: string
  thread_id: string
  agent: string | null
  reason: string | null
  draft: string | null
  payload: Record<string, any> | null
  created_at: string
  requester_email?: string | null
  requester_name?: string | null
}

const AGENT_LABEL: Record<string, string> = {
  browser: "Agent Navigateur",
  agent1: "Agent 1",
  agent2: "Agent 2",
  agent3: "Agent 3",
}

export default function ValidationQueue({ token }: { token: string }) {
  const [items, setItems] = useState<ValidationItem[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await apiRequest<ValidationItem[]>("/api/validations/", { token })
      setItems(data)
      setError(null)
    } catch (e: any) {
      setError(e.message || "Erreur de chargement")
    }
  }, [token])

  useEffect(() => {
    load()
    const id = setInterval(load, 4000)
    return () => clearInterval(id)
  }, [load])

  async function resolve(id: string, approved: boolean) {
    setBusy(id)
    try {
      await apiRequest(`/api/validations/${id}/resolve`, {
        method: "POST",
        token,
        body: JSON.stringify({ approved }),
      })
      setItems((prev) => prev.filter((v) => v.id !== id))
    } catch (e: any) {
      setError(e.message || "Échec de la résolution")
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--color-text-primary)" }}>
          Actions en attente de validation
        </h2>
        <span className="sym-pop" style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 600, color: "var(--color-progress-text)", background: "var(--color-progress-bg)", padding: "4px 12px", borderRadius: "var(--radius-pill)" }}>
          {items.length} en attente
        </span>
      </div>

      {error && (
        <div className="sym-pop" style={{ background: "var(--color-pending-bg)", color: "var(--color-pending-text)", borderRadius: "var(--radius-card-sm)", padding: "10px 14px", fontSize: 13, marginBottom: 12 }}>
          {error}
        </div>
      )}

      {items.length === 0 ? (
        <div className="sym-fade" style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card)", padding: "40px 24px", textAlign: "center", boxShadow: "var(--shadow-card)", color: "var(--color-text-muted)", fontSize: 14 }}>
          Aucune action en attente. Les actions modifiantes de l'agent apparaîtront ici pour approbation.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {items.map((v, i) => {
            const p = v.payload || {}
            const isBrowser = v.agent === "browser"
            const summary = p.summary || v.draft || "—"
            return (
              <div key={v.id} className={`sym-in sym-in-${Math.min(i + 1, 6)} sym-card`} style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card)", padding: 18, boxShadow: "var(--shadow-card)", border: "1px solid var(--color-border)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <span style={{ background: "var(--color-progress-bg)", color: "var(--color-progress-text)", padding: "4px 12px", borderRadius: "var(--radius-pill)", fontSize: 12, fontWeight: 600 }}>
                    {AGENT_LABEL[v.agent || ""] || v.agent || "Agent"}
                  </span>
                  <span style={{ fontSize: 12, color: "var(--color-text-muted)" }}>{v.reason || ""}</span>
                  <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--color-text-muted)" }}>
                    {v.requester_name || v.requester_email || ""}
                  </span>
                </div>

                <div style={{ fontSize: 14, color: "var(--color-text-primary)", lineHeight: 1.5, marginBottom: isBrowser && p.url ? 6 : 12 }}>
                  {summary}
                </div>
                {isBrowser && p.url && (
                  <div style={{ fontFamily: "monospace", fontSize: 12, color: "var(--color-primary-mid)", marginBottom: 12, wordBreak: "break-all" }}>
                    {p.url}
                  </div>
                )}

                {p.screenshot && (
                  <img
                    src={`data:image/jpeg;base64,${p.screenshot}`}
                    alt="Capture de la page"
                    style={{ maxWidth: "100%", borderRadius: "var(--radius-icon)", border: "1px solid var(--color-border)", marginBottom: 14 }}
                  />
                )}

                <div style={{ display: "flex", gap: 10 }}>
                  <button
                    onClick={() => resolve(v.id, true)}
                    disabled={busy === v.id}
                    className="sym-tap"
                    style={{ flex: 1, padding: "10px 16px", borderRadius: "var(--radius-pill)", border: "none", cursor: "pointer", fontWeight: 700, fontSize: 14, background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))", color: "var(--color-text-on-dark)", boxShadow: "var(--shadow-card)", opacity: busy === v.id ? 0.6 : 1 }}
                  >
                    Approuver
                  </button>
                  <button
                    onClick={() => resolve(v.id, false)}
                    disabled={busy === v.id}
                    className="sym-tap"
                    style={{ flex: 1, padding: "10px 16px", borderRadius: "var(--radius-pill)", border: "1px solid var(--color-pending-text)", cursor: "pointer", fontWeight: 700, fontSize: 14, background: "var(--color-surface)", color: "var(--color-pending-text)", opacity: busy === v.id ? 0.6 : 1 }}
                  >
                    Refuser
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
