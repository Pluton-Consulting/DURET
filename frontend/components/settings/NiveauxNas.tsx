"use client"
import { useEffect, useState } from "react"

/**
 * QUI VOIT QUEL DOSSIER DU NAS (13/09, Duret).
 *
 * Chaque profil a un rôle ; la synchronisation et « Enrichir les documents »
 * rangent ce qu'ils lisent au niveau d'accès du DOSSIER d'où ça vient. Ici,
 * l'administrateur attribue un niveau à des dossiers. Un dossier vaut pour
 * tout ce qu'il contient, la règle du chemin le plus long l'emporte, et sans
 * règle vaut le niveau par défaut du serveur. Enregistrer reclasse aussitôt
 * les documents déjà importés ; le chat ne liste, ne trouve et n'ouvre plus
 * que ce que le rôle voit.
 */

interface Regle { chemin: string; niveau: string }
interface Niveau { cle: string; libelle: string; roles: string[] }
interface Etat {
  regles: Regle[]; defaut: string; echelle: Niveau[]; racines: string[]
  dossiers: string[]; catalogue: string; connaissances_documents: number | null
}

export default function NiveauxNas({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [etat, setEtat] = useState<Etat | null>(null)
  const [regles, setRegles] = useState<Regle[]>([])
  const [chemin, setChemin] = useState("")
  const [niveau, setNiveau] = useState("direction_only")
  const [erreur, setErreur] = useState("")
  const [bilan, setBilan] = useState("")
  const [enCours, setEnCours] = useState(false)
  const [confirmer, setConfirmer] = useState(false)
  const entetes = { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` }

  const charger = () =>
    fetch(`${apiUrl}/api/nas-niveaux`, { headers: entetes, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : r.json().then((d) => Promise.reject(new Error(d.detail || `HTTP ${r.status}`)))))
      .then((j: Etat) => { setEtat(j); setRegles(j.regles || []) })
      .catch((e) => setErreur(e?.message || "Niveaux indisponibles"))

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { charger() }, [apiUrl, backendToken])

  const libelle = (cle: string) => etat?.echelle.find((n) => n.cle === cle)?.libelle || cle
  const modifie = JSON.stringify(regles) !== JSON.stringify(etat?.regles || [])

  function ajouter() {
    const c = chemin.trim()
    if (!c) return
    setRegles((r) => [...r.filter((x) => x.chemin.toLowerCase() !== c.toLowerCase()), { chemin: c, niveau }]
      .sort((a, b) => a.chemin.localeCompare(b.chemin)))
    setChemin("")
  }

  async function enregistrer() {
    setEnCours(true); setErreur(""); setBilan("")
    try {
      const r = await fetch(`${apiUrl}/api/nas-niveaux`, { method: "PUT", headers: entetes, body: JSON.stringify({ regles }) })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setErreur(d.detail || "Les règles n'ont pas pu être enregistrées."); return }
      const rc = d.reclassement || {}
      setBilan(rc.erreur
        ? `Règles enregistrées, mais le reclassement a échoué : ${rc.erreur}`
        : `Règles enregistrées. ${rc.reclasses ?? 0} document(s) déjà importé(s) reclassé(s) sur ${rc.documents ?? 0}`
          + (rc.catalogue_pret === false ? " (catalogue du NAS pas encore prêt : les chemins très longs attendront la prochaine synchronisation)" : "")
          + ". La carte du classement se reconstruit.")
      await charger()
    } catch { setErreur("Erreur réseau") } finally { setEnCours(false) }
  }

  async function reprendre() {
    setEnCours(true); setErreur(""); setBilan(""); setConfirmer(false)
    try {
      const r = await fetch(`${apiUrl}/api/nas-niveaux/reprendre-connaissances`, { method: "POST", headers: entetes })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) { setErreur(d.detail || "La reprise n'a pas pu être lancée."); return }
      setBilan(`${d.retirees} connaissance(s) retirée(s) ; « Enrichir les documents » est relancé et les réécrira au niveau de leurs dossiers.`)
      await charger()
    } catch { setErreur("Erreur réseau") } finally { setEnCours(false) }
  }

  const carte: React.CSSProperties = {
    background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)",
    boxShadow: "var(--marque-shadow-card)", padding: 20, marginTop: 24,
  }
  const champ: React.CSSProperties = {
    padding: "9px 12px", border: "1.5px solid var(--marque-border)", borderRadius: 10,
    fontSize: 13.5, outline: "none", background: "var(--marque-surface)", color: "var(--marque-text-primary)",
  }
  const bouton = (plein: boolean): React.CSSProperties => ({
    background: plein ? "var(--marque-primary)" : "none", color: plein ? "var(--marque-text-on-dark)" : "var(--marque-text-body)",
    border: plein ? "none" : "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)",
    padding: "8px 18px", fontSize: 13, fontWeight: 600, cursor: enCours ? "wait" : "pointer",
  })

  return (
    <div className="sym-card sym-in" style={carte} data-testid="niveaux-nas">
      <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)", marginBottom: 4 }}>
        Qui voit quel dossier du NAS
      </div>
      <p style={{ fontSize: 13, color: "var(--marque-text-body)", margin: "0 0 14px", maxWidth: 720 }}>
        Le niveau d'un dossier vaut pour tout ce qu'il contient : documents importés, connaissances tirées par
        « Enrichir les documents », carte du classement, et ce que l'assistant liste ou ouvre dans le chat.
        La règle la plus précise l'emporte. Sans règle : <b>{etat ? libelle(etat.defaut) : "…"}</b>.
      </p>

      {etat && (
        <div style={{ overflowX: "auto", marginBottom: 14 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 520, fontSize: 13 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--marque-text-muted)", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                <th style={{ padding: "6px 8px" }}>Dossier</th><th style={{ padding: "6px 8px" }}>Visible par</th><th />
              </tr>
            </thead>
            <tbody>
              {regles.map((r) => (
                <tr key={r.chemin} style={{ borderTop: "1px solid var(--marque-border)" }}>
                  <td style={{ padding: "8px", fontFamily: "ui-monospace, monospace", overflowWrap: "anywhere" }}>{r.chemin}</td>
                  <td style={{ padding: "8px" }}>
                    <select value={r.niveau} style={champ}
                            onChange={(e) => setRegles((l) => l.map((x) => x.chemin === r.chemin ? { ...x, niveau: e.target.value } : x))}>
                      {etat.echelle.map((n) => <option key={n.cle} value={n.cle}>{n.libelle}</option>)}
                    </select>
                  </td>
                  <td style={{ padding: "8px", textAlign: "right" }}>
                    <button type="button" className="sym-tap" style={bouton(false)}
                            onClick={() => setRegles((l) => l.filter((x) => x.chemin !== r.chemin))}>Retirer</button>
                  </td>
                </tr>
              ))}
              {regles.length === 0 && (
                <tr><td colSpan={3} style={{ padding: 12, color: "var(--marque-text-muted)" }}>
                  Aucune règle : tout le NAS est au niveau par défaut.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {etat && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
          <input list="nas-dossiers" placeholder={etat.racines[0] ? `${etat.racines[0]}/…` : "Chemin du dossier"}
                 value={chemin} onChange={(e) => setChemin(e.target.value)}
                 style={{ ...champ, flex: "1 1 280px", minWidth: 0 }} />
          <datalist id="nas-dossiers">
            {etat.dossiers.map((d) => <option key={d} value={d} />)}
          </datalist>
          <select value={niveau} onChange={(e) => setNiveau(e.target.value)} style={champ}>
            {etat.echelle.map((n) => <option key={n.cle} value={n.cle}>{n.libelle}</option>)}
          </select>
          <button type="button" className="sym-tap" style={bouton(false)} onClick={ajouter} disabled={!chemin.trim()}>Ajouter</button>
          <button type="button" className="sym-tap" style={bouton(true)} onClick={enregistrer} disabled={enCours || !modifie}>
            {enCours ? "…" : "Enregistrer et reclasser"}
          </button>
        </div>
      )}
      {etat && etat.catalogue !== "pret" && etat.catalogue !== "partiel" && (
        <p style={{ fontSize: 12, color: "var(--marque-text-muted)", margin: "0 0 10px" }}>
          Le catalogue du NAS se construit : la liste des dossiers proposés se remplira dans quelques minutes.
        </p>
      )}

      {etat && (etat.connaissances_documents ?? 0) > 0 && (
        <div style={{ borderTop: "1px solid var(--marque-border)", paddingTop: 12, marginTop: 6 }}>
          <p style={{ fontSize: 13, color: "var(--marque-text-body)", margin: "0 0 8px", maxWidth: 720 }}>
            <b>{etat.connaissances_documents}</b> connaissance(s) viennent déjà d'« Enrichir les documents ». Elles
            gardent le niveau d'avant vos règles : une connaissance ne sait pas de quel fichier précis elle vient.
            Pour qu'elles suivent les nouveaux niveaux, retirez-les et relancez la campagne.
          </p>
          {confirmer ? (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" className="sym-tap" style={bouton(true)} onClick={reprendre} disabled={enCours}>
                Supprimer ces {etat.connaissances_documents} connaissance(s) et relancer
              </button>
              <button type="button" className="sym-tap" style={bouton(false)} onClick={() => setConfirmer(false)}>Annuler</button>
            </div>
          ) : (
            <button type="button" className="sym-tap" style={bouton(false)} onClick={() => setConfirmer(true)} disabled={enCours || modifie}>
              Réécrire les connaissances aux nouveaux niveaux
            </button>
          )}
        </div>
      )}

      {bilan && <p role="status" style={{ fontSize: 13, color: "var(--marque-paid-text)", margin: "12px 0 0" }}>{bilan}</p>}
      {erreur && <p role="status" style={{ fontSize: 13, color: "var(--marque-error-text)", margin: "12px 0 0" }}>{erreur}</p>}
    </div>
  )
}
