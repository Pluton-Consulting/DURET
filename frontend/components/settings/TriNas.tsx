"use client"
import { useEffect, useRef, useState } from "react"

/**
 * CE QUE L'ASSISTANT APPREND DU NAS (15/09, Duret — `backend/nas/tri.py`).
 *
 * « Enrichir les documents » ouvrait tout le NAS : trop long, et le serveur à
 * genoux. Ici l'administrateur fait PROPOSER un tri par l'IA — elle juge les
 * dossiers sur leurs noms, sans rien ouvrir —, corrige, puis valide. La
 * synchronisation suivante n'ouvre plus que ce qui est « à apprendre », les
 * affaires récentes d'abord, et remet les PDF scannés à la nuit. Photos et
 * fichiers trop anciens sont écartés sans IA ; une COPIE POSSIBLE (même nom,
 * même taille) est lue en dernier et reconnue à son contenu (16/09, audit
 * D-27). Rien n'est supprimé.
 */

type Decision = "apprendre" | "toujours" | "demande" | "ignorer"
interface Ligne { chemin: string; decision: Decision; raison?: string; fichiers?: number; annee?: number | null; degre?: number }
interface Estimation { total: number; a_lire: number; demande: number; ignorer: number; photo: number; ancien: number; doublon: number; format_non_lu: number; toujours?: number }
interface Ecartes { total: number; sans_texte: number; a_retenter: number; prets: number; prochain: number | null
                    exemples: { chemin: string; raison: string; tentatives: number }[] }
interface Etat {
  regles: Ligne[]; age_ans: number; estimation: Estimation | null; catalogue: string | null
  estimee_le?: number | null; catalogue_pret?: boolean
  ocr_differe: number; nuit: { debut: number; fin: number }
  ecartes?: Ecartes; reprise_demandee?: { le: number; tout: boolean } | null
  continu?: { active: boolean; prochain: number | null; dernier: number | null; rien_a_lire: boolean
              cycle_minutes: number; palier_minutes: number }
  proposition: { en_cours: boolean; avancement?: string | null; date?: number; appels?: number;
                 dossiers?: Ligne[]; erreur?: string | null; non_juges?: number; estimation?: Estimation }
}

const LIBELLES: Record<Decision, string> = {
  apprendre: "À apprendre", toujours: "Toujours apprendre", demande: "À la demande", ignorer: "Ignorer",
}
const nb = (n: number | undefined) => (n ?? 0).toLocaleString("fr-FR")

