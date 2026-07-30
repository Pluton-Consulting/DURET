import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import ValidationQueue from "@/components/validation/ValidationQueue"
import DebriefApprentissage from "@/components/learning/DebriefApprentissage"

async function safeFetch<T>(apiUrl: string, path: string, token: string, fallback: T): Promise<T> {
  try {
    const res = await fetch(`${apiUrl}${path}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
    return res.ok ? ((await res.json()) as T) : fallback
  } catch {
    return fallback
  }
}

const PIPELINE = [
  { n: "1", t: "Analyse du gap", d: "Détecte ce qui manque pour répondre (requête hors champ)." },
  { n: "2", t: "Recherche docs", d: "RAG interne pour trouver un contexte métier de base." },
  { n: "3", t: "Génération skill", d: "Claude génère un skill Python réutilisable (run(data))." },
  { n: "4", t: "Test sandbox", d: "Exécution isolée Daytona (<90ms) sur données fictives → score 0–1." },
  { n: "5", t: "Validation humaine", d: "Si score ≥ 0.7 → soumission ; mise en prod après visa." },
]

const STATUS_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  draft:      { bg: "var(--color-pending-bg)", fg: "var(--color-pending-text)", label: "Brouillon" },
  testing:    { bg: "var(--color-progress-bg)", fg: "var(--color-progress-text)", label: "En test" },
  validated:  { bg: "var(--color-paid-bg)", fg: "var(--color-paid-text)", label: "Validé" },
  stable:     { bg: "var(--color-paid-bg)", fg: "var(--color-paid-text)", label: "Stable" },
}

export default async function AutoEvolutionPage() {
  const session = await auth()
  const role = (session as any)?.user?.role || ""
  if (!["super_admin", "direction"].includes(role)) redirect("/accueil")

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
  const token = (session as any)?.backendToken || ""
  const skills = await safeFetch<any[]>(apiUrl, "/api/dashboard/pending-skills", token, [])

  return (
    <div style={{ padding: 32, maxWidth: 1100, margin: "0 auto" }}>
      <div className="sym-in" style={{ marginBottom: 8, fontFamily: "monospace", fontSize: 12, letterSpacing: "0.14em", textTransform: "uppercase", color: "var(--color-primary-mid)", fontWeight: 600 }}>
        Agent 3 · Superviseur auto-apprenant
      </div>
      <h1 className="sym-in sym-in-1" style={{ margin: "0 0 8px", fontSize: 28, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "-0.5px" }}>
        Auto-Évolution
      </h1>
      <p className="sym-in sym-in-2" style={{ margin: "0 0 28px", fontSize: 15, color: "var(--color-text-body)", maxWidth: "70ch", lineHeight: 1.55 }}>
        Quand une requête sort du champ des agents existants, Duret & Sols ne reste pas bloqué : il <b>génère un nouveau skill</b>,
        le teste dans un sandbox isolé, puis le soumet à validation humaine. Chaque cas non couvert devient une capacité réutilisable.
      </p>

      {/* Pipeline */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 32 }}>
        {PIPELINE.map((s) => (
          <div key={s.n} className={`sym-in sym-in-${s.n} sym-card`} style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card-sm)", padding: 16, boxShadow: "var(--shadow-card)", border: "1px solid var(--color-border)" }}>
            <div style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 28, height: 28, borderRadius: "var(--radius-pill)", background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))", color: "var(--color-text-on-dark)", fontFamily: "monospace", fontSize: 13, fontWeight: 700, marginBottom: 10, boxShadow: "var(--shadow-card)" }}>
              {s.n}
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 4 }}>{s.t}</div>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", lineHeight: 1.45 }}>{s.d}</div>
          </div>
        ))}
      </div>

      {/* Apprentissage déclenché à la main sur la dernière conversation */}
      <div style={{ marginBottom: 36 }}>
        <DebriefApprentissage token={token} />
      </div>

      {/* Skills */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--color-text-primary)" }}>Skills en attente de validation</h2>
        <span style={{ fontFamily: "monospace", fontSize: 13, color: "var(--color-text-muted)" }}>{skills.length} skill(s)</span>
      </div>

      {skills.length === 0 ? (
        <div className="sym-fade" style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card)", padding: "48px 24px", textAlign: "center", boxShadow: "var(--shadow-card)", color: "var(--color-text-muted)", fontSize: 14 }}>
          Aucun skill en attente. L'Agent 3 générera un skill dès qu'une requête sortira du champ couvert.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {skills.map((s: any, i: number) => {
            const st = STATUS_STYLE[s.status] || { bg: "var(--color-canvas)", fg: "var(--color-text-muted)", label: s.status }
            const conf = s.confidence_score != null ? Number(s.confidence_score) : null
            return (
              <div key={s.id} className={`sym-in sym-in-${Math.min(i + 1, 6)} sym-card`} style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card-sm)", padding: "16px 20px", boxShadow: "var(--shadow-card)", border: "1px solid var(--color-border)", display: "flex", alignItems: "center", gap: 16 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: "monospace", fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>{s.name}</div>
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3 }}>
                    {s.description || "—"} · v{s.version ?? 1} · par {s.created_by || "agent3"}
                  </div>
                </div>
                {conf != null && (
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontSize: 11, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Confiance</div>
                    <div style={{ fontFamily: "monospace", fontSize: 18, fontWeight: 700, color: conf >= 0.7 ? "var(--color-paid-text)" : "var(--color-pending-text)" }}>
                      {(conf * 100).toFixed(0)}%
                    </div>
                  </div>
                )}
                <span style={{ background: st.bg, color: st.fg, padding: "4px 12px", borderRadius: "var(--radius-pill)", fontSize: 12, fontWeight: 600, whiteSpace: "nowrap" }}>
                  {st.label}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* File de validation — approuver/refuser les skills (et actions) en attente */}
      <div style={{ marginTop: 36 }}>
        <ValidationQueue token={token} />
      </div>
    </div>
  )
}
