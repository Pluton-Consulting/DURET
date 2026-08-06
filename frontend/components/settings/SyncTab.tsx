"use client"

import { useCallback, useEffect, useRef, useState } from "react"

// Déclenchement des synchronisations depuis l'interface, réservé à
// l'administration système. Le backend les exécute en TÂCHE DE FOND : parcourir
// plusieurs boîtes prend des minutes, et une requête HTTP expirerait avant la
// fin. On lance, puis on interroge l'état — d'où le rafraîchissement
// automatique tant qu'une synchronisation tourne.

interface EtatSync {
  source: string
  libelle: string
  etat: "jamais" | "en_cours" | "terminee" | "echec" | "non_configure"
  debut?: number
  fin?: number
  par?: string
  resultat?: Record<string, any> | null
  erreur?: string | null
}

const ETIQUETTE: Record<string, { texte: string; bg: string; fg: string }> = {
  jamais: { texte: "Jamais lancée", bg: "var(--color-canvas)", fg: "var(--color-text-muted)" },
  en_cours: { texte: "En cours…", bg: "var(--color-progress-bg)", fg: "var(--color-progress-text)" },
  terminee: { texte: "Terminée", bg: "var(--color-paid-bg)", fg: "var(--color-paid-text)" },
  echec: { texte: "Échec", bg: "var(--color-error-bg)", fg: "var(--color-error-text)" },
  non_configure: { texte: "Non configuré", bg: "var(--color-pending-bg)", fg: "var(--color-pending-text)" },
}

