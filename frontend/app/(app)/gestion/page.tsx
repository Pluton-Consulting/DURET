"use client"
import { useState } from "react"
import { useSession } from "next-auth/react"
import { useRouter } from "next/navigation"

type GestionTab = "logs" | "couts" | "erreurs" | "cartographie" | "prompts"

const PROMPTS = [
  { agent: "Agent 1", name: "system_commercial", version: "v3", modified: "Il y a 3 jours", tokens: 482, body: "Tu es Duret & Sols, assistant IA interne de Duret & Sols, entreprise de travaux de sols et revêtements (BTP). Tu aides les équipes commerciales et administratives à répondre aux questions sur nos chantiers, nos catalogues fournisseurs et nos outils métier (MyFiteco, Ediflex)..." },
  { agent: "Agent 2", name: "system_conception", version: "v2", modified: "Il y a 1 semaine", tokens: 634, body: "Tu es Duret & Sols, spécialisé en études, chiffrage et analyse de plans. Tu analyses les plans (CCTP, DPGF, DWG), photos de chantier, et fiches techniques pour produire des estimations de coûts et des extractions structurées..." },
  { agent: "Agent 3", name: "system_superviseur", version: "v1", modified: "Il y a 2 semaines", tokens: 812, body: "Tu es Duret & Sols superviseur, chargé d'identifier les lacunes de connaissances de l'équipe et de générer automatiquement des skills Python réutilisables. Chaque skill doit exposer run(data: dict) -> dict..." },
]

