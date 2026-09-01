"use client"
import { useCallback, useEffect, useState } from "react"
import { StatTile } from "@/components/blocks/layout/StatTile"
import { BarChart } from "@/components/blocks/charts/BarChart"

/**
 * LA PAGE MONTRE CE QUE LE SERVEUR SAIT, ET RIEN D'AUTRE.
 *
 * Une seule lecture (`/api/dashboard/pilotage`), quatre vues : les usages dans
 * le temps, les personnes, les erreurs récentes, le journal des actions. Pas
 * d'exemple, pas de « n/d » : une valeur absente se dit « 0 » ou « aucun »,
 * parce que c'est ce que la base contient. Le détail des coûts et le journal
 * n'arrivent que si le rôle y a droit — c'est le serveur qui tranche, la page
 * se contente de ne pas dessiner une colonne qu'on ne lui a pas donnée.
 */

interface Props { apiUrl: string; token: string }

type Kpi = {
  requetes_30j?: number; erreurs_24h?: number; cout_mois_eur?: number
  personnes_actives_30j?: number; accords_en_attente?: number; competences_actives?: number
}
type Jour = { date: string; requetes: number; jetons: number; cout_eur: number }
type Personne = {
  id: string; name?: string | null; email: string; role: string
  requetes: number; jetons: number; cout_eur?: number; derniere_activite?: string | null
}
type Erreur = { created_at: string; action: string; agent_id?: string | null; error_message?: string | null; qui?: string | null }
type Ligne = {
  created_at: string; action: string; agent_id?: string | null; model_used?: string | null
  duration_ms?: number | null; success: boolean; tokens_in?: number; tokens_out?: number; qui?: string | null
}
type Donnees = {
  kpi: Kpi; par_jour: Jour[]; par_personne: Personne[]
  erreurs_24h: Erreur[]; journal: Ligne[]; droits: { couts: boolean; journal: boolean }
}

type Onglet = "usages" | "personnes" | "erreurs" | "journal"

const ROLES: Record<string, string> = {
  super_admin: "Administrateur", direction: "Direction", responsable: "Responsable",
  conducteur: "Conducteur de travaux", bureau_etudes: "Bureau d'études",
  administratif: "Administratif", commercial: "Commercial", terrain: "Terrain",
}

const euros = (v?: number | null) =>
  typeof v === "number" ? v.toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 2 }) : "—"
const entier = (v?: number | null) => typeof v === "number" ? v.toLocaleString("fr-FR") : "0"
const quand = (iso?: string | null) => {
  if (!iso) return "—"
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
}
const jour = (iso: string) => {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })
}
// Les actions du journal sont des identifiants techniques ; à l'écran on les
// dit en français, et l'identifiant reste lisible pour ce qui n'est pas traduit.
const ACTIONS: Record<string, string> = {
  chat_request: "Question posée", chat_interrompu: "Question interrompue",
  skill_executed: "Action exécutée", login: "Connexion", logout: "Déconnexion",
  tache_differee_lancee: "Tâche en arrière-plan", browser_task_running: "Navigation lancée",
  browser_task_completed: "Navigation terminée", browser_task_failed: "Navigation échouée",
  skill_created: "Compétence créée", skill_validated: "Compétence validée",
  user_created: "Utilisateur créé", user_deactivated: "Utilisateur désactivé",
  quota_exceeded: "Quota dépassé",
}
const libelleAction = (a: string) => ACTIONS[a] || a.replace(/_/g, " ")

