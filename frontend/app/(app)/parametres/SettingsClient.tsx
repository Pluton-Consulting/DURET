"use client"
import { useState, useEffect } from "react"
import { ROLE_LABELS, ROLE_COLORS, nomExpert } from "@/lib/permissions"
import ImportTab from "@/components/settings/ImportTab"
import SyncTab from "@/components/settings/SyncTab"
import ClesApiTab from "@/components/settings/ClesApiTab"
import GoogleTab from "@/components/settings/GoogleTab"

type SubTab = "google" | "utilisateurs" | "plages" | "rbac" | "agents" | "quotas" | "services" | "import" | "synchro" | "cles"
type Role = "super_admin" | "direction" | "commercial" | "bureau_etudes" | "conducteur" | "administratif" | "terrain"
type Agent = "agent1" | "agent2" | "agent3"

interface AgentPermissions { agent1: boolean; agent2: boolean; agent3: boolean }
interface User {
  id: string; email: string; name: string | null; role: Role
  actif: boolean; created_at: string; agent_permissions: AgentPermissions
}
interface Props {
  initialUsers: User[]; backendToken: string; currentRole: string; apiUrl: string
}

const METIER_ROLES: Role[] = ["commercial", "bureau_etudes", "conducteur", "administratif", "terrain"]
const CREATABLE: Record<string, Role[]> = {
  super_admin: ["direction", ...METIER_ROLES],
  direction: METIER_ROLES,
}

function canTogglePerm(mgr: string, _agent: Agent, target: Role): boolean {
  if (mgr === "super_admin") return true
  if (mgr === "direction") return target !== "super_admin"
  return false
}

// Paramètres est désormais ouvert à TOUS les rôles — pour la connexion Google
// personnelle. Les onglets d'administration, eux, gardent leurs rôles : les
// quatre premiers, jadis sans restriction, ne l'étaient que parce que la PAGE
// filtrait à l'entrée (super_admin/direction) — la restriction descend ici.
const ALL_SUB_TABS: { key: SubTab; label: string; roles?: string[] }[] = [
  // Sans `roles` : visible de chacun — l'onglet ne parle que de SA boîte.
  { key: "google", label: "Mon compte Google" },
  { key: "utilisateurs", label: "Utilisateurs", roles: ["super_admin", "direction"] },
  { key: "plages", label: "Plages horaires", roles: ["super_admin", "direction"] },
  { key: "rbac", label: "Permissions RBAC", roles: ["super_admin", "direction"] },
  // 01/09 (Noa) : « États des agents » rejoint l'administration système.
  { key: "agents", label: "États des agents", roles: ["super_admin"] },
  { key: "quotas", label: "Quotas", roles: ["super_admin"] },
  { key: "services", label: "Services connectés", roles: ["super_admin"] },
  { key: "import", label: "Import de données", roles: ["super_admin", "direction"] },
  // Déclencher une synchronisation touche à toutes les sources de
  // l'entreprise : réservé à l'administration système, comme l'endpoint.
  { key: "synchro", label: "Synchronisations", roles: ["super_admin"] },
  // Les clés commandent quels modèles répondent : administration système.
  { key: "cles", label: "Clés API", roles: ["super_admin"] },
]

