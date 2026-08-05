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

  // Tant qu'une synchronisation tourne, on réinterroge. Dès qu'elles sont
  // toutes au repos, on s'arrête : inutile de solliciter le serveur pour rien.
  useEffect(() => {
    if (minuterie.current) clearTimeout(minuterie.current)
    if (etats.some((e) => e.etat === "en_cours")) {
      minuterie.current = setTimeout(charger, 4000)
    }
    return () => { if (minuterie.current) clearTimeout(minuterie.current) }
  }, [etats, charger])

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
