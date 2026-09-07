"use client"
/**
 * LES ÉCHANGES, PERSONNE PAR PERSONNE — console développeur (07/09).
 *
 * Demande de Noa : « depuis l'espace admin, dans les logs, voir de façon simple
 * les questions/réponses posées par chacun des utilisateurs, avec les logs de
 * chacun en détail déroulant. »
 *
 * CE QUI SE LIT SANS CLIQUER, et c'est tout le point : l'heure, QUI a demandé,
 * la question, et le verdict du tour (réussi, échoué, combien de gestes, combien
 * en échec). Le reste — la réponse entière et les lignes techniques — se déroule.
 * Le flux d'audit de la colonne d'à côté montre les mêmes lignes SANS le contenu :
 * ici on voit ce qui a été dit, là on voit ce que la machine a fait.
 *
 * Une ligne par TOUR, jamais par message : c'est l'unité qu'on relit quand
 * quelque chose s'est mal passé.
 */
import { useCallback, useEffect, useState } from "react"

interface Props {
  apiUrl: string
  token: string
  /** Les couleurs de la console : la palette y est déjà décidée. */
  C: Record<string, string>
}

interface Geste { skill: string; ok: boolean }
interface LigneDetail {
  quand: string; action: string; succes: boolean; erreur: string | null
  modele: string | null; duree_ms: number | null; metadata: any
}
interface Echange {
  id: string; quand: string; fil: string | null; expert: string | null
  utilisateur: { id: string; email: string | null; nom: string | null; role: string | null }
  question: string; reponse: string; sans_reponse: boolean
  modele: string | null; duree_ms: number | null; cout_eur: number; jetons: number
  succes: boolean; erreur: string | null; gestes: Geste[]; pieces: number
  detail: LigneDetail[]; detail_exact: boolean
}
interface Personne { id: string; email: string | null; nom: string | null; role: string | null }

const PERIODES = [
  { valeur: 1, libelle: "24 h" },
  { valeur: 7, libelle: "7 jours" },
  { valeur: 30, libelle: "30 jours" },
]

