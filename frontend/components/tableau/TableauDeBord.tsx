"use client"
import { useCallback, useEffect, useState } from "react"
import { EXPERTS } from "@/lib/permissions"
import { EVENEMENT_VUE } from "@/components/nav/EnTete"

/**
 * LE TABLEAU DE BORD — ce qu'un patron de PME veut voir en ouvrant l'outil.
 *
 * Pas le nombre de requêtes ni les jetons (ça, c'est Pilotage, pour qui
 * administre) : ce que l'outil lui a fait gagner, ce que chaque EXPERT a fait,
 * ce qui attend sa décision, ce qui est planifié, ce que l'entreprise
 * connaît, ce qui vient de se passer. Tout vient de `/api/dashboard/tableau`,
 * en une lecture ; le serveur a déjà tranché le périmètre (l'entreprise pour
 * la direction, sa propre activité pour un collaborateur).
 *
 * CHAQUE EXPERT A SON HISTORIQUE. Le bouton ouvre la liste de ses
 * conversations et tâches passées ; en cliquer une la PRÉ-INSCRIT dans le
 * chat — une petite carte au-dessus de la saisie, comme une pièce jointe —
 * et le prochain message part avec ce contexte. C'est ce qui permet de
 * reprendre « le devis de la semaine dernière » sans le réexpliquer.
 */
interface Props { apiUrl: string; token: string }

type Kpi = { libelle: string; valeur: number }
type Expert = { cle: string; actif: boolean; kpis: Kpi[]; en_attente: number }
type Donnees = {
  perimetre: "global" | "personnel"
  roi: { euros: number; heures: number; periode: string; cout_ia_eur: number | null
         hypotheses: Record<string, number>; detail: Record<string, number>
         serie: { jour: string; euros: number }[]; variation_pct: number | null } | null
  experts: Expert[]
  a_valider: { accords: any[]; competences: any[] }
  synthese: { terminees: number; en_attente: number; echouees: number; total: number; par_jour: { jour: string; conversations: number; actions: number }[] }
  planifiees: any[]
  executions?: any[]
  taches: any[]
  // `null` quand la personne n'a pas le périmètre : ces compteurs disent
  // combien la maison a de clients et de devis, ils ne sont pas pour tout
  // le monde. Le serveur ne les rend pas ; l'écran ne dessine pas la carte.
  memoire: { documents: number; devis: number; clients: number; fournisseurs: number; synchronisations: any[] } | null
  activite: any[]
}

export const CLE_CONTEXTE = "v2_contexte_prealable"
export const EVENEMENT_CONTEXTE = "v2:contexte"

export type ContextePrealable = {
  titre: string; resume: string; expert: string; source: "conversation" | "tache"; thread_id?: string | null
}

/** Pré-inscrit un contexte dans le chat et y emmène. */
export function preinscrire(contexte: ContextePrealable) {
  try { localStorage.setItem(CLE_CONTEXTE, JSON.stringify(contexte)) } catch { /* stockage plein ou bloqué : la carte ne s'affichera pas */ }
  window.dispatchEvent(new CustomEvent(EVENEMENT_CONTEXTE, { detail: contexte }))
  window.dispatchEvent(new CustomEvent(EVENEMENT_VUE + ":demande", { detail: "chat" }))
}

const euros = (v: number | null | undefined) =>
  typeof v === "number" ? v.toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }) : "—"
const quand = (iso?: string | null) => {
  if (!iso) return "—"
  const d = new Date(iso); if (isNaN(d.getTime())) return iso
  const maintenant = new Date()
  const memeJour = d.toDateString() === maintenant.toDateString()
  return memeJour ? d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
                  : d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" })
}
const ACTIONS: Record<string, string> = {
  chat_request: "a répondu à une question", skill_executed: "a fait une action",
  tache_differee_lancee: "a pris une tâche en arrière-plan", browser_task_completed: "a terminé une navigation web",
  skill_created: "a appris une compétence", skill_validated: "compétence validée",
}
const SKILLS: Record<string, string> = {
  rechercher_documents: "a cherché dans la mémoire", interroger_donnees: "a interrogé les données",
  lire_mails: "a relevé des mails", lire_mail: "a lu un mail", triage_email_entrant: "a trié un mail", redaction_email: "a rédigé un mail",
  resume_fil_email: "a résumé un échange de mails", produire_document: "a produit un document",
  terminer_document: "a terminé un document", creer_document: "a commencé un document", ajouter_document: "a complété un document",
  chercher_web: "a cherché sur le web", ouvrir_page: "a lu une page web", naviguer: "a navigué sur le web",
  retenir: "a retenu une consigne", connaissances_acquises: "a consulté ses connaissances",
}
const EXPERT_PAR_AGENT: Record<string, string> = { agent1: "L'expert devis & clients", agent2: "L'expert plans & visuels", agent3: "L'expert savoir-faire" }
const STATUTS: Record<string, { libelle: string; ton: string }> = {
  terminee: { libelle: "Terminée", ton: "ok" }, termine: { libelle: "Terminée", ton: "ok" },
  en_cours: { libelle: "En cours", ton: "attente" }, attente_validation: { libelle: "Attend votre accord", ton: "attente" },
  echec: { libelle: "Échouée", ton: "erreur" }, interrompue: { libelle: "Interrompue", ton: "neutre" },
}
const SCHEDULE: Record<string, string> = { interval: "toutes les", daily: "chaque jour à", weekly: "chaque semaine" }