export default function PilotageClient({ apiUrl, token }: Props) {
  const [donnees, setDonnees] = useState<Donnees | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [onglet, setOnglet] = useState<Onglet>("usages")

  // MÊME DÉFAUT QUE LE TABLEAU DE BORD (01/09) : un seul chargement au montage,
  // donc un écran de pilotage figé sur l'heure d'ouverture de l'onglet. On
  // relit quand l'onglet redevient visible, et toutes les 60 s tant qu'il l'est
  // — jamais en arrière-plan : un écran que personne ne regarde n'a pas besoin
  // d'être à jour, et chaque lecture coûte plusieurs requêtes lourdes.
  const charger = useCallback(async () => {
    try {
      const r = await fetch(`${apiUrl}/api/dashboard/pilotage`,
        { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
      if (!r.ok) {
        throw new Error(r.status === 403
          ? "Vous n'avez pas accès au pilotage."
          : `Chargement impossible (${r.status}).`)
      }
      setDonnees(await r.json()); setErreur(null)
    } catch (e: any) {
      setErreur(e?.message || "Chargement impossible.")
    }
  }, [apiUrl, token])

  useEffect(() => {
    let vivant = true
    const relire = () => { if (vivant && document.visibilityState === "visible") charger() }
    relire()
    document.addEventListener("visibilitychange", relire)
    const minuterie = window.setInterval(relire, 60000)
    return () => {
      vivant = false
      document.removeEventListener("visibilitychange", relire)
      window.clearInterval(minuterie)
    }
  }, [charger])

  const k = donnees?.kpi || {}
  const onglets: { key: Onglet; label: string; n?: number }[] = [
    { key: "usages", label: "Usages" },
    { key: "personnes", label: "Personnes", n: donnees?.par_personne.length },
    { key: "erreurs", label: "Erreurs 24 h", n: donnees?.erreurs_24h.length },
    ...(donnees?.droits.journal ? [{ key: "journal" as Onglet, label: "Journal", n: donnees.journal.length }] : []),
  ]

  return (
    <div className="sym-page" style={{ padding: 32, maxWidth: 1300, margin: "0 auto" }}>
      <div className="sym-in" style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-0.5px" }}>
          Pilotage
        </h1>
        <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--marque-text-muted)" }}>
          Qui se sert de l'assistant, pour quoi faire, et ce que ça coûte — sur les trente derniers jours.
        </p>
      </div>

      {erreur && (
        <div className="sym-in sym-card" style={{ padding: "14px 18px", background: "var(--marque-error-bg)", color: "var(--marque-error-text)", borderRadius: "var(--marque-radius-card-sm)", marginBottom: 20, fontSize: 14 }}>
          {erreur}
        </div>
      )}

      {/* Indicateurs */}
      <div className="sym-grid-auto" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 14, marginBottom: 24 }}>
        <div className="sym-in sym-in-1"><StatTile label="Questions (30 j)" value={entier(k.requetes_30j)} hint="toutes personnes confondues" signature /></div>
        <div className="sym-in sym-in-2"><StatTile label="Personnes actives (30 j)" value={entier(k.personnes_actives_30j)} hint="ont posé au moins une question" /></div>
        {donnees?.droits.couts && (
          <div className="sym-in sym-in-3"><StatTile label="Coût IA du mois" value={euros(k.cout_mois_eur)} hint="appels aux modèles, mois en cours" /></div>
        )}
        <div className="sym-in sym-in-4"><StatTile label="Erreurs (24 h)" value={entier(k.erreurs_24h)} hint={k.erreurs_24h ? "voir l'onglet Erreurs" : "aucune"} /></div>
        <div className="sym-in sym-in-5"><StatTile label="Accords en attente" value={entier(k.accords_en_attente)} hint="actions qui attendent une décision" /></div>
        <div className="sym-in sym-in-6"><StatTile label="Compétences actives" value={entier(k.competences_actives)} hint="validées et activées" /></div>
      </div>

      {/* Onglets */}
      <div className="sym-in" style={{ display: "flex", gap: 6, marginBottom: 16, borderBottom: "1px solid var(--marque-border)" }}>
        {onglets.map((o) => (
          <button key={o.key} type="button" onClick={() => setOnglet(o.key)} className="sym-tap" style={{
            padding: "10px 16px", fontSize: 13.5, fontWeight: 600, border: "none", cursor: "pointer", background: "transparent",
            color: onglet === o.key ? "var(--marque-primary)" : "var(--marque-text-muted)",
            borderBottom: onglet === o.key ? "2px solid var(--marque-primary)" : "2px solid transparent", marginBottom: -1,
          }}>
            {o.label}{typeof o.n === "number" ? <span style={{ marginLeft: 6, fontSize: 11.5, color: "var(--marque-text-muted)" }}>{o.n}</span> : null}
          </button>
        ))}
      </div>

      {!donnees && !erreur && (
        <div className="sym-in" style={{ padding: 40, textAlign: "center", color: "var(--marque-text-muted)", fontSize: 14 }}>Chargement…</div>
      )}

      {donnees && onglet === "usages" && (
        <div className="sym-in sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
          <h3 style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Questions par jour</h3>
          <p style={{ margin: "0 0 18px", fontSize: 13, color: "var(--marque-text-muted)" }}>
            {donnees.par_jour.length ? `${donnees.par_jour.length} jour(s) d'activité sur les trente derniers.` : "Aucune activité enregistrée sur les trente derniers jours."}
          </p>
          {donnees.par_jour.length > 0 && (
            <BarChart height={170} data={donnees.par_jour.map((j) => ({ label: jour(j.date), value: Number(j.requetes) || 0 }))} />
          )}
          {donnees.droits.couts && donnees.par_jour.length > 0 && (
            <div style={{ marginTop: 22, overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead><tr>
                  {["Jour", "Questions", "Jetons", "Coût"].map((c, i) => (
                    <th key={c} style={{ textAlign: i ? "right" : "left", padding: "8px 12px", background: "var(--marque-primary-subtle)", color: "var(--marque-text-muted)", fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 700 }}>{c}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {[...donnees.par_jour].reverse().map((j) => (
                    <tr key={j.date}>
                      <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", fontWeight: 600, color: "var(--marque-text-primary)" }}>{jour(j.date)}</td>
                      <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{entier(Number(j.requetes))}</td>
                      <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{entier(Number(j.jetons))}</td>
                      <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{euros(Number(j.cout_eur))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {donnees && onglet === "personnes" && (
        <div className="sym-in sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
          <h3 style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Consommation par personne</h3>
          <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--marque-text-muted)" }}>
            Trente derniers jours. Une personne sans activité apparaît à zéro : c'est aussi une information.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead><tr>
                {["Personne", "Rôle", "Questions", "Jetons", ...(donnees.droits.couts ? ["Coût"] : []), "Dernière activité"].map((c, i) => (
                  <th key={c} style={{ textAlign: i >= 2 && i <= 4 ? "right" : "left", padding: "8px 12px", background: "var(--marque-primary-subtle)", color: "var(--marque-text-muted)", fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 700 }}>{c}</th>
                ))}
              </tr></thead>
              <tbody>
                {donnees.par_personne.map((p) => (
                  <tr key={p.id}>
                    <td style={{ padding: "9px 12px", borderTop: "1px solid var(--marque-border)", fontWeight: 600, color: "var(--marque-text-primary)" }}>
                      {p.name || p.email}
                      {p.name && <div style={{ fontSize: 11.5, fontWeight: 400, color: "var(--marque-text-muted)" }}>{p.email}</div>}
                    </td>
                    <td style={{ padding: "9px 12px", borderTop: "1px solid var(--marque-border)", color: "var(--marque-text-body)" }}>{ROLES[p.role] || p.role}</td>
                    <td style={{ padding: "9px 12px", borderTop: "1px solid var(--marque-border)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{entier(Number(p.requetes))}</td>
                    <td style={{ padding: "9px 12px", borderTop: "1px solid var(--marque-border)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{entier(Number(p.jetons))}</td>
                    {donnees.droits.couts && (
                      <td style={{ padding: "9px 12px", borderTop: "1px solid var(--marque-border)", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{euros(Number(p.cout_eur))}</td>
                    )}
                    <td style={{ padding: "9px 12px", borderTop: "1px solid var(--marque-border)", color: "var(--marque-text-muted)" }}>{p.derniere_activite ? jour(p.derniere_activite) : "jamais"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {donnees && onglet === "erreurs" && (
        <div className="sym-in sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
          <h3 style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Erreurs des dernières 24 heures</h3>
          {!donnees.droits.journal ? (
            <p style={{ margin: 0, fontSize: 13, color: "var(--marque-text-muted)" }}>Le détail des erreurs demande le droit de lire le journal.</p>
          ) : donnees.erreurs_24h.length === 0 ? (
            <p style={{ margin: 0, fontSize: 13, color: "var(--marque-text-muted)" }}>Aucune erreur enregistrée.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
              {donnees.erreurs_24h.map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 14, alignItems: "baseline", padding: "10px 14px", background: "var(--marque-error-bg)", borderRadius: "var(--marque-radius-card-sm)", fontSize: 13 }}>
                  <span style={{ color: "var(--marque-text-muted)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{quand(e.created_at)}</span>
                  <span style={{ fontWeight: 600, color: "var(--marque-error-text)" }}>{libelleAction(e.action)}</span>
                  {e.agent_id && <span style={{ color: "var(--marque-text-muted)" }}>{e.agent_id}</span>}
                  <span style={{ color: "var(--marque-text-body)", flex: 1 }}>{e.error_message || "sans détail"}</span>
                  <span style={{ color: "var(--marque-text-muted)" }}>{e.qui || "système"}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {donnees && onglet === "journal" && donnees.droits.journal && (
        <div className="sym-in sym-card" style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)", padding: 24, boxShadow: "var(--marque-shadow-card)" }}>
          <h3 style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>Journal des actions</h3>
          <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--marque-text-muted)" }}>
            Les quatre-vingts dernières. Le journal dit qui a fait quoi, quand et combien de temps — jamais le contenu des échanges.
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead><tr>
                {["Quand", "Action", "Par", "Agent", "Modèle", "Durée", "Résultat"].map((c) => (
                  <th key={c} style={{ textAlign: "left", padding: "8px 12px", background: "var(--marque-primary-subtle)", color: "var(--marque-text-muted)", fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", fontWeight: 700 }}>{c}</th>
                ))}
              </tr></thead>
              <tbody>
                {donnees.journal.map((l, i) => (
                  <tr key={i}>
                    <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", color: "var(--marque-text-muted)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>{quand(l.created_at)}</td>
                    <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", fontWeight: 600, color: "var(--marque-text-primary)" }}>{libelleAction(l.action)}</td>
                    <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", color: "var(--marque-text-body)" }}>{l.qui || "système"}</td>
                    <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", color: "var(--marque-text-muted)" }}>{l.agent_id || "—"}</td>
                    <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", color: "var(--marque-text-muted)", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.model_used || "—"}</td>
                    <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)", color: "var(--marque-text-body)", fontVariantNumeric: "tabular-nums" }}>{typeof l.duration_ms === "number" ? `${(l.duration_ms / 1000).toFixed(1)} s` : "—"}</td>
                    <td style={{ padding: "8px 12px", borderTop: "1px solid var(--marque-border)" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 9px", borderRadius: "var(--marque-radius-pill)", background: l.success ? "var(--marque-paid-bg)" : "var(--marque-error-bg)", color: l.success ? "var(--marque-paid-text)" : "var(--marque-error-text)" }}>
                        {l.success ? "réussi" : "échec"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