/* ── CARTOGRAPHY (Request Flow Diagram) ── */
function Cartography({ steps }: { steps: { name: string; ms: number; error?: boolean }[] }) {
  if (!steps.length) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--marque-text-muted)", fontSize: 14 }}>
        Sélectionnez une requête dans les logs pour voir sa cartographie
      </div>
    )
  }

  const total = steps.reduce((s, n) => s + n.ms, 0)

  return (
    <div>
      <div style={{ fontSize: 13, color: "var(--marque-text-muted)", marginBottom: 20 }}>
        Durée totale : <strong style={{ color: "var(--marque-text-primary)" }}>{total}ms</strong>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {steps.map((step, i) => {
          const pct = (step.ms / total) * 100
          const isError = step.error
          const isSlow = step.ms > 500
          const color = isError ? "var(--marque-error-text)" : isSlow ? "var(--marque-pending-text)" : "var(--marque-paid-text)"
          const bg = isError ? "var(--marque-error-bg)" : isSlow ? "var(--marque-pending-bg)" : "var(--marque-paid-bg)"
          const barColor = isError ? "var(--marque-error-text)" : isSlow ? "var(--marque-pending-text)" : "var(--marque-primary-mid)"

          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 0", borderBottom: i < steps.length - 1 ? "1px solid var(--marque-border)" : "none" }}>
              {/* Step number */}
              <div style={{ width: 24, height: 24, borderRadius: "50%", background: isError ? "var(--marque-error-bg)" : "var(--marque-primary-subtle)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: isError ? "var(--marque-error-text)" : "var(--marque-primary)", flexShrink: 0 }}>
                {i + 1}
              </div>
              {/* Name */}
              <div style={{ width: 140, fontSize: 13, fontWeight: 600, color: "var(--marque-text-primary)", flexShrink: 0 }}>
                {step.name}
                {isError && <span style={{ marginLeft: 4, fontSize: 11, color: "var(--marque-error-text)" }}>erreur</span>}
              </div>
              {/* Bar */}
              <div style={{ flex: 1, height: 8, background: "var(--marque-border)", borderRadius: 4 }}>
                <div style={{ height: 8, borderRadius: 4, background: barColor, width: `${Math.max(pct, 1)}%`, transition: "width 0.3s" }} />
              </div>
              {/* Duration */}
              <div style={{ width: 60, textAlign: "right", fontSize: 13, fontWeight: 700, color, flexShrink: 0 }}>
                {step.ms}ms
              </div>
              {/* Badge */}
              <span style={{ fontSize: 10, fontWeight: 700, color, background: bg, padding: "2px 8px", borderRadius: "var(--marque-radius-pill)", flexShrink: 0, width: 62, textAlign: "center" }}>
                {isError ? "ERROR" : isSlow ? "LENT" : "OK"}
              </span>
            </div>
          )
        })}
      </div>

      {/* Summary row */}
      <div className="sym-pop" style={{ marginTop: 20, padding: 16, background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))", borderRadius: 12, display: "flex", alignItems: "center", gap: 20 }}>
        <div>
          <div style={{ fontSize: 11, color: "var(--marque-on-dark-accent)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>Total</div>
          <div style={{ fontSize: 24, fontWeight: 800, color: "var(--marque-text-on-dark)" }}>{total}ms</div>
        </div>
        <div style={{ width: 1, height: 40, background: "var(--marque-primary-hover)" }} />
        <div>
          <div style={{ fontSize: 11, color: "var(--marque-on-dark-accent)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>Étapes</div>
          <div style={{ fontSize: 24, fontWeight: 800, color: "var(--marque-text-on-dark)" }}>{steps.length}</div>
        </div>
        <div style={{ width: 1, height: 40, background: "var(--marque-primary-hover)" }} />
        <div>
          <div style={{ fontSize: 11, color: "var(--marque-on-dark-accent)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>Goulot</div>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-on-dark)" }}>
            {steps.reduce((a, b) => a.ms > b.ms ? a : b).name}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── MAIN COMPONENT ── */
export default function GestionPage() {
  const { data: session } = useSession()
  const router = useRouter()
  const [activeTab, setActiveTab] = useState<GestionTab>("logs")
  const [editingPrompt, setEditingPrompt] = useState<string | null>(null)

  const role = (session as any)?.user?.role
  if (session && role !== "direction" && role !== "super_admin") { router.replace("/accueil"); return null }

  const tabs: { key: GestionTab; label: string }[] = [
    { key: "logs", label: "Logs" },
    { key: "couts", label: "Coûts" },
    { key: "erreurs", label: "Erreurs" },
    { key: "cartographie", label: "Cartographie" },
    { key: "prompts", label: "Prompts" },
  ]

  return (
    <div className="sym-page" style={{ padding: 32, maxWidth: 1300, margin: "0 auto" }}>
      {/* Header */}
      <div className="sym-in" style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-0.5px" }}>
          Gestion
        </h1>
        <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--marque-text-muted)" }}>
          Supervision — logs, coûts, prompts. ⚠ Certaines sections (prompts, cartographie) affichent encore des données de démonstration ; les métriques réelles sont dans l'onglet Développeur.
        </p>
      </div>

      {/* KPI row */}
      <div className="sym-grid-auto" style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14, marginBottom: 24 }}>
        {[
          { label: "Requêtes totales" },
          { label: "Erreurs 24h" },
          { label: "Coût total" },
          { label: "Skills créés" },
          { label: "Uptime" },
        ].map((kpi, i) => (
          <div key={i} className={`sym-in sym-in-${i + 1} sym-card`} style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card-sm, 14px)", padding: "16px 18px", boxShadow: "var(--marque-shadow-card)" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>{kpi.label}</div>
            <div style={{ fontSize: 26, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-0.5px" }}>—</div>
          </div>
        ))}
      </div>

      {/* Sub-tab nav */}
      <div className="sym-in" style={{ display: "flex", gap: 2, marginBottom: 24, background: "var(--marque-surface)", padding: 6, borderRadius: 14, width: "fit-content", boxShadow: "var(--marque-shadow-card)" }}>
        {tabs.map((t) => {
          const active = activeTab === t.key
          return (
            <button key={t.key} onClick={() => setActiveTab(t.key)} className="sym-tap" style={{
              padding: "8px 18px", border: "none", cursor: "pointer",
              borderRadius: 10, fontSize: 14, fontWeight: active ? 700 : 500,
              color: active ? "var(--marque-primary)" : "var(--marque-text-muted)",
              background: active ? "var(--marque-primary-subtle)" : "transparent",
              boxShadow: active ? "var(--marque-shadow-card)" : "none",
              transition: "all 0.15s",
            }}>
              {t.label}
            </button>
          )
        })}
      </div>

      {/* ── LOGS TAB ── */}
      {activeTab === "logs" && (
        <div className="sym-in sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
          <h3 style={{ margin: "0 0 16px", fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Logs temps réel</h3>
          <div style={{ padding: "48px 24px", textAlign: "center", color: "var(--marque-text-muted)", fontSize: 13, border: "1.5px dashed var(--marque-border)", borderRadius: 12 }}>
            <div style={{ marginBottom: 8 }}>Route <code style={{ fontFamily: "monospace", background: "var(--marque-canvas)", padding: "2px 6px", borderRadius: 4 }}>/api/logs</code> non implémentée</div>
            <div style={{ fontSize: 12 }}>
              Activité d'audit disponible via{" "}
              <code style={{ fontFamily: "monospace", background: "var(--marque-canvas)", padding: "2px 6px", borderRadius: 4 }}>/api/dashboard/activity</code>{" "}
              (action, agent_id, success, created_at)
            </div>
          </div>
        </div>
      )}

      {/* ── COUTS TAB ── */}
      {activeTab === "couts" && (
        <div className="sym-in sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
          <h3 style={{ margin: "0 0 8px", fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Coûts par utilisateur</h3>
          <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--marque-text-muted)" }}>
            Agrégation par rôle disponible via <code style={{ fontFamily: "monospace", background: "var(--marque-canvas)", padding: "2px 6px", borderRadius: 4 }}>/api/dashboard/global</code> — détail par utilisateur non implémenté.
          </p>
          <div style={{ padding: "48px 24px", textAlign: "center", color: "var(--marque-text-muted)", fontSize: 13, border: "1.5px dashed var(--marque-border)", borderRadius: 12 }}>
            Route <code style={{ fontFamily: "monospace", background: "var(--marque-canvas)", padding: "2px 6px", borderRadius: 4 }}>/api/costs/breakdown</code> non implémentée
          </div>
        </div>
      )}

      {/* ── ERREURS TAB ── */}
      {activeTab === "erreurs" && (
        <div className="sym-in sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
          <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 700, color: "var(--marque-text-primary)" }}>
            Erreurs des dernières 24h
          </h3>
          <div style={{ padding: "48px 24px", textAlign: "center", color: "var(--marque-text-muted)", fontSize: 13, border: "1.5px dashed var(--marque-border)", borderRadius: 12 }}>
            Route <code style={{ fontFamily: "monospace", background: "var(--marque-canvas)", padding: "2px 6px", borderRadius: 4 }}>/api/logs/errors</code> non implémentée
          </div>
        </div>
      )}

      {/* ── CARTOGRAPHIE TAB ── */}
      {activeTab === "cartographie" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Architecture diagram */}
          <div className="sym-in sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 32, boxShadow: "var(--marque-shadow-card)" }}>
            <h3 style={{ margin: "0 0 24px", fontSize: 16, fontWeight: 700, color: "var(--marque-text-primary)" }}>
              Architecture — Flux d'une requête Duret & Sols
            </h3>
            <div style={{ display: "flex", alignItems: "center", gap: 0, flexWrap: "wrap", rowGap: 32 }}>
              {[
                { label: "Client", sub: "Browser", color: "var(--marque-progress-text)", bg: "var(--marque-progress-bg)" },
                null,
                { label: "Nginx", sub: "Reverse proxy", color: "var(--marque-paid-text)", bg: "var(--marque-paid-bg)" },
                null,
                { label: "JWT Auth", sub: "2-5ms", color: "var(--marque-paid-text)", bg: "var(--marque-paid-bg)" },
                null,
                { label: "Plage horaire", sub: "1ms", color: "var(--marque-pending-text)", bg: "var(--marque-pending-bg)" },
                null,
                { label: "Rate limit", sub: "1ms", color: "var(--marque-pending-text)", bg: "var(--marque-pending-bg)" },
                null,
                { label: "RBAC", sub: "3-5ms", color: "var(--marque-paid-text)", bg: "var(--marque-paid-bg)" },
              ].map((node, i) => {
                if (!node) return <div key={i} style={{ fontSize: 18, color: "var(--marque-text-muted)", padding: "0 4px" }}>→</div>
                return (
                  <div key={i} style={{ background: node.bg, border: "2px solid var(--marque-border)", borderRadius: 12, padding: "12px 16px", textAlign: "center", minWidth: 100 }}>
                    <div style={{ fontSize: 15, marginBottom: 4 }}>{node.label}</div>
                    <div style={{ fontSize: 10, color: node.color, fontWeight: 700 }}>{node.sub}</div>
                  </div>
                )
              })}
            </div>

            {/* Second row — agents */}
            <div style={{ marginTop: 32, display: "flex", alignItems: "flex-start", gap: 24 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 20 }}>
                <div style={{ background: "var(--marque-primary-subtle)", border: "2px solid var(--marque-primary-light)", borderRadius: 12, padding: "12px 16px", textAlign: "center", minWidth: 100 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4, color: "var(--marque-primary)" }}>Router</div>
                  <div style={{ fontSize: 10, color: "var(--marque-primary)", fontWeight: 700 }}>5ms</div>
                </div>
                <span style={{ fontSize: 18, color: "var(--marque-text-muted)", padding: "0 4px" }}>→</span>
              </div>

              <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
                {[
                  { label: "Agent 1 — NER → RAG → LLM STANDARD", color: "var(--marque-progress-text)", bg: "var(--marque-progress-bg)", pipeline: "NER (TODO) → 250ms · RAG (TODO) → 200ms · Haiku → 2s" },
                  { label: "Agent 2 — Vision → RAG → LLM COMPLEX", color: "var(--marque-primary)", bg: "var(--marque-primary-subtle)", pipeline: "Vision (TODO) → 500ms · RAG (TODO) → 300ms · Sonnet → 4s" },
                  { label: "Agent 3 — Gap → Generate → Sandbox", color: "var(--marque-paid-text)", bg: "var(--marque-paid-bg)", pipeline: "Gap (TODO) → LLM → Daytona → 1s" },
                ].map((a, i) => (
                  <div key={i} className={`sym-in sym-in-${i + 1} sym-card`} style={{ background: a.bg, border: "2px solid var(--marque-border)", borderRadius: 12, padding: 16 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: a.color, marginBottom: 6 }}>{a.label}</div>
                    <div style={{ fontSize: 12, fontFamily: "monospace", color: "var(--marque-text-muted)" }}>{a.pipeline}</div>
                  </div>
                ))}
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 20 }}>
                <span style={{ fontSize: 18, color: "var(--marque-text-muted)", padding: "0 4px" }}>→</span>
                <div style={{ background: "var(--marque-paid-bg)", border: "2px solid var(--marque-primary-light)", borderRadius: 12, padding: "12px 16px", textAlign: "center", minWidth: 100 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 4, color: "var(--marque-paid-text)" }}>Response</div>
                  <div style={{ fontSize: 10, color: "var(--marque-paid-text)", fontWeight: 700 }}>JSON/SSE</div>
                </div>
              </div>
            </div>
          </div>

          {/* Drill-down — non implémenté */}
          <div className="sym-in sym-in-2 sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
            <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 700, color: "var(--marque-text-primary)" }}>
              Drill-down par requête
            </h3>
            <div style={{ padding: "48px 24px", textAlign: "center", color: "var(--marque-text-muted)", fontSize: 13, border: "1.5px dashed var(--marque-border)", borderRadius: 12 }}>
              Disponible une fois <code style={{ fontFamily: "monospace", background: "var(--marque-canvas)", padding: "2px 6px", borderRadius: 4 }}>/api/logs</code> implémentée — les traces par étape (NER, RAG, LLM) seront visibles ici
            </div>
          </div>
        </div>
      )}

      {/* ── PROMPTS TAB ── */}
      {activeTab === "prompts" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {PROMPTS.map((p, i) => (
            <div key={p.name} className={`sym-in sym-in-${i + 1} sym-card`} style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                    <span style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>{p.agent}</span>
                    <code style={{ fontSize: 12, color: "var(--marque-primary)", background: "var(--marque-primary-subtle)", padding: "2px 8px", borderRadius: 6 }}>{p.name}</code>
                    <span style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", background: "var(--marque-border)", padding: "2px 8px", borderRadius: "var(--marque-radius-pill)" }}>{p.version}</span>
                  </div>
                  <div style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>
                    Modifié {p.modified} · {p.tokens} tokens
                  </div>
                </div>
                <button
                  onClick={() => setEditingPrompt(editingPrompt === p.name ? null : p.name)}
                  className="sym-tap"
                  style={{ background: editingPrompt === p.name ? "var(--marque-error-bg)" : "var(--marque-primary)", color: editingPrompt === p.name ? "var(--marque-error-text)" : "var(--marque-text-on-dark)", border: "none", borderRadius: "var(--marque-radius-pill)", padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
                >
                  {editingPrompt === p.name ? "Fermer" : "Modifier"}
                </button>
              </div>

              {editingPrompt === p.name ? (
                <div className="sym-fade">
                  <textarea
                    defaultValue={p.body}
                    style={{ width: "100%", minHeight: 180, padding: 14, border: "1.5px solid var(--marque-primary-light)", borderRadius: 10, fontSize: 13, lineHeight: 1.6, fontFamily: "monospace", color: "var(--marque-text-body)", outline: "none", resize: "vertical" }}
                  />
                  <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                    <button className="sym-tap" style={{ background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))", color: "var(--marque-text-on-dark)", border: "none", borderRadius: "var(--marque-radius-pill)", padding: "8px 20px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                      Sauvegarder v{parseInt(p.version.slice(1)) + 1}
                    </button>
                    <button onClick={() => setEditingPrompt(null)} className="sym-tap" style={{ background: "var(--marque-surface)", color: "var(--marque-text-body)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)", padding: "8px 20px", fontSize: 13, cursor: "pointer" }}>
                      Annuler
                    </button>
                  </div>
                </div>
              ) : (
                <div className="sym-fade" style={{ fontSize: 13, color: "var(--marque-text-muted)", lineHeight: 1.6, padding: "12px 14px", background: "var(--marque-canvas)", borderRadius: 8, fontFamily: "monospace" }}>
                  {p.body.slice(0, 200)}…
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