/** La courbe du ROI : une aire douce, un trait, un point sur aujourd'hui. */
function CourbeRoi({ serie }: { serie: { jour: string; euros: number }[] }) {
  const L = 300, H = 64
  const vals = serie.map((s) => s.euros)
  const max = Math.max(1, ...vals)
  const pts = vals.map((v, i) => [
    (i / Math.max(1, vals.length - 1)) * L,
    H - 6 - (v / max) * (H - 14),
  ] as const)
  const trait = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ")
  const aire = `${trait} L${L},${H} L0,${H} Z`
  const [fx, fy] = pts[pts.length - 1] || [L, H - 6]
  return (
    <svg viewBox={`0 0 ${L} ${H}`} style={{ width: "100%", height: H, display: "block" }} aria-hidden>
      <defs>
        <linearGradient id="roiAire" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--marque-leaf)" stopOpacity=".28" />
          <stop offset="100%" stopColor="var(--marque-leaf)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={aire} fill="url(#roiAire)" />
      <path d={trait} fill="none" stroke="var(--marque-leaf)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={fx} cy={fy} r="3.4" fill="var(--marque-leaf)" stroke="var(--marque-surface)" strokeWidth="1.6" />
    </svg>
  )
}

function IconeExpert({ cle }: { cle: string }) {
  if (cle === "agent2") return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M9 22V12h6v10" /></svg>
  if (cle === "agent3") return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M12 2a7 7 0 0 0-4 12.7V17a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-2.3A7 7 0 0 0 12 2z" /><path d="M10 22h4" /></svg>
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>
}

