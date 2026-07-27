"use client"

import { useCallback, useEffect, useState } from "react"
import { apiRequest } from "@/lib/api"
import ValidationQueue from "@/components/validation/ValidationQueue"

interface BrowserTask {
  id: string
  status: string
  task_prompt: string
  allowed_domains: string[]
  steps: number
  error: string | null
  result?: {
    summary?: string
    steps?: number
    step_log?: { n: number; url?: string | null; action?: string | null }[]
  } | null
  created_at: string
  updated_at: string
}

const STATUS_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  pending:           { bg: "var(--color-pending-bg)", fg: "var(--color-pending-text)", label: "En attente" },
  running:           { bg: "var(--color-progress-bg)", fg: "var(--color-progress-text)", label: "En cours" },
  awaiting_approval: { bg: "var(--color-pending-bg)", fg: "var(--color-pending-text)", label: "Validation requise" },
  completed:         { bg: "var(--color-paid-bg)", fg: "var(--color-paid-text)", label: "Terminé" },
  failed:            { bg: "var(--color-error-bg)", fg: "var(--color-error-text)", label: "Échec" },
  cancelled:         { bg: "var(--color-canvas)", fg: "var(--color-text-muted)", label: "Annulé" },
}

export default function NavigateurClient({ token }: { token: string; role: string }) {
  const [task, setTask] = useState("")
  const [domains, setDomains] = useState("")
  const [ingest, setIngest] = useState(false)
  const [writeMode, setWriteMode] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tasks, setTasks] = useState<BrowserTask[]>([])
  const [openTask, setOpenTask] = useState<Record<string, boolean>>({})

  const loadTasks = useCallback(async () => {
    try {
      const data = await apiRequest<BrowserTask[]>("/api/browser/tasks", { token })
      setTasks(data)
    } catch {
      /* silencieux : le polling réessaiera */
    }
  }, [token])

  useEffect(() => {
    loadTasks()
    const id = setInterval(loadTasks, 5000)
    return () => clearInterval(id)
  }, [loadTasks])

  async function launch() {
    setError(null)
    const allowed = domains.split(",").map((d) => d.trim()).filter(Boolean)
    if (!task.trim()) { setError("Décris la tâche à effectuer."); return }
    if (allowed.length === 0) { setError("Indique au moins un domaine autorisé."); return }
    setLaunching(true)
    try {
      await apiRequest("/api/browser/run", {
        method: "POST",
        token,
        body: JSON.stringify({ task, allowed_domains: allowed, ingest, readonly: !writeMode }),
      })
      setTask("")
      await loadTasks()
    } catch (e: any) {
      setError(e.message || "Échec du lancement")
    } finally {
      setLaunching(false)
    }
  }

  async function cancel(id: string) {
    try {
      await apiRequest(`/api/browser/tasks/${id}/cancel`, { method: "POST", token })
      await loadTasks()
    } catch { /* ignore */ }
  }

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "10px 12px", borderRadius: "var(--radius-icon)",
    border: "1px solid var(--color-border)", fontSize: 14,
    fontFamily: "inherit", boxSizing: "border-box",
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 32 }}>
      {/* Lancement */}
      <div className="sym-in sym-in-1" style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", padding: 24, boxShadow: "var(--shadow-card)" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 6 }}>
          Agent navigateur
        </div>
        <h2 style={{ margin: "0 0 14px", fontSize: 18, fontWeight: 700, color: "var(--color-text-primary)" }}>
          Nouvelle tâche
        </h2>
        <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: "var(--color-text-body)", marginBottom: 6 }}>
          Que doit faire l'agent ?
        </label>
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          rows={3}
          placeholder="Ex : va sur le site fournisseur, cherche le prix HT du composteur 400L et renvoie le prix."
          style={{ ...inputStyle, resize: "vertical", marginBottom: 14 }}
        />
        <label style={{ display: "block", fontSize: 13, fontWeight: 600, color: "var(--color-text-body)", marginBottom: 6 }}>
          Domaines autorisés (séparés par des virgules)
        </label>
        <input
          value={domains}
          onChange={(e) => setDomains(e.target.value)}
          placeholder="myfiteco.com, ediflex.fr"
          style={{ ...inputStyle, marginBottom: 14 }}
        />
        <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 13, color: "var(--color-text-body)", marginBottom: 10, cursor: "pointer" }}>
          <input type="checkbox" checked={writeMode} onChange={(e) => setWriteMode(e.target.checked)} style={{ marginTop: 3 }} />
          <span><b>Mode écriture</b> pour cette tâche — autorise la saisie, le clic et la soumission de formulaires (login…). ⚠️ à surveiller.</span>
        </label>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--color-text-body)", marginBottom: 16, cursor: "pointer" }}>
          <input type="checkbox" checked={ingest} onChange={(e) => setIngest(e.target.checked)} />
          Réinjecter le résultat dans la base documentaire (RAG)
        </label>

        {error && (
          <div className="sym-pop" style={{ background: "var(--color-pending-bg)", color: "var(--color-pending-text)", borderRadius: "var(--radius-icon)", padding: "10px 14px", fontSize: 13, marginBottom: 14 }}>
            {error}
          </div>
        )}

        <button
          onClick={launch}
          disabled={launching}
          className="sym-tap"
          style={{ padding: "11px 22px", borderRadius: "var(--radius-pill)", border: "none", cursor: "pointer", fontWeight: 700, fontSize: 14, background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))", color: "var(--color-text-on-dark)", opacity: launching ? 0.6 : 1, boxShadow: "var(--shadow-card)", transition: "opacity .2s ease, box-shadow .2s ease" }}
        >
          {launching ? "Lancement…" : "Lancer la tâche"}
        </button>
        <p style={{ margin: "12px 0 0", fontSize: 12, color: "var(--color-text-muted)", lineHeight: 1.5 }}>
          Toute action modifiante (soumettre, envoyer, écrire…) sera mise en pause et devra être approuvée ci-dessous avant exécution.
        </p>
      </div>

      {/* File de validation (HITL) */}
      <ValidationQueue token={token} />

      {/* Historique des tâches */}
      <div className="sym-in sym-in-2">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 11, letterSpacing: "0.08em", textTransform: "uppercase", fontWeight: 600, color: "var(--color-text-muted)", marginBottom: 4 }}>
              Historique
            </div>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--color-text-primary)" }}>Tâches récentes</h2>
          </div>
          <span style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 600, color: "var(--color-text-muted)", background: "var(--color-canvas)", borderRadius: "var(--radius-pill)", padding: "2px 12px" }}>{tasks.length}</span>
        </div>
        {tasks.length === 0 ? (
          <div className="sym-fade" style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card)", padding: "40px 24px", textAlign: "center", boxShadow: "var(--shadow-card)", color: "var(--color-text-muted)", fontSize: 14 }}>
            Aucune tâche lancée pour l'instant.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {tasks.map((t, i) => {
              const st = STATUS_STYLE[t.status] || { bg: "var(--color-canvas)", fg: "var(--color-text-muted)", label: t.status }
              const active = t.status === "running" || t.status === "awaiting_approval" || t.status === "pending"
              return (
                <div key={t.id} className={`sym-in sym-in-${Math.min(i + 1, 6)} sym-card`} style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card-sm)", padding: "16px 20px", boxShadow: "var(--shadow-card)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 14, color: "var(--color-text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.task_prompt}</div>
                      <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3 }}>
                        {(t.allowed_domains || []).join(", ")} · {t.steps} étape(s){t.error ? ` · ${t.error}` : ""}
                      </div>
                    </div>
                    <span className="sym-pop" style={{ background: st.bg, color: st.fg, padding: "5px 12px", borderRadius: "var(--radius-pill)", fontSize: 12, fontWeight: 600, whiteSpace: "nowrap" }}>
                      {st.label}
                    </span>
                    {active && (
                      <button
                        onClick={() => cancel(t.id)}
                        className="sym-tap"
                        style={{ padding: "6px 12px", borderRadius: "var(--radius-pill)", border: "1px solid var(--color-border)", background: "var(--color-surface)", cursor: "pointer", fontSize: 12, color: "var(--color-text-body)", transition: "background .2s ease, color .2s ease, border-color .2s ease" }}
                      >
                        Annuler
                      </button>
                    )}
                  </div>
                  {(t.status === "completed" || t.status === "failed") && (
                    <div style={{ marginTop: 12 }}>
                      <button
                        onClick={() => setOpenTask((o) => ({ ...o, [t.id]: !o[t.id] }))}
                        className="sym-tap"
                        style={{ background: "none", border: "1px solid var(--color-border)", borderRadius: "var(--radius-pill)", padding: "5px 12px", fontSize: 12, cursor: "pointer", color: "var(--color-primary)", fontWeight: 600, transition: "background .2s ease, border-color .2s ease" }}
                      >
                        {openTask[t.id] ? "Masquer le détail" : `Voir le détail (${t.steps} étape${t.steps > 1 ? "s" : ""})`}
                      </button>

                      {openTask[t.id] && (
                        <div className="sym-fade" style={{ marginTop: 10 }}>
                          {/* Résultat / résumé */}
                          <div style={{ padding: "12px 14px", background: "var(--color-canvas)", borderRadius: "var(--radius-icon)", fontSize: 13, color: "var(--color-text-body)", lineHeight: 1.55, whiteSpace: "pre-wrap", marginBottom: 12 }}>
                            {t.result?.summary
                              ? t.result.summary
                              : <span style={{ color: "var(--color-text-muted)", fontStyle: "italic" }}>Aucun résumé rédigé par l'agent.</span>}
                          </div>

                          {/* Démarche étape par étape */}
                          {t.result?.step_log && t.result.step_log.length > 0 && (
                            <div>
                              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>
                                Démarche de l'agent
                              </div>
                              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                                {t.result.step_log.map((s, i) => (
                                  <div key={s.n} className={`sym-in sym-in-${Math.min(i + 1, 6)}`} style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 12, padding: "6px 10px", background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-icon)" }}>
                                    <span style={{ fontWeight: 700, color: "var(--color-primary-mid)", minWidth: 24, flexShrink: 0 }}>#{s.n}</span>
                                    <span style={{ fontWeight: 600, color: "var(--color-text-primary)", minWidth: 130, flexShrink: 0 }}>{s.action || "—"}</span>
                                    <span style={{ color: "var(--color-text-muted)", wordBreak: "break-all" }}>{s.url || ""}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