function heure(iso: string) {
  try {
    return new Date(iso).toLocaleString("fr-FR",
      { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
  } catch { return "—" }
}

function duree(ms: number | null) {
  if (!ms) return "—"
  return ms < 1000 ? `${ms} ms` : ms < 60000 ? `${(ms / 1000).toFixed(1)} s`
    : `${Math.floor(ms / 60000)} min ${String(Math.round((ms % 60000) / 1000)).padStart(2, "0")}`
}

function qui(p: Personne | Echange["utilisateur"]) {
  return p.nom || p.email || "compte supprimé"
}

/** Ce qu'une ligne du journal DIT, et pas seulement son type.
 *
 * Relevé par Noa le 07/09 : « il y a juste écrit skill executed ». Le nom du
 * geste était pourtant déjà journalisé (`metadata.skill`, depuis toujours) —
 * l'écran ne le lisait pas. Une ligne de journal qui ne nomme pas ce qu'elle
 * décrit ne sert à personne.
 */
function libelleLigne(l: LigneDetail) {
  const m = l.metadata || {}
  if (l.action === "skill_executed" && m.skill) return m.skill
  if (l.action === "filet_mecanique" && m.filet) return `filet « ${m.filet} »`
  if (l.action === "chat_request") return l.modele ? `réponse · ${l.modele}` : "réponse"
  return l.action
}

/** Les précisions utiles d'une ligne — jamais du contenu de message. */
function detailsLigne(l: LigneDetail) {
  const m = l.metadata || {}
  const out: string[] = []
  if (l.action === "skill_executed") {
    if (m.effet) out.push(`effet ${m.effet}`)
    if (m.mailbox) out.push(String(m.mailbox))
    if (m.status && m.status !== "native") out.push(String(m.status))
  }
  if (l.action === "filet_mecanique" && m.cause) out.push(String(m.cause))
  if (l.action === "chat_request" && Array.isArray(m.gestes) && m.gestes.length) {
    out.push(`${m.gestes.length} geste${m.gestes.length > 1 ? "s" : ""}`)
  }
  return out
}

export default function Echanges({ apiUrl, token, C }: Props) {
  const [echanges, setEchanges] = useState<Echange[]>([])
  const [gens, setGens] = useState<Personne[]>([])
  const [personne, setPersonne] = useState("")
  const [jours, setJours] = useState(7)
  const [q, setQ] = useState("")
  const [recherche, setRecherche] = useState("")
  const [page, setPage] = useState(1)
  const [ouverts, setOuverts] = useState<Record<string, boolean>>({})
  const [charge, setCharge] = useState(false)
  const [err, setErr] = useState("")

  const LIMITE = 40

  const charger = useCallback(async () => {
    setCharge(true)
    try {
      const p = new URLSearchParams({ jours: String(jours), limite: String(LIMITE), page: String(page) })
      if (personne) p.set("utilisateur", personne)
      if (recherche) p.set("q", recherche)
      const res = await fetch(`${apiUrl}/api/dashboard/echanges?${p}`,
        { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setEchanges(data.echanges || [])
      // La liste des personnes ne dépend pas du filtre : on la garde telle
      // qu'elle est arrivée la première fois, sinon choisir quelqu'un ferait
      // disparaître tous les autres du menu.
      setGens((prev) => (personne ? prev : data.utilisateurs || []))
      setErr("")
    } catch (e: any) {
      setErr(e?.message || "erreur")
    } finally {
      setCharge(false)
    }
  }, [apiUrl, token, jours, page, personne, recherche])

  useEffect(() => { charger() }, [charger])

  const champ = {
    background: C.panel2, color: C.text, border: `1px solid ${C.border}`,
    borderRadius: 6, padding: "5px 9px", fontFamily: C.mono, fontSize: 12,
  } as const

  return (
    <div className="sym-in" style={{
      background: C.panel, border: `1px solid ${C.border}`,
      borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)",
      overflow: "hidden", marginTop: 16,
    }}>
      <div style={{
        padding: "10px 14px", borderBottom: `1px solid ${C.border}`,
        display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
      }}>
        <div style={{ fontSize: 12, color: C.dim }}>
          Échanges — questions &amp; réponses, par personne
        </div>
        <div style={{ flex: 1 }} />

        <select value={personne} aria-label="Filtrer par personne" style={champ}
                onChange={(e) => { setPersonne(e.target.value); setPage(1) }}>
          <option value="">tout le monde</option>
          {gens.map((g) => (
            <option key={g.id} value={g.id}>{qui(g)} · {g.role}</option>
          ))}
        </select>

        <select value={jours} aria-label="Période" style={champ}
                onChange={(e) => { setJours(Number(e.target.value)); setPage(1) }}>
          {PERIODES.map((p) => <option key={p.valeur} value={p.valeur}>{p.libelle}</option>)}
        </select>

        <form onSubmit={(e) => { e.preventDefault(); setRecherche(q.trim()); setPage(1) }}>
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="chercher dans les mots…" aria-label="Chercher dans les échanges"
                 style={{ ...champ, width: 190 }} />
        </form>
      </div>

      {err && <div style={{ padding: "10px 14px", color: C.red, fontSize: 12 }}>⚠ {err}</div>}

      <div style={{ maxHeight: 620, overflowY: "auto" }}>
        {!echanges.length && !charge && (
          <div style={{ padding: 20, color: C.dim, fontSize: 12 }}>
            aucun échange sur cette période
          </div>
        )}

        {echanges.map((e) => {
          const rates = e.gestes.filter((g) => !g.ok).length
          const ouvert = !!ouverts[e.id]
          return (
            <div key={e.id} style={{ borderBottom: `1px solid ${C.panel2}` }}>
              <button
                type="button"
                onClick={() => setOuverts((o) => ({ ...o, [e.id]: !o[e.id] }))}
                aria-expanded={ouvert}
                style={{
                  width: "100%", textAlign: "left", background: "none", border: "none",
                  color: C.text, fontFamily: C.mono, cursor: "pointer",
                  padding: "9px 14px", display: "flex", gap: 10, alignItems: "baseline",
                }}
              >
                <span style={{ color: C.dim, fontSize: 11, flex: "none", width: 96 }}>
                  {heure(e.quand)}
                </span>
                <span style={{
                  flex: "none", fontSize: 11, maxWidth: 150, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap",
                  color: e.utilisateur.role === "super_admin" ? C.amber : C.blue,
                }}>
                  {qui(e.utilisateur)}
                </span>
                <span style={{
                  flex: 1, fontSize: 12, overflow: "hidden",
                  textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {e.question || "(message sans texte)"}
                </span>
                {e.pieces > 0 && (
                  <span style={{ flex: "none", fontSize: 11, color: C.dim }}>
                    📎 {e.pieces}
                  </span>
                )}
                {e.gestes.length > 0 && (
                  <span style={{ flex: "none", fontSize: 11, color: rates ? C.red : C.dim }}>
                    {e.gestes.length} geste{e.gestes.length > 1 ? "s" : ""}
                    {rates ? ` · ${rates} en échec` : ""}
                  </span>
                )}
                <span style={{ flex: "none", fontSize: 11, color: C.dim, width: 62, textAlign: "right" }}>
                  {duree(e.duree_ms)}
                </span>
                <span style={{ flex: "none", color: e.succes && !e.sans_reponse ? C.green : C.red }}>
                  {e.succes && !e.sans_reponse ? "●" : "▲"}
                </span>
                <span style={{ flex: "none", color: C.dim, fontSize: 11 }}>{ouvert ? "▾" : "▸"}</span>
              </button>

              {ouvert && (
                <div style={{ padding: "0 14px 14px 110px", fontSize: 12 }}>
                  <div style={{ color: C.dim, fontSize: 10.5, textTransform: "uppercase",
                                letterSpacing: ".08em", marginBottom: 4 }}>
                    Ce qui a été demandé
                  </div>
                  <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", marginBottom: 12 }}>
                    {e.question || "(message sans texte)"}
                  </div>

                  <div style={{ color: C.dim, fontSize: 10.5, textTransform: "uppercase",
                                letterSpacing: ".08em", marginBottom: 4 }}>
                    Ce que l&apos;assistant a répondu
                  </div>
                  <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word",
                                color: e.sans_reponse ? C.red : C.text, marginBottom: 12 }}>
                    {e.reponse || "Aucune réponse enregistrée pour ce tour."}
                  </div>

                  {e.gestes.length > 0 && (
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ color: C.dim, fontSize: 10.5, textTransform: "uppercase",
                                    letterSpacing: ".08em", marginBottom: 4 }}>
                        Ce qui a tourné
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {e.gestes.map((g, i) => (
                          <span key={`${g.skill}-${i}`} style={{
                            fontSize: 11, padding: "1px 7px", borderRadius: 4,
                            border: `1px solid ${g.ok ? C.border : C.red}`,
                            color: g.ok ? C.dim : C.red,
                          }}>
                            {g.skill}{g.ok ? "" : " ✗"}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {e.erreur && (
                    <div style={{ color: C.red, marginBottom: 12, whiteSpace: "pre-wrap",
                                  wordBreak: "break-word" }}>
                      ⚠ {e.erreur}
                    </div>
                  )}

                  <div style={{ color: C.dim, fontSize: 10.5, textTransform: "uppercase",
                                letterSpacing: ".08em", marginBottom: 4 }}>
                    Journal du tour
                    {!e.detail_exact && (
                      <span style={{ textTransform: "none", letterSpacing: 0 }}>
                        {" "}— rapproché par l&apos;heure, pas par le fil : ce tour
                        est antérieur au marquage des fils
                      </span>
                    )}
                  </div>
                  <div style={{ color: C.dim, fontSize: 11.5 }}>
                    <div>
                      expert {e.expert || "—"} · modèle {e.modele || "—"} ·{" "}
                      {e.jetons} jeton{e.jetons > 1 ? "s" : ""} ·{" "}
                      {e.cout_eur.toFixed(4)} € · fil {e.fil?.slice(0, 8) || "—"}
                    </div>
                    {e.detail.map((l, i) => (
                      <div key={i} style={{ marginTop: 3 }}>
                        <span style={{ color: l.succes ? C.dim : C.red }}>
                          {l.succes ? "·" : "▲"} {heure(l.quand)} {libelleLigne(l)}
                        </span>
                        {l.duree_ms ? ` · ${duree(l.duree_ms)}` : ""}
                        {l.erreur ? <span style={{ color: C.red }}> · {l.erreur}</span> : ""}
                        {detailsLigne(l).length > 0 && (
                          <span style={{ color: C.dim }}>
                            {" · "}{detailsLigne(l).join(" · ")}
                          </span>
                        )}
                      </div>
                    ))}
                    {!e.detail.length && <div style={{ marginTop: 3 }}>aucune ligne technique</div>}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div style={{
        padding: "8px 14px", borderTop: `1px solid ${C.border}`,
        display: "flex", alignItems: "center", gap: 10, fontSize: 11, color: C.dim,
      }}>
        <span>{charge ? "chargement…" : `${echanges.length} échange${echanges.length > 1 ? "s" : ""}`}</span>
        <div style={{ flex: 1 }} />
        <button type="button" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}
                style={{ ...champ, cursor: page <= 1 ? "default" : "pointer", opacity: page <= 1 ? 0.4 : 1 }}>
          ◂ précédents
        </button>
        <span>page {page}</span>
        <button type="button" disabled={echanges.length < LIMITE} onClick={() => setPage((p) => p + 1)}
                style={{ ...champ, cursor: echanges.length < LIMITE ? "default" : "pointer",
                         opacity: echanges.length < LIMITE ? 0.4 : 1 }}>
          suivants ▸
        </button>
      </div>
    </div>
  )
}