export default function TableauDeBord({ apiUrl, token }: Props) {
  const [d, setD] = useState<Donnees | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [historiqueOuvert, setHistoriqueOuvert] = useState<string | null>(null)
  const [historiques, setHistoriques] = useState<Record<string, any>>({})
  const [hypotheses, setHypotheses] = useState(false)

  // CE TABLEAU NE SE RAFRAÎCHISSAIT JAMAIS (01/09). Un seul chargement au
  // montage — et, pire, la scène garde les DEUX vues montées : basculer
  // Chat → Tableau de bord ne remontait donc pas le composant et ne relisait
  // rien. Après une conversation, « À valider », « Tâches en arrière-plan » et
  // « Ce qui vient de se passer » restaient figés sur l'état d'ouverture de
  // l'onglet, jusqu'au F5. Or c'est précisément là qu'on va voir si un accord
  // attend.
  //
  // Trois déclencheurs, et aucun n'est un intervalle court : un tableau de bord
  // n'est pas un moniteur temps réel, et interroger toutes les cinq secondes
  // coûterait une requête par personne et par seconde pour rien.
  //   · au montage ;
  //   · quand l'onglet REDEVIENT visible (on revient du chat, ou du navigateur) ;
  //   · toutes les 60 s, mais SEULEMENT si l'onglet est visible.
  const charger = useCallback(async () => {
    try {
      const r = await fetch(`${apiUrl}/api/dashboard/tableau`,
        { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
      if (!r.ok) throw new Error(`Tableau de bord indisponible (${r.status})`)
      setD(await r.json()); setErreur(null)
    } catch (e: any) {
      setErreur(e?.message || "Tableau de bord indisponible")
    }
  }, [apiUrl, token])

  useEffect(() => {
    let vivant = true
    const relire = () => { if (vivant && document.visibilityState === "visible") charger() }
    relire()
    document.addEventListener("visibilitychange", relire)
    // La scène ne démonte pas la vue : c'est cet événement, émis par le switch,
    // qui dit qu'on revient regarder le tableau.
    window.addEventListener(EVENEMENT_VUE, relire)
    const minuterie = window.setInterval(relire, 60000)
    return () => {
      vivant = false
      document.removeEventListener("visibilitychange", relire)
      window.removeEventListener(EVENEMENT_VUE, relire)
      window.clearInterval(minuterie)
    }
  }, [apiUrl, token])

  const ouvrirHistorique = async (cle: string) => {
    if (historiqueOuvert === cle) { setHistoriqueOuvert(null); return }
    setHistoriqueOuvert(cle)
    if (historiques[cle]) return
    try {
      const r = await fetch(`${apiUrl}/api/dashboard/tableau/historique/${cle}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" })
      setHistoriques((h) => ({ ...h, [cle]: r.ok ? null : { erreur: true } }))
      if (r.ok) { const j = await r.json(); setHistoriques((h) => ({ ...h, [cle]: j })) }
    } catch { setHistoriques((h) => ({ ...h, [cle]: { erreur: true } })) }
  }

  if (erreur) return <div className="v2-vide" style={{ padding: 40 }}>{erreur}</div>
  if (!d) return (
    <div className="v2-grille" aria-busy>
      {[4, 4, 4, 4, 4, 4].map((s, i) => <div key={i} className="v2-carte sym-skeleton" style={{ gridColumn: `span ${s}`, height: 150 }} />)}
    </div>
  )

  const maxJour = Math.max(1, ...d.synthese.par_jour.map((j) => Number(j.conversations) + Number(j.actions)))
  const aValider = d.a_valider.accords.length + d.a_valider.competences.length
  const exp = (cle: string) => d.experts.find((e) => e.cle === cle)

  return (
    <div className="v2-grille">
      {/* ── ROI — carte de direction : le serveur ne la donne qu'à elle ── */}
      {d.roi && (
        <div className="v2-carte v2-apparait" style={{ gridColumn: "span 4", display: "flex", flexDirection: "column" }}>
          <div className="v2-carte-titre">
            <h3>ROI ce mois</h3>
            <button type="button" onClick={() => setHypotheses((h) => !h)}
                    style={{ border: "none", background: "transparent", cursor: "pointer", fontFamily: "inherit",
                             fontSize: 12.5, fontWeight: 600, color: "var(--marque-primary)", padding: 0 }}>
              {hypotheses ? "Masquer le détail" : "Détail →"}
            </button>
          </div>
          <div style={{ fontSize: 42, fontWeight: 800, letterSpacing: "-1.5px", lineHeight: 1,
                        color: "var(--marque-text-primary)", fontVariantNumeric: "tabular-nums" }}>
            {euros(d.roi.euros)}
          </div>
          <div style={{ marginTop: 6, fontSize: 13, color: "var(--marque-leaf)", fontWeight: 600 }}>
            {d.roi.variation_pct !== null ? `${d.roi.variation_pct >= 0 ? "+" : ""}${d.roi.variation_pct} % ce mois` : "premier mois mesuré"}
            <span style={{ color: "var(--marque-text-muted)", fontWeight: 500 }}> · {d.roi.heures.toLocaleString("fr-FR")} h économisées</span>
          </div>
          {!hypotheses && <div style={{ marginTop: "auto", paddingTop: 12 }}><CourbeRoi serie={d.roi.serie || []} /></div>}
          {hypotheses && (
            <div style={{ marginTop: 12, fontSize: 12.5, lineHeight: 1.55, color: "var(--marque-text-body)" }}>
              <b>{d.roi.detail.conversations}</b> conversations · <b>{d.roi.detail.documents}</b> documents · <b>{d.roi.detail.mails}</b> mails · <b>{d.roi.detail.analyses}</b> analyses · <b>{d.roi.detail.recherches}</b> recherches
              {d.roi.cout_ia_eur !== null && <> · coût IA <b>{euros(d.roi.cout_ia_eur)}</b></>}
              <div style={{ marginTop: 6, color: "var(--marque-text-muted)", fontSize: 12 }}>
                Estimation : temps valorisé {d.roi.hypotheses.taux_horaire} €/h ; un échange ≈ {d.roi.hypotheses.minutes_par_conversation} min,
                un document ≈ {d.roi.hypotheses.minutes_par_document} min, un mail ≈ {d.roi.hypotheses.minutes_par_mail} min,
                une analyse ≈ {d.roi.hypotheses.minutes_par_analyse} min, une recherche ≈ {d.roi.hypotheses.minutes_par_recherche} min.
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Synthèse ────────────────────────────────────────────────── */}
      <div className="v2-carte v2-apparait" style={{ gridColumn: "span 4" }}>
        <div className="v2-carte-titre"><h3>Ce mois-ci</h3><small>tâches confiées aux experts</small></div>
        <div className="v2-mini" style={{ marginTop: 0 }}>
          <div><b>{d.synthese.terminees}</b><span>terminées</span></div>
          <div><b>{d.synthese.en_attente}</b><span>en cours ou à décider</span></div>
          <div><b>{d.synthese.echouees}</b><span>n'ont pas abouti</span></div>
        </div>
        <div style={{ marginTop: 16, fontSize: 11, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "var(--marque-text-muted)" }}>
          Activité des 14 derniers jours
        </div>
        <div className="v2-barres" style={{ marginTop: 8 }} aria-label="Activité par jour">
          {d.synthese.par_jour.length === 0 && <i style={{ height: 3 }} />}
          {d.synthese.par_jour.map((j) => {
            const v = Number(j.conversations) + Number(j.actions)
            return <i key={j.jour} style={{ height: `${Math.max(6, Math.round((v / maxJour) * 100))}%` }} title={`${quand(j.jour)} : ${v}`} />
          })}
        </div>
      </div>

      {/* ── À valider ───────────────────────────────────────────────── */}
      <div className="v2-carte v2-apparait" style={{ gridColumn: "span 4", gridRow: "span 2" }}>
        <div className="v2-carte-titre">
          <h3>À valider</h3>
          <span className="v2-pastille" data-ton={aValider ? "attente" : "neutre"}>{aValider ? `${aValider} en attente` : "rien en attente"}</span>
        </div>
        {aValider === 0 && <div className="v2-vide">Aucune décision ne vous attend. Les experts travaillent en lecture : tout ce qui engage l'entreprise passe par vous.</div>}
        <div className="v2-liste">
          {d.a_valider.accords.map((a) => (
            <div key={a.id} style={{ flexDirection: "column", alignItems: "stretch", gap: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <b style={{ fontSize: 13 }}>{EXPERT_PAR_AGENT[a.agent] || "Un expert"} demande un accord{a.reason ? ` — ${a.reason}` : ""}</b>
                <time>{quand(a.created_at)}</time>
              </div>
              {a.apercu && <div style={{ color: "var(--marque-text-muted)", fontSize: 12.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.apercu}</div>}
              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <button type="button" className="v2-bouton-plein"
                        onClick={() => preinscrire({ titre: `Accord : ${a.reason || "action"}`, resume: a.apercu || "", expert: a.agent || "agent1", source: "tache", thread_id: a.thread_id })}>
                  Voir dans le chat
                </button>
              </div>
            </div>
          ))}
          {d.a_valider.competences.map((c) => (
            <div key={c.name} style={{ flexDirection: "column", alignItems: "stretch", gap: 2 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <b style={{ fontSize: 13 }}>Nouvelle compétence à valider : {c.name}</b><time>{quand(c.created_at)}</time>
              </div>
              <div style={{ color: "var(--marque-text-muted)", fontSize: 12.5 }}>{c.description || "—"} · <a href="/connaissances" style={{ color: "var(--marque-primary)" }}>ouvrir Connaissances</a></div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Les experts ─────────────────────────────────────────────── */}
      {EXPERTS.map((e) => {
        const x = exp(e.cle)
        const h = historiques[e.cle]
        return (
          <div key={e.cle} className="v2-carte v2-apparait" style={{ gridColumn: "span 4" }}>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <div className="v2-expert-ico"><IconeExpert cle={e.cle} /></div>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 800, fontSize: 15, color: "var(--marque-text-primary)", letterSpacing: "-.1px" }}>{e.nom}</div>
                <div style={{ fontSize: 12, color: "var(--marque-text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.domaine}</div>
              </div>
              <span className="v2-pastille">Actif</span>
            </div>
            <div className="v2-mini">
              {(x?.kpis || []).map((k) => <div key={k.libelle}><b>{k.valeur}</b><span>{k.libelle}</span></div>)}
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12, gap: 8 }}>
              <span className="v2-pastille" data-ton={x?.en_attente ? "attente" : "neutre"}>
                {x?.en_attente ? `${x.en_attente} action(s) en attente` : "aucune action en attente"}
              </span>
              <button type="button" className="v2-bouton-doux" onClick={() => ouvrirHistorique(e.cle)} aria-expanded={historiqueOuvert === e.cle}>
                {historiqueOuvert === e.cle ? "Fermer" : "Historique"}
              </button>
            </div>
            {historiqueOuvert === e.cle && (
              <div className="v2-historique">
                {h === undefined && <div className="v2-vide">Chargement…</div>}
                {h?.erreur && <div className="v2-vide">Historique indisponible.</div>}
                {h && !h.erreur && (h.conversations?.length || h.taches?.length) === 0 && <div className="v2-vide">Aucune conversation ni tâche avec cet expert pour l'instant.</div>}
                {h && !h.erreur && (h.taches || []).map((t: any) => (
                  <button key={t.id} type="button"
                          onClick={() => preinscrire({ titre: t.demande, resume: t.reponse || t.status, expert: e.cle, source: "tache" })}>
                    <span style={{ fontWeight: 600 }}>Tâche · {t.demande}</span>
                    <small>{STATUTS[t.status]?.libelle || t.status} · {quand(t.updated_at)}</small>
                  </button>
                ))}
                {h && !h.erreur && (h.conversations || []).map((c: any) => (
                  <button key={c.thread_id} type="button"
                          onClick={() => preinscrire({ titre: c.title || "Conversation", resume: c.derniere_reponse || "", expert: e.cle, source: "conversation", thread_id: c.thread_id })}>
                    <span style={{ fontWeight: 600 }}>{c.title || "Conversation"}</span>
                    <small>{c.nb_messages} message(s) · {quand(c.updated_at)}{c.derniere_reponse ? ` · ${c.derniere_reponse}` : ""}</small>
                  </button>
                ))}
              </div>
            )}
          </div>
        )
      })}

      {/* ── Mémoire d'entreprise ─────────────────────────────────────── */}
      {d.memoire && (
      <div className="v2-carte v2-apparait" style={{ gridColumn: "span 4" }}>
        <div className="v2-carte-titre"><h3>Ce que l'entreprise a confié à l'outil</h3><small>mémoire d'entreprise</small></div>
        <div className="v2-mini" style={{ marginTop: 0, gridTemplateColumns: "repeat(4, 1fr)" }}>
          <div><b>{d.memoire.documents}</b><span>documents</span></div>
          <div><b>{d.memoire.devis}</b><span>devis</span></div>
          <div><b>{d.memoire.clients}</b><span>clients</span></div>
          <div><b>{d.memoire.fournisseurs}</b><span>fournisseurs</span></div>
        </div>
        <div className="v2-liste" style={{ marginTop: 10 }}>
          {d.memoire.synchronisations.length === 0 && <div className="v2-vide" style={{ padding: "10px 0" }}>Aucune synchronisation de source lancée pour l'instant.</div>}
          {d.memoire.synchronisations.map((s: any) => (
            <div key={s.source}>
              <span style={{ fontWeight: 600, textTransform: "capitalize", minWidth: 90 }}>{String(s.source).replace(/_/g, " ")}</span>
              <span className="v2-pastille" data-ton={s.statut === "terminee" ? undefined : s.statut === "en_cours" ? "attente" : s.statut === "echec" ? "erreur" : "neutre"}>
                {s.statut === "terminee" ? "à jour" : s.statut === "en_cours" ? "en cours" : s.statut === "echec" ? "en échec" : s.statut.replace(/_/g, " ")}
              </span>
              <time style={{ marginLeft: "auto" }}>{quand(s.termine_a || s.demarre_a)}</time>
            </div>
          ))}
        </div>
      </div>
      )}

      {/* ── Les RÉVEILS des tâches planifiées ──────────────────────────
          Le worker écrivait ses exécutions dans une table que RIEN ne lisait :
          une tâche de 7 h 30 qui plantait ne laissait aucune trace à l'écran.
          On montre l'issue, et la cause quand il y en a une. */}
      {(d.executions?.length ?? 0) > 0 && (
        <div className="v2-carte v2-apparait" style={{ gridColumn: "span 4" }}>
          <div className="v2-carte-titre">
            <h3>Derniers réveils</h3><small>7 derniers jours</small>
          </div>
          <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
            {(d.executions || []).map((e: any) => (
              <div key={e.id} style={{ display: "flex", alignItems: "center", gap: 10,
                                       flexWrap: "wrap", fontSize: 13 }}>
                <span style={{
                  fontWeight: 700,
                  color: e.status === "failed" ? "var(--marque-error-text)"
                       : e.status === "completed" ? "var(--marque-paid-text)"
                       : "var(--marque-text-muted)",
                }}>
                  {e.status === "failed" ? "échec"
                   : e.status === "completed" ? "fait"
                   : e.status === "awaiting_approval" ? "attend un accord"
                   : e.status}
                </span>
                <span style={{ flex: 1, minWidth: 140 }}>{e.title}</span>
                <span style={{ color: "var(--marque-text-muted)", fontSize: 12 }}>
                  {e.started_at ? new Date(e.started_at).toLocaleString("fr-FR",
                    { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—"}
                </span>
                {e.error && (
                  <span style={{ width: "100%", fontSize: 12,
                                 color: "var(--marque-error-text)" }}>{e.error}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Actions planifiées ─────────────────────────────────────────── */}
      <div className="v2-carte v2-apparait" style={{ gridColumn: "span 4" }}>
        <div className="v2-carte-titre"><h3>Actions planifiées</h3><small>{d.planifiees.length || "aucune"}</small></div>
        {d.planifiees.length === 0 && <div className="v2-vide">Rien n'est programmé. Une tâche récurrente (relances, veille, tri du courrier) se crée depuis le chat : « chaque lundi à 8h, … ».</div>}
        <div className="v2-liste">
          {d.planifiees.map((p: any) => (
            <div key={p.id}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--marque-primary-mid)", flexShrink: 0, position: "relative", top: -1 }} />
              <span style={{ flex: 1, minWidth: 0 }}>
                <span style={{ fontWeight: 600, display: "block" }}>{p.title}</span>
                <span style={{ color: "var(--marque-text-muted)", fontSize: 12 }}>
                  {EXPERT_PAR_AGENT[p.agent] || "Expert"} · {SCHEDULE[p.schedule_kind] || ""} {p.schedule_kind === "interval" ? `${p.interval_minutes} min` : p.time_of_day ? String(p.time_of_day).slice(0, 5) : ""}
                </span>
              </span>
              <time>{p.next_run_at ? quand(p.next_run_at) : "—"}</time>
            </div>
          ))}
        </div>
      </div>

      {/* ── Tâches récentes ────────────────────────────────────────────── */}
      <div className="v2-carte v2-apparait" style={{ gridColumn: "span 4" }}>
        <div className="v2-carte-titre"><h3>Tâches en arrière-plan</h3><small>les dernières</small></div>
        {d.taches.length === 0 && <div className="v2-vide">Aucune tâche pour l'instant. Les demandes longues (analyser tout un dossier, préparer plusieurs documents) passent ici et vous retrouvent dans le chat.</div>}
        <div className="v2-liste">
          {d.taches.map((t: any) => {
            const s = STATUTS[t.status] || { libelle: t.status, ton: "neutre" }
            return (
              <div key={t.id} style={{ alignItems: "center" }}>
                <span className="v2-pastille" data-ton={s.ton === "ok" ? undefined : s.ton}>{s.libelle}</span>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={t.demande}>{t.demande}</span>
                <time>{quand(t.updated_at)}</time>
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Activité récente ───────────────────────────────────────────── */}
      <div className="v2-carte v2-apparait" style={{ gridColumn: "span 12" }}>
        <div className="v2-carte-titre"><h3>Ce qui vient de se passer</h3><small>{d.perimetre === "global" ? "toute l'entreprise" : "votre activité"}</small></div>
        {d.activite.length === 0 && <div className="v2-vide">Rien encore. Posez une première question dans le chat.</div>}
        <div className="v2-liste">
          {d.activite.map((a: any, i: number) => (
            <div key={i} style={{ alignItems: "center" }}>
              <time>{quand(a.created_at)}</time>
              <span style={{ fontWeight: 600, minWidth: 170 }}>{EXPERT_PAR_AGENT[a.agent_id] || (a.agent_id ? a.agent_id : "L'assistant")}</span>
              <span style={{ flex: 1, color: "var(--marque-text-body)" }}>
                {a.action === "skill_executed" ? (SKILLS[a.skill] || `a fait : ${String(a.skill || "").replace(/_/g, " ")}`) : (ACTIONS[a.action] || a.action.replace(/_/g, " "))}
                {a.qui ? <span style={{ color: "var(--marque-text-muted)" }}> · pour {a.qui}</span> : null}
              </span>
              <span className="v2-pastille" data-ton={a.success === false ? "erreur" : undefined}>{a.success === false ? "échec" : "ok"}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