export default function TriNas({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [etat, setEtat] = useState<Etat | null>(null)
  const [lignes, setLignes] = useState<Ligne[]>([])
  const [source, setSource] = useState<"regles" | "proposition">("regles")
  const [age, setAge] = useState("3")
  const [erreur, setErreur] = useState("")
  const [bilan, setBilan] = useState("")
  const [enCours, setEnCours] = useState(false)
  const [toutReprendre, setToutReprendre] = useState(false)
  const minuterie = useRef<ReturnType<typeof setTimeout> | null>(null)
  const entetes = { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` }

  const charger = async (garderLignes = false) => {
    try {
      const r = await fetch(`${apiUrl}/api/nas-tri`, { headers: entetes, cache: "no-store" })
      const j = await r.json()
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`)
      setEtat(j)
      if (!garderLignes) {
        const prop = j.proposition?.dossiers as Ligne[] | undefined
        if (prop && prop.length && !j.proposition.en_cours) { setLignes(prop); setSource("proposition") }
        else { setLignes(j.regles || []); setSource("regles") }
        setAge(String(j.age_ans ?? 3))
      }
      if (j.proposition?.en_cours) minuterie.current = setTimeout(() => charger(false), 4000)
    } catch (e: any) { setErreur(e?.message || "Tri indisponible") }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { charger(); return () => { if (minuterie.current) clearTimeout(minuterie.current) } }, [apiUrl, backendToken])

  /** L'ESTIMATION SUR CLIC (23/09) : elle parcourt tout le catalogue du NAS ;
   *  l'ouverture de l'onglet ne la lance plus, elle montre la dernière. */
  const [estimationEnCours, setEstimationEnCours] = useState(false)
  async function estimer() {
    setErreur(""); setEstimationEnCours(true)
    try {
      const r = await fetch(`${apiUrl}/api/nas-tri/estimer`, { method: "POST", headers: entetes })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setErreur(d.detail || "L'estimation n'a pas pu être calculée."); return }
      setEtat((av) => av ? { ...av, estimation: d.estimation, estimee_le: d.estimee_le } : av)
    } catch { setErreur("Erreur réseau") } finally { setEstimationEnCours(false) }
  }

  async function proposer() {
    setErreur(""); setBilan("")
    const r = await fetch(`${apiUrl}/api/nas-tri/proposer`, { method: "POST", headers: entetes })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) { setErreur(d.detail || "La proposition n'a pas pu être lancée."); return }
    setBilan("Proposition lancée : l'IA juge les dossiers sur leurs noms, sans rien ouvrir. Quelques minutes.")
    charger()
  }

  /** L'INTÉGRATION CONTINUE (15/09) : le serveur lance lui-même un palier de
   *  lecture à chaque cycle — rien ne dépend de ce navigateur ni de ce PC. */
  async function basculerContinu(active: boolean) {
    setErreur("")
    const r = await fetch(`${apiUrl}/api/nas-tri/continu`, { method: "PUT", headers: entetes, body: JSON.stringify({ active }) })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) { setErreur(d.detail || "Le réglage n'a pas pu être enregistré."); return }
    await charger(true)
  }

  /** Réessayer les fichiers écartés (audit D-27) : un délai ponctuel ne doit
   *  pas exclure un document pour toujours. Appliqué au prochain palier. */
  async function reprendre() {
    setErreur(""); setBilan("")
    const r = await fetch(`${apiUrl}/api/nas-tri/reprendre`, {
      method: "POST", headers: entetes, body: JSON.stringify({ tout: toutReprendre }),
    })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) { setErreur(d.detail || "La reprise n'a pas pu être demandée."); return }
    setBilan("Reprise demandée : ces fichiers seront rouverts dès la prochaine synchronisation.")
    await charger(true)
  }

  async function valider() {
    setEnCours(true); setErreur(""); setBilan("")
    try {
      const r = await fetch(`${apiUrl}/api/nas-tri`, {
        method: "PUT", headers: entetes,
        body: JSON.stringify({ regles: lignes.map(({ chemin, decision }) => ({ chemin, decision })), age_ans: Number(age) }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setErreur(d.detail || "Le tri n'a pas pu être enregistré."); return }
      setBilan(`Tri validé : ${d.regles.length} règle(s). La prochaine synchronisation du NAS n'ouvrira que ce qui est à apprendre.`)
      await charger()
    } catch { setErreur("Erreur réseau") } finally { setEnCours(false) }
  }

  const e = etat?.proposition?.estimation && source === "proposition" ? etat.proposition.estimation : etat?.estimation
  const p = etat?.proposition
  const carte: React.CSSProperties = {
    background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)",
    boxShadow: "var(--marque-shadow-card)", padding: 20, marginTop: 24,
  }
  const champ: React.CSSProperties = {
    padding: "7px 10px", border: "1.5px solid var(--marque-border)", borderRadius: 10,
    fontSize: 13, background: "var(--marque-surface)", color: "var(--marque-text-primary)",
  }
  const bouton = (plein: boolean, actif = true): React.CSSProperties => ({
    background: plein ? "var(--marque-primary)" : "none", color: plein ? "var(--marque-text-on-dark)" : "var(--marque-text-body)",
    border: plein ? "none" : "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)",
    padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: actif ? "pointer" : "not-allowed", opacity: actif ? 1 : 0.55,
  })

  return (
    <div className="sym-card sym-in" style={carte} data-testid="tri-nas">
      <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)", marginBottom: 4 }}>
        Ce que l'assistant apprend du NAS
      </div>
      <p style={{ fontSize: 13, color: "var(--marque-text-body)", margin: "0 0 14px", maxWidth: 760 }}>
        Au lieu d'ouvrir tout le serveur, l'IA propose un tri des <b>dossiers</b> d'après leurs noms, sans rien lire :
        à apprendre, à la demande (l'assistant l'ouvre seulement si on le lui demande), ou à ignorer. Vous corrigez, puis
        validez. <b>Toujours apprendre</b> lit le dossier quel que soit l'âge des fichiers (trames, procédures,
        référentiels). Les photos et les fichiers trop anciens sont écartés sans IA ; une copie possible (même nom, même
        taille) est lue <b>après</b> les originaux et reconnue à son contenu — elle garde son dossier et ses droits. Les PDF
        scannés sont lus la nuit ({etat ? `${etat.nuit.debut} h – ${etat.nuit.fin} h` : "…"}). Rien n'est supprimé.
      </p>

      {e && (
        <div data-testid="tri-estimation" style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14, fontSize: 12.5 }}>
          {[
            [`${nb(e.a_lire)} à lire`, true], [`${nb(e.demande)} à la demande`, false], [`${nb(e.ignorer)} ignorés`, false],
            [`${nb(e.photo)} photos`, false], [`${nb(e.ancien)} anciens`, false],
            [`${nb(e.doublon)} copies possibles, lues en dernier`, false],
            ...(e.toujours ? [[`${nb(e.toujours)} toujours appris`, false] as [string, boolean]] : []),
            [`${nb(e.total)} fichiers au total`, false],
          ].map(([t, fort]) => (
            <span key={String(t)} style={{ padding: "4px 10px", borderRadius: "var(--marque-radius-pill)", border: "1px solid var(--marque-border)",
                                           fontWeight: fort ? 700 : 400, color: "var(--marque-text-body)" }}>{t}</span>
          ))}
          {etat && etat.ocr_differe > 0 && (
            <span style={{ padding: "4px 10px", borderRadius: "var(--marque-radius-pill)", border: "1px solid var(--marque-border)", color: "var(--marque-text-muted)" }}>
              {nb(etat.ocr_differe)} scan(s) attendent la nuit
            </span>
          )}
        </div>
      )}
      {etat?.continu && (
        <div data-testid="tri-continu" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, margin: "0 0 14px",
                                                padding: "10px 12px", border: "1px solid var(--marque-border)", borderRadius: 10 }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: "var(--marque-text-primary)", cursor: "pointer" }}>
            <input type="checkbox" checked={etat.continu.active} onChange={(ev) => basculerContinu(ev.target.checked)} />
            Intégration continue
          </label>
          <span style={{ fontSize: 12.5, color: "var(--marque-text-body)" }}>
            {etat.continu.active
              ? `Toutes les ${etat.continu.cycle_minutes} min, le serveur lit ce qu'il peut en ${etat.continu.palier_minutes} min et l'intègre aussitôt — même PC éteint. `
                + (etat.continu.rien_a_lire ? "Tout est à jour : il repassera au prochain relevé du NAS."
                   : etat.continu.prochain ? `Prochain palier vers ${new Date(etat.continu.prochain * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}.` : "Premier palier dans quelques minutes.")
              : "Coupée : le NAS n'est lu que lorsque vous lancez la synchronisation."}
          </span>
        </div>
      )}
      {etat?.ecartes && etat.ecartes.total > 0 && (
        <div data-testid="tri-ecartes" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10,
                                                margin: "0 0 14px", padding: "10px 12px",
                                                border: "1px solid var(--marque-border)", borderRadius: 10 }}>
          <span style={{ fontSize: 12.5, color: "var(--marque-text-body)" }}>
            <b>{nb(etat.ecartes.total)} fichier(s) écarté(s)</b> — {nb(etat.ecartes.sans_texte)} sans texte lisible
            (relus seulement s'ils changent), {nb(etat.ecartes.a_retenter)} à réessayer
            {etat.ecartes.prets > 0 ? ` dont ${nb(etat.ecartes.prets)} au prochain palier` : ""}
            {etat.ecartes.prochain
              ? `, le suivant le ${new Date(etat.ecartes.prochain * 1000).toLocaleDateString("fr-FR")}` : ""}.
            {etat.reprise_demandee ? " Une reprise est déjà demandée : elle s'applique au prochain palier." : ""}
          </span>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, cursor: "pointer" }}>
            <input type="checkbox" checked={toutReprendre} onChange={(ev) => setToutReprendre(ev.target.checked)} />
            y compris ceux sans texte
          </label>
          <button type="button" className="sym-tap" onClick={reprendre} style={bouton(false)} data-testid="tri-reprendre">
            Réessayer ces fichiers
          </button>
        </div>
      )}
      {etat && (
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, margin: "0 0 12px" }}>
          <button type="button" className="sym-tap" onClick={estimer} data-testid="tri-estimer"
                  disabled={estimationEnCours || etat.catalogue_pret === false}
                  style={bouton(false, !estimationEnCours && etat.catalogue_pret !== false)}>
            {estimationEnCours ? "Calcul en cours…" : "Calculer l'estimation"}
          </button>
          <span style={{ fontSize: 12.5, color: "var(--marque-text-muted)" }}>
            {etat.catalogue_pret === false ? "Le catalogue du NAS se construit : le calcul sera possible dans quelques minutes."
              : etat.estimee_le ? `Dernière estimation le ${new Date(etat.estimee_le * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}.`
              : "Aucune estimation encore : elle parcourt tout le NAS, elle ne se lance qu'à la demande."}
          </span>
        </div>
      )}

      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <button type="button" className="sym-tap" onClick={proposer} disabled={!!p?.en_cours}
                style={bouton(false, !p?.en_cours)} data-testid="tri-proposer">
          {p?.en_cours ? "L'IA trie…" : "Proposer un tri par l'IA"}
        </button>
        <label style={{ fontSize: 13, color: "var(--marque-text-body)", display: "inline-flex", alignItems: "center", gap: 6 }}>
          Ne pas apprendre les fichiers de plus de
          <input type="number" min={0} max={50} value={age} onChange={(ev) => setAge(ev.target.value.replace(/\D/g, ""))}
                 style={{ ...champ, width: 64 }} aria-label="Âge maximal en années" />
          ans <span style={{ color: "var(--marque-text-muted)", fontSize: 12 }}>(0 = aucune limite)</span>
        </label>
      </div>
      {p?.en_cours && p.avancement && (
        <p role="status" style={{ fontSize: 12.5, color: "var(--marque-text-body)", margin: "0 0 12px" }}>⏳ {p.avancement}</p>
      )}
      {p?.erreur && !p.en_cours && (
        <p style={{ fontSize: 12.5, color: "var(--marque-error-text)", margin: "0 0 12px" }}>La dernière proposition a échoué : {p.erreur}</p>
      )}

      {lignes.length > 0 && (
        <>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginBottom: 6 }}>
            {source === "proposition"
              ? `Proposition de l'IA${p?.date ? ` du ${new Date(p.date * 1000).toLocaleString("fr-FR")}` : ""} — ${lignes.length} dossier(s), ${p?.appels ?? 0} appel(s)${p?.non_juges ? `, ${p.non_juges} sous-dossier(s) non jugés (trop profonds : ils suivent leur parent)` : ""}. Rien n'est appliqué avant « Valider ».`
              : `Tri en vigueur — ${lignes.length} règle(s). Sans règle, un dossier est à apprendre.`}
          </div>
          <div style={{ maxHeight: 420, overflow: "auto", border: "1px solid var(--marque-border)", borderRadius: 10 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 560, fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: "left", color: "var(--marque-text-muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em",
                             position: "sticky", top: 0, background: "var(--marque-surface)" }}>
                  <th style={{ padding: "6px 8px" }}>Dossier</th><th style={{ padding: "6px 8px" }}>Décision</th>
                  <th style={{ padding: "6px 8px" }}>Fichiers</th><th style={{ padding: "6px 8px" }}>Pourquoi</th>
                </tr>
              </thead>
              <tbody>
                {lignes.map((l) => (
                  <tr key={l.chemin} style={{ borderTop: "1px solid var(--marque-border)" }}>
                    <td style={{ padding: "6px 8px", paddingLeft: 8 + 14 * Math.max(0, (l.degre ?? 1) - 1),
                                 fontFamily: "ui-monospace, monospace", fontSize: 12, overflowWrap: "anywhere" }} title={l.chemin}>
                      {l.chemin.split("/").slice(-Math.min(2, l.chemin.split("/").length - 1)).join("/")}
                    </td>
                    <td style={{ padding: "6px 8px" }}>
                      <select value={l.decision} style={champ} aria-label={`Décision pour ${l.chemin}`}
                              onChange={(ev) => setLignes((ls) => ls.map((x) => x.chemin === l.chemin ? { ...x, decision: ev.target.value as Decision } : x))}>
                        {(Object.keys(LIBELLES) as Decision[]).map((d) => <option key={d} value={d}>{LIBELLES[d]}</option>)}
                      </select>
                    </td>
                    <td style={{ padding: "6px 8px", color: "var(--marque-text-muted)", whiteSpace: "nowrap" }}>
                      {l.fichiers != null ? nb(l.fichiers) : ""}{l.annee ? ` · ${l.annee}` : ""}
                    </td>
                    <td style={{ padding: "6px 8px", color: "var(--marque-text-muted)", fontSize: 12 }}>{l.raison || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap" }}>
        <button type="button" className="sym-tap" onClick={valider} disabled={enCours || !/^\d+$/.test(age)}
                style={bouton(true, !enCours)} data-testid="tri-valider">
          {enCours ? "…" : source === "proposition" ? "Valider ce tri" : "Enregistrer"}
        </button>
        {source === "proposition" && etat && etat.regles.length > 0 && (
          <button type="button" className="sym-tap" style={bouton(false)}
                  onClick={() => { setLignes(etat.regles); setSource("regles") }}>
            Revenir au tri en vigueur
          </button>
        )}
      </div>
      {bilan && <p role="status" style={{ fontSize: 12.5, color: "var(--marque-text-body)", margin: "10px 0 0" }}>{bilan}</p>}
      {erreur && <p role="status" style={{ fontSize: 12.5, color: "var(--marque-error-text)", margin: "10px 0 0" }}>{erreur}</p>}
    </div>
  )
}
