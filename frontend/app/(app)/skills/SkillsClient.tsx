"use client"
import { useCallback, useEffect, useMemo, useState } from "react"

interface Props { apiUrl: string; token: string }

interface Skill {
  name: string
  description: string | null
  status: string
  agent: string | null
  category: string | null
  enabled: boolean
  confidence_score: number | null
  usage_count: number
}

const STATUS_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  draft: { bg: "var(--marque-pending-bg)", fg: "var(--marque-pending-text)", label: "Brouillon" },
  testing: { bg: "var(--marque-progress-bg)", fg: "var(--marque-progress-text)", label: "En test" },
  validated: { bg: "var(--marque-paid-bg)", fg: "var(--marque-paid-text)", label: "Validé" },
  stable: { bg: "var(--marque-paid-bg)", fg: "var(--marque-paid-text)", label: "Stable" },
  deprecated: { bg: "var(--marque-error-bg)", fg: "var(--marque-error-text)", label: "Déprécié" },
}

// Cycle de validation proposé par le bouton principal.
const NEXT_STATUS: Record<string, string> = {
  draft: "validated",
  testing: "validated",
  validated: "stable",
  stable: "deprecated",
  deprecated: "draft",
}

export default function SkillsClient({ apiUrl, token }: Props) {
  const [skills, setSkills] = useState<Skill[]>([])
  const [err, setErr] = useState("")
  const [loading, setLoading] = useState(true)
  const [agentFilter, setAgentFilter] = useState<string>("all")
  const [busy, setBusy] = useState<string>("")
  const [open, setOpen] = useState<Record<string, any>>({})   // détail (code + run) par skill

  const headers = useMemo(
    () => ({ Authorization: `Bearer ${token}`, "Content-Type": "application/json" }),
    [token],
  )

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${apiUrl}/api/skills`, { headers, cache: "no-store" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setSkills(await res.json())
      setErr("")
    } catch (e: any) {
      setErr(e?.message || "erreur de chargement")
    } finally {
      setLoading(false)
    }
  }, [apiUrl, headers])

  useEffect(() => {
    load()
  }, [load])

  // ── Import / export Markdown ───────────────────────────────────────
  // Un skill s'édite bien plus confortablement dans un fichier : on le
  // versionne, on le relit, on le rejoue sur une autre instance.

  const telecharger = async (chemin: string, nomFichier: string) => {
    setBusy(chemin)
    try {
      const res = await fetch(`${apiUrl}/api/skills${chemin}`, {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || `HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = nomFichier
      a.click()
      URL.revokeObjectURL(url)
      setErr("")
    } catch (e: any) {
      setErr(e?.message || "export impossible")
    } finally {
      setBusy("")
    }
  }

  const importer = async (fichier: File) => {
    setBusy("import")
    try {
      const corps = new FormData()
      corps.append("file", fichier)
      // Pas de Content-Type ici : le navigateur doit poser lui-même la
      // frontière multipart, sinon le serveur ne sait pas découper.
      const res = await fetch(`${apiUrl}/api/skills/import`, {
        method: "POST", headers: { Authorization: `Bearer ${token}` }, body: corps,
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      const n = json.importes?.length ?? 0
      setErr(n
        ? `${n} skill(s) importé(s) en brouillon, désactivé(s) : relisez le code avant de valider.`
        : "Aucun skill importé.")
      await load()
    } catch (e: any) {
      setErr(e?.message || "import impossible")
    } finally {
      setBusy("")
    }
  }

  const act = async (name: string, path: string, body: any) => {
    setBusy(name + path)
    try {
      const res = await fetch(`${apiUrl}/api/skills/${name}${path}`, {
        method: "POST", headers, body: JSON.stringify(body),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      return json
    } finally {
      setBusy("")
    }
  }

  const validate = async (s: Skill) => {
    try {
      await act(s.name, "/validate", { status: NEXT_STATUS[s.status] || "validated" })
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  const toggleEnabled = async (s: Skill) => {
    try {
      await act(s.name, "/enabled", { enabled: !s.enabled })
      await load()
    } catch (e: any) { setErr(e.message) }
  }

  const runTest = async (s: Skill) => {
    try {
      const r = await act(s.name, "/run", { data: {}, allow_draft: true })
      setOpen((o) => ({ ...o, [s.name]: { ...(o[s.name] || {}), run: r } }))
      await load()
    } catch (e: any) {
      setOpen((o) => ({ ...o, [s.name]: { ...(o[s.name] || {}), run: { error: e.message } } }))
    }
  }

  const viewDetail = async (s: Skill) => {
    if (open[s.name]?.detail) {
      setOpen((o) => { const c = { ...o }; delete c[s.name]; return c })
      return
    }
    try {
      const res = await fetch(`${apiUrl}/api/skills/${s.name}`, { headers, cache: "no-store" })
      const detail = await res.json()
      setOpen((o) => ({ ...o, [s.name]: { ...(o[s.name] || {}), detail } }))
    } catch (e: any) { setErr(e.message) }
  }

  const agents = ["all", "agent1", "agent2", "agent3"]
  const filtered = agentFilter === "all" ? skills : skills.filter((s) => s.agent === agentFilter)
  const counts = {
    total: skills.length,
    valides: skills.filter((s) => ["validated", "stable"].includes(s.status)).length,
    actifs: skills.filter((s) => s.enabled).length,
  }

  return (
    <div className="sym-page" style={{ padding: 32, maxWidth: 1180, margin: "0 auto" }}>
      <div className="sym-in sym-in-1" style={{ fontFamily: "monospace", fontSize: 12, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--marque-primary-mid)", fontWeight: 600, marginBottom: 8 }}>
        Gouvernance · Capacités des agents
      </div>
      <h1 className="sym-in sym-in-2" style={{ margin: "0 0 8px", fontSize: 28, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-0.5px" }}>
        Configuration des skills
      </h1>
      <p className="sym-in sym-in-3" style={{ margin: "0 0 24px", fontSize: 15, color: "var(--marque-text-body)", maxWidth: "72ch", lineHeight: 1.55 }}>
        Catalogue des capacités métier des agents. Vous validez, activez/désactivez et testez chaque skill.
        Une skill n'est exécutable par les agents qu'une fois <b>validée/stable</b> ET <b>active</b>.
      </p>

      {/* KPIs + filtre agent */}
      <div className="sym-in sym-in-4" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 18 }}>
        <span style={{ fontSize: 13, color: "var(--marque-text-muted)" }}>
          {counts.total} skills · {counts.valides} validées · {counts.actifs} actives
        </span>
        <div style={{ flex: 1 }} />
        {agents.map((a) => (
          <button key={a} onClick={() => setAgentFilter(a)} className="sym-tap"
            style={{
              fontSize: 13, padding: "6px 12px", borderRadius: "var(--marque-radius-pill)", cursor: "pointer",
              border: `1px solid ${agentFilter === a ? "var(--marque-primary)" : "var(--marque-border)"}`,
              background: agentFilter === a ? "var(--marque-primary-subtle)" : "var(--marque-surface)",
              color: agentFilter === a ? "var(--marque-primary)" : "var(--marque-text-body)",
              fontWeight: agentFilter === a ? 700 : 500,
              boxShadow: agentFilter === a ? "var(--marque-shadow-card)" : "none",
            }}>
            {a === "all" ? "Tous" : a === "agent1" ? "Agent 1" : a === "agent2" ? "Agent 2" : "Agent 3"}
          </button>
        ))}
        <button onClick={() => telecharger("/export", "skills.md")} disabled={busy === "/export"}
          className="sym-tap" title="Télécharger tout le catalogue en Markdown"
          style={{ fontSize: 13, padding: "6px 12px", borderRadius: "var(--marque-radius-pill)", cursor: "pointer", border: "1px solid var(--marque-border)", background: "var(--marque-surface)" }}>
          {busy === "/export" ? "Export…" : "Exporter .md"}
        </button>
        <label className="sym-tap" title="Importer un ou plusieurs skills depuis un fichier Markdown"
          style={{ fontSize: 13, padding: "6px 12px", borderRadius: "var(--marque-radius-pill)", cursor: "pointer", border: "1px solid var(--marque-border)", background: "var(--marque-surface)" }}>
          {busy === "import" ? "Import…" : "Importer .md"}
          <input type="file" accept=".md,text/markdown" style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0]
              // On réinitialise la valeur : sans cela, réimporter le MÊME
              // fichier après correction ne déclencherait aucun événement.
              e.target.value = ""
              if (f) importer(f)
            }} />
        </label>
        <button onClick={load} className="sym-tap" style={{ fontSize: 13, padding: "6px 12px", borderRadius: "var(--marque-radius-pill)", cursor: "pointer", border: "1px solid var(--marque-border)", background: "var(--marque-surface)" }}>↻</button>
      </div>

      {err && <div className="sym-pop" style={{ color: "var(--marque-error-text)", fontSize: 13, marginBottom: 12 }}>⚠ {err}</div>}
      {loading && <div className="sym-fade" style={{ color: "var(--marque-text-muted)", fontSize: 14 }}>Chargement…</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {filtered.map((s, i) => {
          const st = STATUS_STYLE[s.status] || { bg: "var(--marque-canvas)", fg: "var(--marque-text-muted)", label: s.status }
          const detail = open[s.name]
          return (
            <div key={s.name} className={`sym-card sym-in sym-in-${(i % 6) + 1}`} style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden", opacity: s.enabled ? 1 : 0.62 }}>
              <div style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 220 }}>
                  <div style={{ fontFamily: "monospace", fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
                    {s.name}
                    <span style={{ marginLeft: 8, fontFamily: "var(--marque-font)", fontSize: 11, color: "var(--marque-text-muted)", fontWeight: 500 }}>
                      {s.agent} · {s.category}
                    </span>
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--marque-text-muted)", marginTop: 3 }}>{s.description || "Sans description"}</div>
                </div>

                <span style={{ fontSize: 11, color: "var(--marque-text-muted)" }}>{s.usage_count}× util.</span>
                <span className="sym-pop" style={{ background: st.bg, color: st.fg, padding: "5px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 600 }}>{st.label}</span>

                {/* Actions */}
                <button onClick={() => runTest(s)} disabled={busy === s.name + "/run"} className="sym-tap"
                  style={btn("var(--marque-progress-text)")}>Tester</button>
                <button onClick={() => validate(s)} disabled={busy === s.name + "/validate"} className="sym-tap"
                  style={btn("var(--marque-paid-text)")}>→ {STATUS_STYLE[NEXT_STATUS[s.status]]?.label || "Valider"}</button>
                <button onClick={() => toggleEnabled(s)} disabled={busy === s.name + "/enabled"} className="sym-tap"
                  style={btn(s.enabled ? "var(--marque-error-text)" : "var(--marque-paid-text)")}>
                  {s.enabled ? "Désactiver" : "Activer"}
                </button>
                <button onClick={() => telecharger(`/${s.name}/export`, `${s.name}.md`)}
                  disabled={busy === `/${s.name}/export`} className="sym-tap"
                  title="Exporter ce skill en Markdown" style={btn("var(--marque-text-body)")}>.md</button>
                <button onClick={() => viewDetail(s)} className="sym-tap" style={btn("var(--marque-text-body)")}>
                  {detail?.detail ? "▾ Code" : "▸ Code"}
                </button>
              </div>

              {(detail?.detail || detail?.run) && (
                <div className="sym-fade" style={{ borderTop: "1px solid var(--marque-border)", padding: "12px 18px", background: "var(--marque-canvas)" }}>
                  {detail?.run && (
                    <pre style={preStyle}>
                      {"▶ Test : " + JSON.stringify(detail.run.output ?? detail.run.error ?? detail.run, null, 2)}
                    </pre>
                  )}
                  {detail?.detail && (
                    <>
                      <div style={{ fontSize: 12, color: "var(--marque-text-muted)", margin: "6px 0 4px", fontWeight: 600 }}>prompt_template</div>
                      <pre style={preStyle}>{detail.detail.prompt_template || "Aucun prompt défini"}</pre>
                      <div style={{ fontSize: 12, color: "var(--marque-text-muted)", margin: "10px 0 4px", fontWeight: 600 }}>code</div>
                      <pre style={preStyle}>{detail.detail.code}</pre>
                    </>
                  )}
                </div>
              )}
            </div>
          )
        })}
        {!loading && filtered.length === 0 && (
          <div className="sym-fade" style={{ color: "var(--marque-text-muted)", fontSize: 14, padding: 24 }}>Aucune skill pour ce filtre.</div>
        )}
      </div>
    </div>
  )
}

function btn(color: string): React.CSSProperties {
  return {
    fontSize: 12.5, fontWeight: 600, padding: "6px 11px", borderRadius: "var(--marque-radius-pill)", cursor: "pointer",
    border: "1px solid var(--marque-border)", background: "var(--marque-surface)", color, whiteSpace: "nowrap",
  }
}

const preStyle: React.CSSProperties = {
  margin: 0, fontSize: 11.5, lineHeight: 1.5, color: "var(--marque-text-primary)",
  background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-icon)",
  padding: "8px 10px", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 320, overflow: "auto",
}