/* ---------- USERS TAB ---------- */
function UsersTab({ initialUsers, backendToken, currentRole, apiUrl }: Props) {
  const [users, setUsers] = useState<User[]>(initialUsers)
  const [form, setForm] = useState({ email: "", name: "", role: "terrain" as Role })
  const [adding, setAdding] = useState(false)
  const [formError, setFormError] = useState("")
  const [showForm, setShowForm] = useState(false)
  const [permLoading, setPermLoading] = useState<string | null>(null)

  const creatableRoles = CREATABLE[currentRole] ?? []
  const visibleAgents: Agent[] = ["agent1", "agent2", "agent3"].filter(
    (a) => a !== "agent3" || currentRole === "super_admin" || currentRole === "direction"
  ) as Agent[]

  async function addUser(e: React.FormEvent) {
    e.preventDefault(); setAdding(true); setFormError("")
    try {
      const res = await fetch(`${apiUrl}/api/users/`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const err = await res.json()
        setFormError(err.detail ?? "Erreur")
        return
      }
      const newUser = await res.json()
      setUsers((p) => [newUser, ...p])
      setForm({ email: "", name: "", role: "terrain" }); setShowForm(false)
    } catch { setFormError("Erreur réseau") } finally { setAdding(false) }
  }

  async function togglePerm(userId: string, agent: Agent, cur: boolean, targetRole: Role) {
    if (!canTogglePerm(currentRole, agent, targetRole)) return
    const key = `${userId}:${agent}`; setPermLoading(key)
    try {
      const res = await fetch(`${apiUrl}/api/users/${userId}/permissions/${agent}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ has_access: !cur }),
      })
      if (res.ok) setUsers((p) => p.map((u) => u.id === userId
        ? { ...u, agent_permissions: { ...u.agent_permissions, [agent]: !cur } } : u))
    } finally { setPermLoading(null) }
  }

  async function toggleActive(userId: string, actif: boolean, targetRole: Role) {
    if (currentRole !== "super_admin" && currentRole !== "direction" && !METIER_ROLES.includes(targetRole)) return
    const ep = actif ? "deactivate" : "reactivate"
    const res = await fetch(`${apiUrl}/api/users/${userId}/${ep}`, {
      method: "PUT", headers: { Authorization: `Bearer ${backendToken}` },
    })
    if (res.ok) setUsers((p) => p.map((u) => u.id === userId ? { ...u, actif: !actif } : u))
  }

  const inp: React.CSSProperties = {
    padding: "10px 14px", border: "1.5px solid var(--marque-border)",
    borderRadius: 10, fontSize: 14, outline: "none", width: "100%",
    color: "var(--marque-text-primary)", background: "var(--marque-surface)",
  }

  return (
    <div>
      <div className="sym-in" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            Total
          </div>
          <div style={{ fontSize: 28, fontWeight: 800, color: "var(--marque-text-primary)" }}>
            {users.length} <span style={{ fontSize: 14, fontWeight: 500, color: "var(--marque-text-muted)" }}>utilisateurs</span>
          </div>
        </div>
        <button onClick={() => setShowForm(!showForm)} className="sym-tap" style={{
          background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
          borderRadius: "var(--marque-radius-pill)", padding: "10px 22px", fontSize: 14, fontWeight: 600, cursor: "pointer",
          boxShadow: "var(--marque-shadow-card)",
        }}>
          + Ajouter un utilisateur
        </button>
      </div>

      {showForm && (
        <form onSubmit={addUser} className="sym-fade" style={{
          background: "var(--marque-primary-subtle)", borderRadius: "var(--marque-radius-card)", padding: 20,
          marginBottom: 20, border: "1px solid var(--marque-primary-light)",
        }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-primary)", marginBottom: 14 }}>
            Nouvel utilisateur
          </div>
          <div className="sym-grid-1" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 12 }}>
            <input type="email" placeholder="Email *" required value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} style={inp} />
            <input type="text" placeholder="Nom complet" value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} style={inp} />
            <select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as Role }))} style={inp}>
              {creatableRoles.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
          </div>
          {formError && <p style={{ color: "var(--marque-error-text)", fontSize: 13, margin: "0 0 10px" }}>{formError}</p>}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" disabled={adding} className="sym-tap" style={{
              background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, fontWeight: 600,
              cursor: adding ? "not-allowed" : "pointer", opacity: adding ? 0.7 : 1,
            }}>
              {adding ? "Ajout..." : "Ajouter"}
            </button>
            <button type="button" onClick={() => setShowForm(false)} className="sym-tap" style={{
              background: "var(--marque-surface)", color: "var(--marque-text-body)", border: "1px solid var(--marque-border)",
              borderRadius: "var(--marque-radius-pill)", padding: "9px 20px", fontSize: 13, cursor: "pointer",
            }}>
              Annuler
            </button>
          </div>
        </form>
      )}

      <div className="sym-card sym-in sym-in-1" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden" }}>
        {/* Sept colonnes sur un téléphone : sans ce conteneur, les dernières
            sont coupées par l'`overflow: hidden` de la carte et rien ne permet
            d'y accéder. Les deux autres tables de cet écran l'avaient déjà. */}
        <div className="sym-table-large" style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 640 }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--marque-border)", background: "var(--marque-canvas)" }}>
              {["Utilisateur", "Rôle", ...visibleAgents.map((a) => nomExpert(a, true)), "Statut", ""].map((h, i) => (
                <th key={i} style={{ padding: "11px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.map((user) => {
              const color = ROLE_COLORS[user.role] || "#666"
              return (
                <tr key={user.id} style={{ borderBottom: "1px solid var(--marque-border)", opacity: user.actif ? 1 : 0.45 }}>
                  <td style={{ padding: "14px 16px" }}>
                    <div style={{ fontWeight: 600, fontSize: 14, color: "var(--marque-text-primary)" }}>{user.name || "Sans nom"}</div>
                    <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 1 }}>{user.email}</div>
                  </td>
                  <td style={{ padding: "14px 16px" }}>
                    <span style={{ background: color + "18", color, padding: "3px 10px", borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 600 }}>
                      {ROLE_LABELS[user.role]}
                    </span>
                  </td>
                  {visibleAgents.map((agent) => {
                    const has = user.agent_permissions[agent]
                    const canToggle = canTogglePerm(currentRole, agent, user.role)
                    const loading = permLoading === `${user.id}:${agent}`
                    return (
                      <td key={agent} style={{ padding: "14px 16px", textAlign: "center" }}>
                        <button
                          onClick={() => canToggle && togglePerm(user.id, agent, has, user.role)}
                          disabled={!canToggle || loading}
                          title={!canToggle ? "Permission insuffisante" : has ? "Révoquer" : "Accorder"}
                          className="sym-tap"
                          style={{
                            width: 40, height: 22, borderRadius: 11, border: "none",
                            background: has ? "var(--marque-primary-mid)" : "var(--marque-border)",
                            cursor: canToggle ? "pointer" : "default",
                            position: "relative", transition: "background 0.25s ease",
                            opacity: loading ? 0.5 : 1,
                          }}
                        >
                          <span style={{
                            position: "absolute", top: 3,
                            left: has ? 21 : 3, width: 16, height: 16,
                            borderRadius: "50%", background: "var(--marque-surface)",
                            transition: "left 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                          }} />
                        </button>
                      </td>
                    )
                  })}
                  <td style={{ padding: "14px 16px" }}>
                    <span style={{
                      fontSize: 12, fontWeight: 600, padding: "3px 10px", borderRadius: "var(--marque-radius-pill)",
                      color: user.actif ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
                      background: user.actif ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
                    }}>
                      {user.actif ? "● Actif" : "○ Inactif"}
                    </span>
                  </td>
                  <td style={{ padding: "14px 16px", textAlign: "right" }}>
                    {(currentRole === "super_admin" || currentRole === "direction" || METIER_ROLES.includes(user.role)) && (
                      <button onClick={() => toggleActive(user.id, user.actif, user.role)} className="sym-tap" style={{
                        background: "none", border: "1px solid var(--marque-border)",
                        borderRadius: "var(--marque-radius-pill)", padding: "5px 14px", fontSize: 12, cursor: "pointer",
                        color: "var(--marque-text-body)", fontWeight: 500,
                      }}>
                        {user.actif ? "Désactiver" : "Réactiver"}
                      </button>
                    )}
                  </td>
                </tr>
              )
            })}
            {users.length === 0 && (
              <tr><td colSpan={7} style={{ padding: 40, textAlign: "center", color: "var(--marque-text-muted)", fontSize: 14 }}>
                Aucun utilisateur à afficher.
              </td></tr>
            )}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  )
}

/* ---------- PLAGES HORAIRES TAB (éditable) ---------- */
function PlagesTab({ apiUrl, backendToken, users, currentRole }: { apiUrl: string; backendToken: string; users: any[]; currentRole: string }) {
  const HOURS = Array.from({ length: 24 }, (_, i) => i)
  const [glob, setGlob] = useState<{ start_hour: number; end_hour: number } | null>(null)
  const [savingG, setSavingG] = useState(false)
  const [msgG, setMsgG] = useState("")
  const [rows, setRows] = useState<any[]>(() => users.map((u) => ({ ...u })))
  const [savingU, setSavingU] = useState<string | null>(null)
  const [msgU, setMsgU] = useState<Record<string, string>>({})

  useEffect(() => {
    fetch(`${apiUrl}/api/settings/schedule`, { headers: { Authorization: `Bearer ${backendToken}` } })
      .then((r) => (r.ok ? r.json() : null)).then((g) => g && setGlob(g)).catch(() => {})
  }, [apiUrl, backendToken])

  async function saveGlobal() {
    if (!glob) return
    setSavingG(true); setMsgG("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/schedule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify(glob),
      })
      if (!res.ok) { const e = await res.json().catch(() => ({})); setMsgG(e.detail || "Erreur"); return }
      setMsgG("✓ Enregistré"); setTimeout(() => setMsgG(""), 2000)
    } catch { setMsgG("Erreur réseau") } finally { setSavingG(false) }
  }

  function canEditUser(targetRole: string) {
    if (currentRole === "super_admin") return true
    if (currentRole === "direction") return !["super_admin", "direction"].includes(targetRole)
    return false
  }
  function patch(id: string, p: any) { setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...p } : r))) }

  async function saveUser(u: any) {
    setSavingU(u.id); setMsgU((m) => ({ ...m, [u.id]: "" }))
    const num = (v: any) => (v === "" || v == null ? null : Number(v))
    try {
      const res = await fetch(`${apiUrl}/api/users/${u.id}/schedule`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ schedule_start_hour: num(u.schedule_start_hour), schedule_end_hour: num(u.schedule_end_hour), bypass_schedule: !!u.bypass_schedule }),
      })
      if (!res.ok) { const e = await res.json().catch(() => ({})); setMsgU((m) => ({ ...m, [u.id]: e.detail || "Erreur" })); return }
      setMsgU((m) => ({ ...m, [u.id]: "✓" })); setTimeout(() => setMsgU((m) => ({ ...m, [u.id]: "" })), 2000)
    } catch { setMsgU((m) => ({ ...m, [u.id]: "Erreur" })) } finally { setSavingU(null) }
  }

  const inp: React.CSSProperties = { width: 56, padding: "6px 8px", border: "1.5px solid var(--marque-border)", borderRadius: 8, fontSize: 13, outline: "none", background: "var(--marque-surface)", color: "var(--marque-text-primary)" }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Plage globale */}
      <div className="sym-card sym-in" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 20, boxShadow: "var(--marque-shadow-card)" }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Horaires</div>
        <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)", marginBottom: 4 }}>Plage horaire globale</div>
        <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginBottom: 14 }}>
          Appliquée à tout utilisateur sans réglage individuel. super_admin et direction sont exemptés.
        </div>
        {glob ? (
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <label style={{ fontSize: 13, color: "var(--marque-text-body)", display: "flex", alignItems: "center", gap: 8 }}>
              Début <input type="number" min={0} max={23} value={glob.start_hour} onChange={(e) => setGlob({ ...glob, start_hour: parseInt(e.target.value) || 0 })} style={inp} /> h
            </label>
            <label style={{ fontSize: 13, color: "var(--marque-text-body)", display: "flex", alignItems: "center", gap: 8 }}>
              Fin <input type="number" min={1} max={24} value={glob.end_hour} onChange={(e) => setGlob({ ...glob, end_hour: parseInt(e.target.value) || 1 })} style={inp} /> h
            </label>
            <button onClick={saveGlobal} disabled={savingG} className="sym-tap" style={{ background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none", borderRadius: "var(--marque-radius-pill)", padding: "8px 20px", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
              {savingG ? "..." : "Enregistrer"}
            </button>
            {msgG && <span className="sym-pop" style={{ fontSize: 13, fontWeight: 600, color: msgG.startsWith("✓") ? "var(--marque-paid-text)" : "var(--marque-error-text)" }}>{msgG}</span>}
          </div>
        ) : <div style={{ color: "var(--marque-text-muted)", fontSize: 13 }}>Chargement…</div>}

        {glob && (
          <div style={{ marginTop: 16, display: "flex", gap: 3, alignItems: "flex-end", flexWrap: "wrap" }}>
            {HOURS.map((h) => {
              const active = h >= glob.start_hour && h < glob.end_hour
              return (
                <div key={h} style={{ textAlign: "center" }}>
                  <div style={{ width: 20, height: 26, borderRadius: 4, background: active ? "var(--marque-primary-mid)" : "var(--marque-border)", opacity: active ? 0.9 : 0.4, transition: "background 0.25s ease, opacity 0.25s ease" }} />
                  <div style={{ fontSize: 9, color: "var(--marque-text-muted)", marginTop: 2 }}>{h}</div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Réglages par utilisateur */}
      <div className="sym-card sym-in sym-in-1" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--marque-border)", fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>
          Réglages individuels <span style={{ fontWeight: 400, fontSize: 12, color: "var(--marque-text-muted)" }}>(vide = plage globale)</span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "var(--marque-canvas)" }}>
                {["Utilisateur", "Rôle", "Début", "Fin", "24/7", ""].map((h, i) => (
                  <th key={i} style={{ padding: "10px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => {
                const editable = canEditUser(u.role)
                return (
                  <tr key={u.id} style={{ borderTop: "1px solid var(--marque-border)", opacity: editable ? 1 : 0.55 }}>
                    <td style={{ padding: "12px 16px" }}>
                      <div style={{ fontWeight: 600, fontSize: 13, color: "var(--marque-text-primary)" }}>{u.name || "Sans nom"}</div>
                      <div style={{ fontSize: 11, color: "var(--marque-text-muted)" }}>{u.email}</div>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <span style={{ background: (ROLE_COLORS[u.role] || "#666") + "18", color: ROLE_COLORS[u.role] || "#666", padding: "3px 10px", borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 600 }}>{ROLE_LABELS[u.role]}</span>
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <input type="number" min={0} max={23} value={u.schedule_start_hour ?? ""} disabled={!editable || u.bypass_schedule} onChange={(e) => patch(u.id, { schedule_start_hour: e.target.value })} style={inp} />
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <input type="number" min={1} max={24} value={u.schedule_end_hour ?? ""} disabled={!editable || u.bypass_schedule} onChange={(e) => patch(u.id, { schedule_end_hour: e.target.value })} style={inp} />
                    </td>
                    <td style={{ padding: "12px 16px" }}>
                      <button onClick={() => editable && patch(u.id, { bypass_schedule: !u.bypass_schedule })} disabled={!editable} className="sym-tap" style={{ width: 40, height: 22, borderRadius: 11, border: "none", background: u.bypass_schedule ? "var(--marque-primary-mid)" : "var(--marque-border)", cursor: editable ? "pointer" : "default", position: "relative", transition: "background 0.25s ease" }}>
                        <span style={{ position: "absolute", top: 3, left: u.bypass_schedule ? 21 : 3, width: 16, height: 16, borderRadius: "50%", background: "var(--marque-surface)", transition: "left 0.2s", boxShadow: "0 1px 3px rgba(0,0,0,0.2)" }} />
                      </button>
                    </td>
                    <td style={{ padding: "12px 16px", textAlign: "right", whiteSpace: "nowrap" }}>
                      {editable && (
                        <button onClick={() => saveUser(u)} disabled={savingU === u.id} className="sym-tap" style={{ background: "none", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)", padding: "5px 14px", fontSize: 12, cursor: "pointer", color: "var(--marque-text-body)", fontWeight: 500 }}>
                          {savingU === u.id ? "..." : "Enregistrer"}
                        </button>
                      )}
                      {msgU[u.id] && <span className="sym-pop" style={{ marginLeft: 8, fontSize: 12, fontWeight: 600, color: msgU[u.id] === "✓" ? "var(--marque-paid-text)" : "var(--marque-error-text)" }}>{msgU[u.id]}</span>}
                    </td>
                  </tr>
                )
              })}
              {rows.length === 0 && <tr><td colSpan={6} style={{ padding: 30, textAlign: "center", color: "var(--marque-text-muted)", fontSize: 13 }}>Aucun utilisateur</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

/* ---------- RBAC TAB (matrice éditable) ---------- */
function RBACTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [data, setData] = useState<any>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState("")

  useEffect(() => {
    fetch(`${apiUrl}/api/settings/permissions`, { headers: { Authorization: `Bearer ${backendToken}` } })
      .then((r) => (r.ok ? r.json() : null)).then((d) => (d ? setData(d) : setErr("Chargement impossible"))).catch(() => setErr("Erreur de chargement"))
  }, [apiUrl, backendToken])

  async function toggle(role: string, feature: string, current: boolean) {
    if (!data?.can_edit || role === data.protected_role) return
    const key = `${role}:${feature}`; setBusy(key)
    const set = (val: boolean) => setData((d: any) => ({ ...d, matrix: { ...d.matrix, [role]: { ...d.matrix[role], [feature]: val } } }))
    set(!current)  // optimiste
    try {
      const res = await fetch(`${apiUrl}/api/settings/permissions`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ role, feature, allowed: !current }),
      })
      if (!res.ok) set(current)  // rollback
    } catch { set(current) } finally { setBusy(null) }
  }

  if (err) return <div className="sym-fade" style={{ color: "var(--marque-error-text)", fontSize: 14, padding: 20 }}>{err}</div>
  if (!data) return <div className="sym-skeleton" style={{ height: 200, borderRadius: "var(--marque-radius-card)" }} />
  const canEdit = !!data.can_edit

  return (
    <div>
      <div className="sym-card sym-in" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden" }}>
        <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--marque-border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Matrice de permissions par rôle</div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2 }}>
              {canEdit ? "Cliquez sur une case pour activer/désactiver. Le super admin n'est pas modifiable." : "Lecture seule : édition réservée au super admin."}
            </div>
          </div>
          <span className="sym-pop" style={{ fontSize: 11, fontWeight: 600, padding: "4px 12px", borderRadius: "var(--marque-radius-pill)", color: canEdit ? "var(--marque-paid-text)" : "var(--marque-pending-text)", background: canEdit ? "var(--marque-paid-bg)" : "var(--marque-pending-bg)" }}>
            {canEdit ? "Éditable" : "Lecture seule"}
          </span>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", minWidth: 900 }}>
            <thead>
              <tr style={{ background: "var(--marque-canvas)" }}>
                <th style={{ padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 700, color: "var(--marque-text-muted)", textTransform: "uppercase", position: "sticky", left: 0, background: "var(--marque-canvas)" }}>Rôle</th>
                {data.features.map((f: string) => (
                  <th key={f} style={{ padding: "10px 10px", textAlign: "center", fontSize: 10.5, fontWeight: 700, color: "var(--marque-text-muted)", whiteSpace: "nowrap" }}>{data.labels[f] || f}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.roles.map((role: string) => {
                const color = ROLE_COLORS[role] || "#666"
                const locked = role === data.protected_role
                return (
                  <tr key={role} style={{ borderTop: "1px solid var(--marque-border)" }}>
                    <td style={{ padding: "10px 16px", position: "sticky", left: 0, background: "var(--marque-surface)" }}>
                      <span style={{ background: color + "18", color, padding: "4px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 700 }}>{ROLE_LABELS[role]}</span>
                    </td>
                    {data.features.map((f: string) => {
                      const has = !!data.matrix[role]?.[f]
                      const key = `${role}:${f}`
                      const editable = canEdit && !locked
                      return (
                        <td key={f} style={{ padding: "8px 10px", textAlign: "center" }}>
                          <button
                            onClick={() => editable && toggle(role, f, has)}
                            disabled={!editable || busy === key}
                            title={locked ? "Super admin : non modifiable" : editable ? (has ? "Désactiver" : "Activer") : "Lecture seule"}
                            className="sym-tap"
                            style={{
                              width: 26, height: 26, borderRadius: 7, border: "none", fontSize: 14,
                              cursor: editable ? "pointer" : "default",
                              background: has ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
                              color: has ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
                              opacity: busy === key ? 0.5 : 1,
                              transition: "background 0.2s ease, color 0.2s ease",
                            }}
                          >
                            {has ? "✓" : "·"}
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

/* ---------- AGENTS TAB (métriques réelles) ---------- */
function AgentsTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const AGENTS = [
    { key: "agent1", name: nomExpert("agent1"), desc: "Chantiers, clients, dossiers, mails et documents.", tier: "Palier LIGHT / STANDARD" },
    { key: "agent2", name: nomExpert("agent2"), desc: "Analyse de DCE, métrés, pré-chiffrage.", tier: "Palier COMPLEX (vision)" },
    { key: "agent3", name: nomExpert("agent3"), desc: "Consignes retenues, connaissances acquises, compétences.", tier: "Palier COMPLEX" },
  ]
  const [stats, setStats] = useState<Record<string, any>>({})
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetch(`${apiUrl}/api/dashboard/agents-activity`, { headers: { Authorization: `Bearer ${backendToken}` } })
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: any[]) => {
        const m: Record<string, any> = {}
        for (const row of rows || []) m[row.agent_id] = row
        setStats(m)
      })
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [apiUrl, backendToken])

  const metric = (label: string, value: any) => (
    <div>
      <div style={{ fontSize: 11, color: "var(--marque-text-muted)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, color: "var(--marque-text-primary)" }}>{value}</div>
    </div>
  )

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="sym-in" style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>
        Métriques réelles du jour, source <code style={{ fontFamily: "monospace", background: "var(--marque-canvas)", padding: "1px 5px", borderRadius: 4 }}>audit_log</code>.
      </div>
      {AGENTS.map((agent, i) => {
        const s = stats[agent.key] || {}
        const dur = s.avg_duration_ms != null ? `${s.avg_duration_ms} ms` : "n/a"
        return (
          <div key={agent.key} className={`sym-card sym-in sym-in-${i + 1}`} style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)", border: "1.5px solid var(--marque-border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
              <div style={{ width: 40, height: 40, borderRadius: "var(--marque-radius-icon)", background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))", boxShadow: "var(--marque-shadow-card)" }} />
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>{agent.name}</div>
                <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 1 }}>{agent.tier} · cascade multi-fournisseurs</div>
              </div>
            </div>
            <p style={{ margin: "0 0 14px 52px", fontSize: 13, color: "var(--marque-text-body)", lineHeight: 1.5 }}>{agent.desc}</p>
            <div style={{ display: "flex", gap: 28, marginLeft: 52 }}>
              {metric("Req. aujourd'hui", loaded ? (s.request_count ?? 0) : "…")}
              {metric("Succès", loaded ? (s.success_count ?? 0) : "…")}
              {metric("Échecs", loaded ? (s.failure_count ?? 0) : "…")}
              {metric("Durée moy.", loaded ? dur : "…")}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ---------- QUOTAS TAB (super_admin uniquement) ---------- */
function QuotasTab({ backendToken, apiUrl }: { backendToken: string; apiUrl: string }) {
  const [quotas, setQuotas] = useState<Record<string, number | null>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    fetch(`${apiUrl}/api/settings/quotas`, {
      headers: { Authorization: `Bearer ${backendToken}` },
    })
      .then((r) => r.json())
      .then(setQuotas)
      .catch(() => setError("Erreur de chargement"))
      .finally(() => setLoading(false))
  }, [apiUrl, backendToken])

  async function save() {
    setSaving(true); setError(""); setSuccess(false)
    try {
      const res = await fetch(`${apiUrl}/api/settings/quotas`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ quotas }),
      })
      if (!res.ok) { setError("Erreur de sauvegarde"); return }
      const updated = await res.json()
      setQuotas(updated)
      setSuccess(true)
      setTimeout(() => setSuccess(false), 2500)
    } catch { setError("Erreur réseau") } finally { setSaving(false) }
  }

  const ROLE_ORDER = ["super_admin", "direction", "commercial", "bureau_etudes", "conducteur", "administratif", "terrain"]

  return (
    <div>
      <div className="sym-card sym-in" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden" }}>
        <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--marque-border)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>Facturation</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Quotas mensuels par rôle</div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2 }}>
              Nombre max de requêtes / mois. Illimité = aucune restriction.
            </div>
          </div>
          <button onClick={save} disabled={saving || loading} className="sym-tap" style={{
            background: success ? "var(--marque-paid-text)" : "var(--marque-primary)",
            color: "var(--marque-text-on-dark)", border: "none",
            borderRadius: "var(--marque-radius-pill)", padding: "9px 22px", fontSize: 13, fontWeight: 600,
            cursor: saving ? "not-allowed" : "pointer", opacity: saving ? 0.7 : 1,
            transition: "background 0.3s",
          }}>
            {saving ? "Sauvegarde..." : success ? "✓ Sauvegardé" : "Sauvegarder"}
          </button>
        </div>

        {loading ? (
          <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 10 }}>
            {[0, 1, 2, 3].map((k) => <div key={k} className="sym-skeleton" style={{ height: 52, borderRadius: 12 }} />)}
          </div>
        ) : (
          <div style={{ padding: 24 }}>
            {error && <p style={{ color: "var(--marque-error-text)", fontSize: 13, marginBottom: 16 }}>{error}</p>}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {ROLE_ORDER.filter((r) => r in quotas).map((role, i) => {
                const limit = quotas[role]
                const isUnlimited = limit === null
                const color = ROLE_COLORS[role] || "#666"
                return (
                  <div key={role} className={`sym-in sym-in-${Math.min(i + 1, 6)}`} style={{
                    display: "flex", alignItems: "center", gap: 16,
                    padding: "14px 18px", borderRadius: 12,
                    border: "1px solid var(--marque-border)", background: "var(--marque-canvas)",
                    transition: "border-color 0.2s ease, box-shadow 0.2s ease",
                  }}>
                    <span style={{
                      background: color + "18", color, padding: "4px 12px",
                      borderRadius: "var(--marque-radius-pill)", fontSize: 12, fontWeight: 700,
                      minWidth: 130, textAlign: "center", display: "inline-block",
                    }}>
                      {ROLE_LABELS[role]}
                    </span>
                    <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "var(--marque-text-body)", cursor: "pointer", userSelect: "none" }}>
                      <input
                        type="checkbox"
                        checked={isUnlimited}
                        onChange={(e) => setQuotas((q) => ({ ...q, [role]: e.target.checked ? null : 100 }))}
                        style={{ width: 16, height: 16, accentColor: "var(--marque-primary)" }}
                      />
                      Illimité
                    </label>
                    {!isUnlimited ? (
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <input
                          type="number" min={1} max={10000}
                          value={limit ?? ""}
                          onChange={(e) => setQuotas((q) => ({ ...q, [role]: parseInt(e.target.value) || 1 }))}
                          style={{
                            padding: "8px 12px", border: "1.5px solid var(--marque-border)",
                            borderRadius: 10, fontSize: 14, width: 110,
                            color: "var(--marque-text-primary)", background: "var(--marque-surface)", outline: "none",
                          }}
                        />
                        <span style={{ fontSize: 13, color: "var(--marque-text-muted)" }}>req / mois</span>
                      </div>
                    ) : (
                      <span style={{ fontSize: 13, color: "var(--marque-text-muted)", fontStyle: "italic" }}>
                        ∞ (aucune restriction)
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/* ---------- SERVICES TAB (état réel via /system) ---------- */
function ServicesTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [sys, setSys] = useState<any>(null)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    fetch(`${apiUrl}/api/dashboard/system`, { headers: { Authorization: `Bearer ${backendToken}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then(setSys)
      .catch(() => {})
      .finally(() => setLoaded(true))
  }, [apiUrl, backendToken])

  const p = sys?.providers || {}
  const db = sys?.db || {}
  const services = [
    { name: "PostgreSQL + pgvector", desc: "Base de données + checkpointer LangGraph", up: sys?.checkpointer === "AsyncPostgresSaver", detail: sys ? `${sys.checkpointer} · ${db.threads ?? 0} threads · ${db.users_actifs ?? 0} users` : "non disponible" },
    { name: "Langfuse", desc: "Observabilité LLM (traces)", up: !!sys?.observability?.langfuse_enabled, detail: sys?.observability?.host || "non configuré" },
    { name: "Groq", desc: "LLM gratuit (paliers LIGHT/STANDARD)", up: !!p.groq, detail: p.groq ? "clé configurée" : "clé absente" },
    { name: "OpenRouter", desc: "LongCat / DeepSeek / modèles free", up: !!p.openrouter, detail: p.openrouter ? "clé configurée" : "clé absente" },
    { name: "DeepSeek (API directe)", desc: "deepseek-v4-pro (fallback qualité)", up: !!p.deepseek, detail: p.deepseek ? "clé configurée" : "clé absente" },
    { name: "LongCat (API directe)", desc: "modèle principal", up: !!p.longcat, detail: p.longcat ? "clé configurée" : "clé absente" },
    { name: "Anthropic", desc: "vision agent 2 (palier COMPLEX)", up: !!p.anthropic, detail: p.anthropic ? "clé configurée" : "placeholder / absente" },
    { name: "Ollama (local)", desc: "LLM local (dernier recours)", up: !!p.ollama, detail: "local" },
  ]

  return (
    <div>
      {loaded && !sys && (
        <div style={{ color: "var(--marque-error-text)", fontSize: 13, marginBottom: 12 }}>
          État système indisponible (réservé au super admin).
        </div>
      )}
      <div className="sym-grid-1" style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 14 }}>
        {services.map((s, i) => (
          <div key={i} className={`sym-card sym-in sym-in-${Math.min(i + 1, 6)}`} style={{
            background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card-sm)", padding: 18, boxShadow: "var(--marque-shadow-card)",
            borderLeft: `3px solid ${s.up ? "var(--marque-primary-mid)" : "var(--marque-pending-text)"}`,
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>{s.name}</div>
              <span className={loaded ? "sym-pop" : ""} style={{
                fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: "var(--marque-radius-pill)",
                color: s.up ? "var(--marque-paid-text)" : "var(--marque-pending-text)",
                background: s.up ? "var(--marque-paid-bg)" : "var(--marque-pending-bg)",
              }}>
                {!loaded ? "…" : s.up ? "✓ Actif" : "! Inactif"}
              </span>
            </div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginBottom: 6 }}>{s.desc}</div>
            <div style={{ fontSize: 11, color: "var(--marque-text-body)", fontFamily: "monospace", background: "var(--marque-canvas)", padding: "4px 8px", borderRadius: 6, display: "inline-block" }}>
              {s.detail}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------- MAIN COMPONENT ---------- */
export default function SettingsClient({ initialUsers, backendToken, currentRole, apiUrl }: Props) {
  const subTabs = ALL_SUB_TABS.filter((t) => !t.roles || t.roles.includes(currentRole))
  // L'onglet d'ouverture : l'administration pour qui la voit (l'habitude), la
  // boîte Google pour tous les autres — c'est leur seul onglet.
  const [activeTab, setActiveTab] = useState<SubTab>(
    subTabs.some((t) => t.key === "utilisateurs") ? "utilisateurs" : (subTabs[0]?.key ?? "google"))

  return (
    <div className="sym-page" style={{ padding: 32, maxWidth: 1300, margin: "0 auto" }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }} className="sym-in">
        Duret & Sols · Administration
      </div>
      <h1 className="sym-in sym-in-1" style={{ margin: "0 0 6px", fontSize: 26, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-0.5px" }}>
        Paramètres
      </h1>
      <p className="sym-in sym-in-2" style={{ margin: "0 0 28px", fontSize: 14, color: "var(--marque-text-muted)" }}>
        Configuration du système Duret & Sols, accès {ROLE_LABELS[currentRole] || currentRole}
      </p>

      <div className="sym-in sym-in-3 sym-onglets" style={{ display: "flex", gap: 2, marginBottom: 28, background: "var(--marque-surface)", padding: 6, borderRadius: "var(--marque-radius-card-sm)", width: "fit-content", maxWidth: "100%", boxShadow: "var(--marque-shadow-card)" }}>
        {subTabs.map((t) => {
          const active = activeTab === t.key
          return (
            <button key={t.key} onClick={() => setActiveTab(t.key)} className="sym-tap" style={{
              padding: "8px 18px", border: "none", cursor: "pointer",
              borderRadius: 10, fontSize: 14, fontWeight: active ? 700 : 500,
              color: active ? "var(--marque-primary)" : "var(--marque-text-muted)",
              background: active ? "var(--marque-primary-subtle)" : "transparent",
              boxShadow: active ? "inset 0 0 0 1px var(--marque-primary-light)" : "none",
              transition: "all 0.15s", display: "flex", alignItems: "center", gap: 6,
            }}>
              {t.label}
            </button>
          )
        })}
      </div>

      {activeTab === "google" && (
        <GoogleTab apiUrl={apiUrl} backendToken={backendToken} currentRole={currentRole} />
      )}
      {activeTab === "utilisateurs" && (
        <UsersTab initialUsers={initialUsers} backendToken={backendToken} currentRole={currentRole} apiUrl={apiUrl} />
      )}
      {activeTab === "plages" && <PlagesTab apiUrl={apiUrl} backendToken={backendToken} users={initialUsers} currentRole={currentRole} />}
      {activeTab === "rbac" && <RBACTab apiUrl={apiUrl} backendToken={backendToken} />}
      {activeTab === "agents" && <AgentsTab apiUrl={apiUrl} backendToken={backendToken} />}
      {activeTab === "quotas" && currentRole === "super_admin" && (
        <QuotasTab backendToken={backendToken} apiUrl={apiUrl} />
      )}
      {activeTab === "services" && <ServicesTab apiUrl={apiUrl} backendToken={backendToken} />}
      {activeTab === "import" && <ImportTab apiUrl={apiUrl} backendToken={backendToken} />}
      {activeTab === "synchro" && currentRole === "super_admin" && (
        <SyncTab apiUrl={apiUrl} backendToken={backendToken} />
      )}
      {activeTab === "cles" && currentRole === "super_admin" && (
        <ClesApiTab apiUrl={apiUrl} backendToken={backendToken} />
      )}
    </div>
  )
}