export default function SyncTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [etats, setEtats] = useState<EtatSync[]>([])
  const [erreur, setErreur] = useState("")
  const [busy, setBusy] = useState("")
  const minuterie = useRef<ReturnType<typeof setTimeout> | null>(null)

  const charger = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/ingestion/sync`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setEtats(await res.json())
      setErreur("")
    } catch (e: any) {
      setErreur(e?.message || "état indisponible")
    }
  }, [apiUrl, backendToken])

  useEffect(() => { charger() }, [charger])

  // ── Enrichissement ────────────────────────────────────────────────
  // Un seul bouton, des paramètres FIXES : toutes les boîtes, tout le corpus,
  // modèle principal exigé. Rien n'est laissé au jugement du modèle — c'est
  // précisément ce qu'on veut d'un traitement de fond déclenché à la main.

  const [enrich, setEnrich] = useState<any>(null)

  const chargerEnrich = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/learning/enrichir/statut`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (res.ok) setEnrich(await res.json())
    } catch { /* l'état d'une campagne n'est pas critique */ }
  }, [apiUrl, backendToken])

  useEffect(() => { chargerEnrich() }, [chargerEnrich])

  const lancerEnrich = async () => {
    setBusy("enrichir")
    try {
      const res = await fetch(`${apiUrl}/api/learning/enrichir`, {
        method: "POST",
        headers: { Authorization: `Bearer ${backendToken}`, "Content-Type": "application/json" },
        // Paramètres déterministes : on ne demande pas au modèle de choisir.
        body: JSON.stringify({
          collecter: true, max_lots_par_boite: 20,
          exiger_modele_principal: true, acces_skills: "all",
        }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setErreur("")
      await chargerEnrich()
    } catch (e: any) {
      setErreur(e?.message || "lancement impossible")
    } finally {
      setBusy("")
    }
  }

  // Tant qu'une synchronisation tourne, on réinterroge. Dès qu'elles sont
  // toutes au repos, on s'arrête : inutile de solliciter le serveur pour rien.
  useEffect(() => {
    if (minuterie.current) clearTimeout(minuterie.current)
    if (etats.some((e) => e.etat === "en_cours") || enrich?.en_cours) {
      minuterie.current = setTimeout(() => { charger(); chargerEnrich() }, 4000)
    }
    return () => { if (minuterie.current) clearTimeout(minuterie.current) }
  }, [etats, enrich, charger, chargerEnrich])

  const lancer = async (source: string) => {
    setBusy(source)
    try {
      const res = await fetch(`${apiUrl}/api/ingestion/sync/${source}`, {
        method: "POST", headers: { Authorization: `Bearer ${backendToken}` },
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setErreur("")
      await charger()
    } catch (e: any) {
      setErreur(e?.message || "lancement impossible")
    } finally {
      setBusy("")
    }
  }

  const resume = (e: EtatSync) => {
    if (e.etat === "echec" || e.etat === "non_configure") return e.erreur || ""
    if (!e.resultat) return ""
    // Le bilan d'un connecteur est un petit dictionnaire de compteurs : on le
    // rend lisible sans présumer de ses clés, qui diffèrent d'un connecteur à
    // l'autre (boîtes, reçus, envoyés, fichiers…).
    return Object.entries(e.resultat)
      .filter(([, v]) => typeof v === "number" || typeof v === "string")
      .map(([k, v]) => `${v} ${k}`)
      .join(" · ")
  }

  return (
    <div>
      <p style={{ margin: "0 0 18px", fontSize: 14, color: "var(--color-text-body)",
                  maxWidth: "72ch", lineHeight: 1.55 }}>
        Chaque synchronisation va chercher les données à la source et les range dans la
        mémoire d'entreprise. Elle tourne <b>en tâche de fond</b> : vous pouvez quitter
        cette page. Les messages déjà connus sont mis à jour, jamais dupliqués, donc
        relancer est sans risque.
      </p>

      {erreur && (
        <div className="sym-pop" style={{ color: "var(--color-error-text)", fontSize: 13,
                                          marginBottom: 12 }}>⚠ {erreur}</div>
      )}

      {/* Enrichissement complet — un seul geste, des paramètres fixes */}
      <div className="sym-card" style={{
        background: "var(--color-surface)", border: "2px solid var(--color-primary)",
        borderRadius: "var(--radius-card-sm)", padding: "16px 18px", marginBottom: 18,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>
              Tout enrichir
            </div>
            <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3,
                          lineHeight: 1.5 }}>
              Synchronise les boîtes, extrait tout le courrier, construit un profil
              d'écriture par personne, puis en tire connaissances, manières de faire et
              brouillons de skills. Plusieurs heures.
            </div>
          </div>
          <span style={{
            background: enrich?.en_cours ? "var(--color-progress-bg)" : "var(--color-canvas)",
            color: enrich?.en_cours ? "var(--color-progress-text)" : "var(--color-text-muted)",
            padding: "5px 12px", borderRadius: "var(--radius-pill)", fontSize: 12,
            fontWeight: 600, whiteSpace: "nowrap",
          }}>
            {enrich?.en_cours ? "En cours…" : (enrich?.phase || "Jamais lancée")}
          </span>
          <button onClick={lancerEnrich} disabled={!!enrich?.en_cours || busy === "enrichir"}
            className="sym-tap" style={{
              padding: "9px 18px", borderRadius: "var(--radius-pill)", border: "none",
              background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
              color: "var(--color-text-on-dark)", fontSize: 13, fontWeight: 700,
              cursor: enrich?.en_cours ? "not-allowed" : "pointer",
              opacity: enrich?.en_cours || busy === "enrichir" ? 0.6 : 1,
            }}>
            {enrich?.en_cours ? "En cours…" : "Tout enrichir"}
          </button>
        </div>
        {enrich && (enrich.messages_extraits || enrich.appels_analyse) ? (
          <div style={{ fontSize: 12, color: "var(--color-text-body)", marginTop: 10,
                        paddingTop: 10, borderTop: "1px solid var(--color-border)" }}>
            {enrich.messages_extraits} message(s) extrait(s) · {enrich.appels_analyse} appel(s)
            d'analyse · {enrich.connaissances} connaissance(s) · {enrich.procedures} manière(s)
            de faire · {(enrich.skills || []).length} skill(s)
            {enrich.boite_courante ? ` · en cours : ${enrich.boite_courante}` : ""}
            {(enrich.echecs || []).length ? ` · ${enrich.echecs.length} échec(s)` : ""}
          </div>
        ) : null}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {etats.map((e) => {
          const et = ETIQUETTE[e.etat] || ETIQUETTE.jamais
          const enCours = e.etat === "en_cours"
          return (
            <div key={e.source} className="sym-card" style={{
              background: "var(--color-surface)", border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-card-sm)", padding: "14px 18px",
              display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
            }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 14, fontWeight: 700,
                              color: "var(--color-text-primary)" }}>{e.libelle}</div>
                <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 3 }}>
                  {resume(e) || "Aucune donnée pour l'instant"}
                  {e.par ? ` · lancée par ${e.par}` : ""}
                </div>
              </div>
              <span style={{ background: et.bg, color: et.fg, padding: "5px 12px",
                             borderRadius: "var(--radius-pill)", fontSize: 12,
                             fontWeight: 600, whiteSpace: "nowrap" }}>{et.texte}</span>
              <button onClick={() => lancer(e.source)} disabled={enCours || busy === e.source}
                className="sym-tap" style={{
                  padding: "8px 16px", borderRadius: "var(--radius-pill)", border: "none",
                  background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
                  color: "var(--color-text-on-dark)", fontSize: 13, fontWeight: 600,
                  cursor: enCours ? "not-allowed" : "pointer",
                  opacity: enCours || busy === e.source ? 0.6 : 1,
                }}>
                {enCours ? "En cours…" : "Synchroniser"}
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
