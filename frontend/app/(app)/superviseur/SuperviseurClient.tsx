"use client"
import { useEffect, useRef, useState, useCallback } from "react"

interface Props { apiUrl: string; token: string }

const POLL_MS = 3000

// Palette console (bandeau sombre) — charte Duret & Sols (bleu), variables CSS uniquement.
// Monospace conservé : fonction terminal (alignement des logs).
const C = {
  bg: "var(--color-text-primary)", panel: "var(--color-primary)", panel2: "var(--color-text-primary)", border: "var(--color-primary-hover)",
  text: "var(--color-text-on-dark)", dim: "var(--color-text-muted)", green: "var(--color-paid-text)", amber: "var(--color-pending-text)",
  red: "var(--color-error-text)", blue: "var(--color-progress-text)", mono: "ui-monospace,'SF Mono','Cascadia Code',Menlo,Consolas,monospace",
}

async function getJSON(apiUrl: string, path: string, token: string) {
  const res = await fetch(`${apiUrl}${path}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

function fmtTime(iso: string) {
  try { return new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) }
  catch { return "--:--:--" }
}

// Aplati les métadonnées JSONB en paires clé=valeur affichables.
function metaEntries(m: any): [string, string][] {
  if (!m || typeof m !== "object") return []
  return Object.entries(m).map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : String(v)])
}

export default function SuperviseurClient({ apiUrl, token }: Props) {
  const [system, setSystem] = useState<any>(null)
  const [logs, setLogs] = useState<any[]>([])
  const [agents, setAgents] = useState<any[]>([])
  const [live, setLive] = useState(true)
  const [err, setErr] = useState<string>("")
  const [tick, setTick] = useState(0)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const logBoxRef = useRef<HTMLDivElement>(null)

  const refresh = useCallback(async () => {
    try {
      const [sys, act, ag] = await Promise.all([
        getJSON(apiUrl, "/api/dashboard/system", token).catch(() => null),
        getJSON(apiUrl, "/api/dashboard/activity?limit=60", token).catch(() => []),
        getJSON(apiUrl, "/api/dashboard/agents-activity", token).catch(() => []),
      ])
      if (sys) setSystem(sys)
      setLogs(Array.isArray(act) ? act : [])
      setAgents(Array.isArray(ag) ? ag : [])
      setErr("")
      setTick((t) => t + 1)
    } catch (e: any) {
      setErr(e?.message || "erreur")
    }
  }, [apiUrl, token])

  useEffect(() => {
    refresh()
    if (!live) return
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [refresh, live])

  const kpi = (label: string, value: any, color = C.text) => (
    <div className="sym-fade sym-card" style={{ background: `linear-gradient(180deg, ${C.panel}, ${C.panel2})`, border: `1px solid ${C.border}`, borderRadius: "var(--radius-card-sm)", padding: "10px 12px" }}>
      <div style={{ fontSize: 10, color: C.dim, textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
      <div style={{ fontFamily: C.mono, fontSize: 16, fontWeight: 600, color, marginTop: 3 }}>{value ?? "—"}</div>
    </div>
  )

  const db = system?.db || {}

  return (
    <div style={{ minHeight: "calc(100vh - 64px)", background: C.bg, color: C.text, fontFamily: C.mono, padding: "20px 24px" }}>
      <style>{`
        @keyframes symFadeUp { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
        @keyframes symLivePulse { 0%,100%{box-shadow:0 0 0 0 color-mix(in srgb, var(--color-paid-text) 55%, transparent)} 50%{box-shadow:0 0 0 7px transparent} }
        .sym-fade{animation:symFadeUp .45s ease both}
        .sym-live{animation:symLivePulse 1.7s ease-in-out infinite}
        .sym-logrow{transition:background-color .15s ease}
        .sym-logrow:hover{background:rgba(255,255,255,.035)}
        @media (prefers-reduced-motion: reduce){ .sym-fade,.sym-live{animation:none} }
      `}</style>
      {/* Header */}
      <div className="sym-in" style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 18 }}>
        <span className={live ? "sym-live" : undefined} style={{ width: 9, height: 9, borderRadius: "50%", background: live ? C.green : C.dim }} />
        <div style={{ fontSize: 18, fontWeight: 700, letterSpacing: "-0.3px" }}>Console développeur</div>
        <div style={{ fontSize: 12, color: C.dim }}>super_admin · flux temps réel</div>
        <div style={{ flex: 1 }} />
        <button onClick={() => setLive((v) => !v)} className="sym-tap" style={{ fontFamily: C.mono, fontSize: 12, background: live ? C.panel : C.panel2, color: live ? C.green : C.dim, border: `1px solid ${C.border}`, borderRadius: "var(--radius-pill)", padding: "6px 12px", cursor: "pointer" }}>
          {live ? "● LIVE (pause)" : "○ figé (reprendre)"}
        </button>
        <button onClick={refresh} className="sym-tap" style={{ fontFamily: C.mono, fontSize: 12, background: C.panel2, color: C.text, border: `1px solid ${C.border}`, borderRadius: "var(--radius-pill)", padding: "6px 12px", cursor: "pointer" }}>
          ↻ refresh
        </button>
      </div>

      {err && <div style={{ color: C.red, fontSize: 12, marginBottom: 12 }}>⚠ {err}</div>}

      {/* System KPIs */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10, marginBottom: 14 }}>
        {kpi("environnement", system?.environment, C.blue)}
        {kpi("debug", String(system?.debug ?? "—"), system?.debug ? C.amber : C.dim)}
        {kpi("checkpointer", system?.checkpointer, C.green)}
        {kpi("langfuse", system?.observability?.langfuse_enabled ? "ON" : "off", system?.observability?.langfuse_enabled ? C.green : C.dim)}
        {kpi("plage horaire", system?.schedule)}
        {kpi("browser", system?.browser_enabled ? "ON" : "off", system?.browser_enabled ? C.green : C.dim)}
      </div>

      {/* DB counters */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginBottom: 18 }}>
        {kpi("users actifs", db.users_actifs)}
        {kpi("threads", db.threads)}
        {kpi("audit events", db.audit_events)}
        {kpi("validations", db.validations_pending, Number(db.validations_pending) > 0 ? C.amber : C.text)}
        {kpi("skills", db.skills)}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 16 }}>
        {/* Live log stream */}
        <div className="sym-in" style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: "var(--radius-card)", boxShadow: "var(--shadow-card)", overflow: "hidden" }}>
          <div style={{ padding: "10px 14px", borderBottom: `1px solid ${C.border}`, fontSize: 12, color: C.dim, display: "flex", justifyContent: "space-between" }}>
            <span>audit_log · {logs.length} événements · cliquer une ligne pour le détail</span>
            <span>maj #{tick}</span>
          </div>
          <div ref={logBoxRef} style={{ maxHeight: 520, overflowY: "auto", padding: "6px 0" }}>
            {logs.length === 0 && <div style={{ padding: 20, color: C.dim, fontSize: 12 }}>— aucun événement —</div>}
            {logs.map((l: any) => {
              const ok = l.success !== false
              const entries = metaEntries(l.metadata)
              const isOpen = !!open[l.id]
              const hasDetail = entries.length > 0 || !!l.error_message
              const toks = (l.tokens_in || 0) + (l.tokens_out || 0)
              return (
                <div key={l.id} className="sym-in" style={{ borderBottom: `1px solid ${C.panel2}` }}>
                  {/* Ligne principale */}
                  <div
                    onClick={() => hasDetail && setOpen((o) => ({ ...o, [l.id]: !o[l.id] }))}
                    className="sym-logrow"
                    style={{ display: "flex", gap: 10, padding: "5px 14px", fontSize: 12.5, whiteSpace: "nowrap", alignItems: "center", cursor: hasDetail ? "pointer" : "default" }}
                  >
                    <span style={{ color: C.dim, width: 62 }}>{fmtTime(l.created_at)}</span>
                    <span style={{ color: ok ? C.green : C.red, width: 12 }}>{ok ? "✓" : "✗"}</span>
                    <span style={{ color: ok ? C.text : C.red, minWidth: 172, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis" }}>{l.action}</span>
                    <span style={{ color: C.blue, width: 92, overflow: "hidden", textOverflow: "ellipsis" }}>{l.agent_id ? `[${l.agent_id}]` : ""}</span>
                    <span style={{ color: C.amber, width: 120, overflow: "hidden", textOverflow: "ellipsis" }}>{l.model_used || ""}</span>
                    <span style={{ color: C.dim, width: 96, textAlign: "right" }}>
                      {l.duration_ms != null ? `${l.duration_ms}ms` : ""}{toks ? ` · ${toks}tk` : ""}
                    </span>
                    <span style={{ flex: 1 }} />
                    <span style={{ color: C.dim }}>{l.user_id ? String(l.user_id).slice(0, 8) : "system"}</span>
                    <span style={{ color: C.dim, width: 14, textAlign: "center" }}>{hasDetail ? (isOpen ? "▾" : "▸") : ""}</span>
                  </div>

                  {/* Aperçu compact (replié) */}
                  {!isOpen && hasDetail && (
                    <div style={{ padding: "0 14px 6px 88px", fontSize: 11.5, color: C.dim, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {l.error_message && <span style={{ color: C.red }}>⚠ {l.error_message}{entries.length ? " · " : ""}</span>}
                      {entries.slice(0, 5).map(([k, v], i) => (
                        <span key={k}>{i > 0 && " · "}<span style={{ color: C.dim }}>{k}=</span><span style={{ color: C.text }}>{v.length > 44 ? v.slice(0, 44) + "…" : v}</span></span>
                      ))}
                    </div>
                  )}

                  {/* Détail complet (déplié) */}
                  {isOpen && (
                    <div style={{ padding: "2px 14px 10px 88px", fontSize: 11.5 }}>
                      {l.error_message && <div style={{ color: C.red, marginBottom: 6, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>⚠ {l.error_message}</div>}
                      {entries.length > 0 && (
                        <pre style={{ margin: 0, color: C.text, background: C.panel2, border: `1px solid ${C.border}`, borderRadius: "var(--radius-icon)", padding: "8px 10px", whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.55 }}>
                          {entries.map(([k, v]) => `${k}: ${v}`).join("\n")}
                        </pre>
                      )}
                      <div style={{ color: C.dim, marginTop: 6 }}>
                        id {String(l.id).slice(0, 8)} · user {l.user_id ? String(l.user_id) : "system"}
                        {toks ? ` · ${l.tokens_in || 0}→${l.tokens_out || 0} tokens` : ""}
                        {l.cost_eur ? ` · ${Number(l.cost_eur).toFixed(4)}€` : ""}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Side: providers + chains + agents */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="sym-card sym-in sym-in-1" style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: "var(--radius-card)", boxShadow: "var(--shadow-card)", padding: 14 }}>
            <div style={{ fontSize: 12, color: C.dim, marginBottom: 10 }}>fournisseurs LLM</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {system?.providers && Object.entries(system.providers).map(([p, up]: any) => (
                <span key={p} style={{ fontSize: 11, padding: "3px 8px", borderRadius: "var(--radius-pill)", background: up ? "var(--color-paid-bg)" : C.panel2, color: up ? C.green : C.dim, border: `1px solid ${up ? "var(--color-paid-text)" : C.border}` }}>
                  {up ? "●" : "○"} {p}
                </span>
              ))}
            </div>
          </div>

          <div className="sym-card sym-in sym-in-2" style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: "var(--radius-card)", boxShadow: "var(--shadow-card)", padding: 14 }}>
            <div style={{ fontSize: 12, color: C.dim, marginBottom: 10 }}>cascade (par palier)</div>
            {system?.chains && Object.entries(system.chains).map(([tier, list]: any) => (
              <div key={tier} style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 11, color: C.amber, textTransform: "uppercase" }}>{tier}</div>
                <div style={{ fontSize: 11, color: C.text, lineHeight: 1.5, wordBreak: "break-all" }}>
                  {(list as string[]).join(" → ") || "—"}
                </div>
              </div>
            ))}
          </div>

          <div className="sym-card sym-in sym-in-3" style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: "var(--radius-card)", boxShadow: "var(--shadow-card)", padding: 14 }}>
            <div style={{ fontSize: 12, color: C.dim, marginBottom: 10 }}>agents (aujourd'hui)</div>
            {agents.length === 0 && <div style={{ fontSize: 11, color: C.dim }}>— aucune requête —</div>}
            {agents.map((a: any) => (
              <div key={a.agent_id} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "3px 0" }}>
                <span style={{ color: C.blue }}>{a.agent_id}</span>
                <span style={{ color: C.dim }}>
                  {a.request_count} req · <span style={{ color: C.green }}>{a.success_count}✓</span> <span style={{ color: C.red }}>{a.failure_count}✗</span> · {a.avg_duration_ms}ms
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
