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
  etat: "jamais" | "en_cours" | "terminee" | "echec" | "non_configure" | "interrompue"
  debut?: string | number
  fin?: string | number
  par?: string
  resultat?: Record<string, any> | null
  erreur?: string | null
  etape?: string | null
  traites?: number
  total?: number | null
  pourcentage?: number | null
  derniere_reussite?: string | null
}

// LA DATE SE FORME CÔTÉ NAVIGATEUR, JAMAIS AU RENDU SERVEUR. Le conteneur
// tourne en UTC, le navigateur est à Paris : un `toLocaleString` appelé pendant
// le rendu produit deux textes différents des deux côtés, et React rend une
// erreur d'hydratation — exactement les trois erreurs vues en production. D'où
// le fuseau FIGÉ et l'appel depuis un état, pas depuis le corps du composant.
function quand(iso?: string | number | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: "Europe/Paris", hour: "2-digit", minute: "2-digit",
  }
  const auj = new Date()
  const jour = (x: Date) => x.toLocaleDateString("fr-FR", { timeZone: "Europe/Paris" })
  const hier = new Date(auj.getTime() - 86400000)
  if (jour(d) === jour(auj)) return `aujourd'hui à ${d.toLocaleTimeString("fr-FR", opts)}`
  if (jour(d) === jour(hier)) return `hier à ${d.toLocaleTimeString("fr-FR", opts)}`
  return `le ${d.toLocaleDateString("fr-FR", { timeZone: "Europe/Paris", day: "numeric", month: "long" })} à ${d.toLocaleTimeString("fr-FR", opts)}`
}

function duree(debut?: string | number | null, fin?: string | number | null): string {
  if (!debut) return ""
  const a = new Date(debut).getTime()
  const b = fin ? new Date(fin).getTime() : Date.now()
  const s = Math.max(0, Math.round((b - a) / 1000))
  if (s < 60) return `${s} s`
  if (s < 3600) return `${Math.floor(s / 60)} min`
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
}

const ETIQUETTE: Record<string, { texte: string; bg: string; fg: string }> = {
  jamais: { texte: "Jamais lancée", bg: "var(--marque-canvas)", fg: "var(--marque-text-muted)" },
  en_cours: { texte: "En cours…", bg: "var(--marque-progress-bg)", fg: "var(--marque-progress-text)" },
  terminee: { texte: "Terminée", bg: "var(--marque-paid-bg)", fg: "var(--marque-paid-text)" },
  echec: { texte: "Échec", bg: "var(--marque-error-bg)", fg: "var(--marque-error-text)" },
  non_configure: { texte: "Non configuré", bg: "var(--marque-pending-bg)", fg: "var(--marque-pending-text)" },
  // « Interrompue » est un état HONNÊTE : le serveur a redémarré pendant la
  // synchronisation. Le laisser en « en cours » afficherait une barre figée
  // pour toujours ; le passer en « échec » accuserait le connecteur à tort.
  interrompue: { texte: "Interrompue", bg: "var(--marque-pending-bg)", fg: "var(--marque-pending-text)" },
  // « Partielle » : le connecteur s'est arrêté avant la fin (Drive : trop de
  // documents lents) et le dit. Afficher « Terminée » là-dessus a caché
  // pendant des semaines une synchro qui n'avançait plus (31/08).
  partielle: { texte: "Partielle", bg: "var(--marque-pending-bg)", fg: "var(--marque-pending-text)" },
}

export default function SyncTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [etats, setEtats] = useState<EtatSync[]>([])
  const [erreur, setErreur] = useState("")
  const [busy, setBusy] = useState("")
  const minuterie = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [chargement, setChargement] = useState(true)
  const tentatives = useRef(0)
  // La liste des connecteurs venait d'UN seul appel, sans indicateur ni
  // nouvelle tentative : quand le backend était occupé (une campagne et une
  // synchro de 438 fichiers en même temps), l'onglet montrait les cartes
  // d'enrichissement et RIEN à la place des connecteurs (Noa, 31/08).
  // Désormais : « chargement… » tant qu'on ne sait pas, et jusqu'à trois
  // nouvelles tentatives espacées avant d'afficher l'erreur.
  const charger = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/ingestion/sync`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setEtats(await res.json())
      setErreur("")
      setChargement(false)
      tentatives.current = 0
    } catch (e: any) {
      if (tentatives.current < 3) {
        tentatives.current += 1
        setTimeout(() => { charger().catch(() => { /* la tentative suivante dira */ }) },
                   3000 * tentatives.current)
        return
      }
      setChargement(false)
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

  // ── Enrichissement DOCUMENTAIRE ───────────────────────────────────
  // Le pendant de « Tout enrichir » pour les documents déjà ingérés du socle
  // (lecture seule : rien n'est retéléchargé). Chaque connaissance hérite du
  // niveau de confidentialité RÉEL de son fichier d'origine — lu dans les
  // partages, pas dans un réglage global.

  const [enrichDocs, setEnrichDocs] = useState<any>(null)

  const chargerEnrichDocs = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/learning/enrichir-documents/statut`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (res.ok) setEnrichDocs(await res.json())
    } catch { /* l'état d'une campagne n'est pas critique */ }
  }, [apiUrl, backendToken])

  useEffect(() => { chargerEnrichDocs() }, [chargerEnrichDocs])
  useEffect(() => {
    if (!enrichDocs?.en_cours) return
    const id = setInterval(chargerEnrichDocs, 5000)
    return () => clearInterval(id)
  }, [enrichDocs?.en_cours, chargerEnrichDocs])

  const lancerEnrichDocs = async () => {
    setBusy("enrichir-docs")
    try {
      const res = await fetch(`${apiUrl}/api/learning/enrichir-documents`, {
        method: "POST",
        headers: { Authorization: `Bearer ${backendToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ max_lots_par_niveau: 30, exiger_modele_principal: true }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setErreur("")
      await chargerEnrichDocs()
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
    } catch (e: any) {
      setErreur(e?.message || "lancement impossible")
    } finally {
      // LE BOUTON SE LIBÈRE AVANT LE RECHARGEMENT, et c'est tout le sujet.
      // `charger()` était appelé DANS le `try`, avant ce `finally` : le jour
      // où le backend s'est gelé, il n'est jamais revenu, le `finally` n'a
      // jamais été atteint, et le bouton est resté grisé indéfiniment. La
      // personne a cru que rien ne s'était lancé — alors que la
      // synchronisation tournait.
      setBusy("")
    }
    // Hors du try/finally : si celui-ci échoue, le bouton est déjà rendu.
    charger().catch(() => { /* l'état se rattrapera au sondage suivant */ })
  }

  const resume = (e: EtatSync) => {
    if (e.etat === "echec" || e.etat === "non_configure" || e.etat === "partielle") return e.erreur || ""
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
      <p style={{ margin: "0 0 18px", fontSize: 14, color: "var(--marque-text-body)",
                  maxWidth: "72ch", lineHeight: 1.55 }}>
        Chaque synchronisation va chercher les données à la source et les range dans la
        mémoire d'entreprise. Elle tourne <b>en tâche de fond</b> : vous pouvez quitter
        cette page. Les messages déjà connus sont mis à jour, jamais dupliqués, donc
        relancer est sans risque.
      </p>

      {erreur && (
        <div className="sym-pop" style={{ color: "var(--marque-error-text)", fontSize: 13,
                                          marginBottom: 12 }}>⚠ {erreur}</div>
      )}

      {/* Enrichissement complet — un seul geste, des paramètres fixes */}
      <div className="sym-card" style={{
        background: "var(--marque-surface)", border: "2px solid var(--marque-primary)",
        borderRadius: "var(--marque-radius-card-sm)", padding: "16px 18px", marginBottom: 18,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
              Tout enrichir
            </div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 3,
                          lineHeight: 1.5 }}>
              Synchronise les boîtes, extrait tout le courrier, construit un profil
              d'écriture par personne, puis en tire connaissances, manières de faire et
              brouillons de skills. Plusieurs heures.
            </div>
          </div>
          <span style={{
            background: enrich?.en_cours ? "var(--marque-progress-bg)" : "var(--marque-canvas)",
            color: enrich?.en_cours ? "var(--marque-progress-text)" : "var(--marque-text-muted)",
            padding: "5px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
            fontWeight: 600, whiteSpace: "nowrap",
          }}>
            {enrich?.en_cours ? "En cours…" : (enrich?.phase || "Jamais lancée")}
          </span>
          <button onClick={lancerEnrich} disabled={!!enrich?.en_cours || busy === "enrichir"}
            className="sym-tap" style={{
              padding: "9px 18px", borderRadius: "var(--marque-radius-pill)", border: "none",
              background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
              color: "var(--marque-text-on-dark)", fontSize: 13, fontWeight: 700,
              cursor: enrich?.en_cours ? "not-allowed" : "pointer",
              opacity: enrich?.en_cours || busy === "enrichir" ? 0.6 : 1,
            }}>
            {enrich?.en_cours ? "En cours…" : "Tout enrichir"}
          </button>
        </div>
        {enrich && (enrich.messages_extraits || enrich.appels_analyse) ? (
          <div style={{ fontSize: 12, color: "var(--marque-text-body)", marginTop: 10,
                        paddingTop: 10, borderTop: "1px solid var(--marque-border)" }}>
            {enrich.messages_extraits} message(s) extrait(s) · {enrich.appels_analyse} appel(s)
            d'analyse · {enrich.connaissances} connaissance(s) · {enrich.procedures} manière(s)
            de faire · {(enrich.skills || []).length} skill(s)
            {enrich.boite_courante ? ` · en cours : ${enrich.boite_courante}` : ""}
            {(enrich.echecs || []).length ? ` · ${enrich.echecs.length} échec(s)` : ""}
          </div>
        ) : null}
      </div>

      {/* Enrichissement documentaire — le savoir des fichiers, au bon niveau */}
      <div className="sym-card" style={{
        background: "var(--marque-surface)", border: "2px solid var(--marque-primary)",
        borderRadius: "var(--marque-radius-card-sm)", padding: "16px 18px", marginBottom: 18,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
              Enrichir les documents
            </div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 3,
                          lineHeight: 1.5 }}>
              Relit tous les documents déjà ingérés du socle documentaire (lecture seule) et en tire
              connaissances et manières de faire. Chaque connaissance hérite du niveau de
              confidentialité réel de son fichier : qui peut ouvrir le fichier peut la
              lire, personne d'autre. Plusieurs heures.
            </div>
          </div>
          <span style={{
            background: enrichDocs?.en_cours ? "var(--marque-progress-bg)" : "var(--marque-canvas)",
            color: enrichDocs?.en_cours ? "var(--marque-progress-text)" : "var(--marque-text-muted)",
            padding: "5px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
            fontWeight: 600, whiteSpace: "nowrap", maxWidth: 260, overflow: "hidden",
            textOverflow: "ellipsis",
          }}>
            {enrichDocs?.en_cours ? "En cours…" : (enrichDocs?.phase || "Jamais lancée")}
          </span>
          <button onClick={lancerEnrichDocs}
            disabled={!!enrichDocs?.en_cours || busy === "enrichir-docs"}
            className="sym-tap" style={{
              padding: "9px 18px", borderRadius: "var(--marque-radius-pill)", border: "none",
              background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
              color: "var(--marque-text-on-dark)", fontSize: 13, fontWeight: 700,
              cursor: enrichDocs?.en_cours ? "not-allowed" : "pointer",
              opacity: enrichDocs?.en_cours || busy === "enrichir-docs" ? 0.6 : 1,
            }}>
            {enrichDocs?.en_cours ? "En cours…" : "Enrichir les documents"}
          </button>
        </div>
        {enrichDocs && (enrichDocs.documents || enrichDocs.appels_analyse) ? (
          <div style={{ fontSize: 12, color: "var(--marque-text-body)", marginTop: 10,
                        paddingTop: 10, borderTop: "1px solid var(--marque-border)" }}>
            {enrichDocs.documents} document(s) ·
            {" "}{Object.entries(enrichDocs.groupes || {}).map(([n, c]) => `${c} en ${n}`).join(", ") || "classement en cours"} ·
            {" "}{enrichDocs.appels_analyse} appel(s) · {enrichDocs.connaissances} connaissance(s)
            · {enrichDocs.procedures} manière(s) de faire
            {(enrichDocs.echecs || []).length ? ` · ${enrichDocs.echecs.length} échec(s)` : ""}
          </div>
        ) : null}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {chargement && etats.length === 0 && !erreur && (
        <div style={{ fontSize: 13, color: "var(--marque-text-muted)", padding: "10px 0" }}>
          Chargement des connecteurs…
        </div>
      )}
      {etats.map((e) => {
          const et = ETIQUETTE[e.etat] || ETIQUETTE.jamais
          const enCours = e.etat === "en_cours"
          return (
            <div key={e.source} className="sym-card" style={{
              background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
              borderRadius: "var(--marque-radius-card-sm)", padding: "14px 18px",
              display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
            }}>
              <div style={{ flex: 1, minWidth: 200 }}>
                <div style={{ fontSize: 14, fontWeight: 700,
                              color: "var(--marque-text-primary)" }}>{e.libelle}</div>
                <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 3 }}>
                  {enCours
                    ? `${e.etape || "en cours"} · depuis ${duree(e.debut)}`
                    : (resume(e) || "Aucune donnée pour l'instant")}
                  {!enCours && e.fin ? ` · ${quand(e.fin)}` : ""}
                  {e.par ? ` · par ${e.par}` : ""}
                </div>
                {/* LA DERNIÈRE RÉUSSITE SURVIT À UN ÉCHEC. C'est ce que le
                    gérant veut savoir : « quand ai-je eu des données à jour ? »
                    Un échec d'aujourd'hui ne doit pas effacer cette réponse. */}
                {!enCours && e.derniere_reussite && e.etat !== "terminee" ? (
                  <div style={{ fontSize: 11, color: "var(--marque-text-muted)",
                                marginTop: 2, opacity: 0.85 }}>
                    Dernière réussite {quand(e.derniere_reussite)}
                  </div>
                ) : null}
                {enCours ? (
                  <div style={{ marginTop: 8 }}>
                    {/* BARRE DÉTERMINÉE si le total est connu, INDÉTERMINÉE
                        sinon. Le Drive connaît son total, Extrabat jamais :
                        afficher « 40 % » sans le savoir serait un mensonge que
                        personne ne peut vérifier. */}
                    <div style={{ height: 4, borderRadius: 999, overflow: "hidden",
                                  background: "var(--marque-canvas)" }}>
                      <div style={{
                        height: "100%", borderRadius: 999,
                        background: "var(--marque-primary)",
                        width: e.pourcentage != null ? `${e.pourcentage}%` : "35%",
                        transition: "width .4s ease",
                        animation: e.pourcentage == null
                          ? "sym-sync-glisse 1.4s ease-in-out infinite" : undefined,
                      }} />
                    </div>
                    <div style={{ fontSize: 11, color: "var(--marque-text-muted)",
                                  marginTop: 4 }}>
                      {e.pourcentage != null
                        ? `${e.traites} sur ${e.total} · ${e.pourcentage} %`
                        : `${e.traites ?? 0} traité(s)`}
                    </div>
                  </div>
                ) : null}
              </div>
              <span style={{ background: et.bg, color: et.fg, padding: "5px 12px",
                             borderRadius: "var(--marque-radius-pill)", fontSize: 12,
                             fontWeight: 600, whiteSpace: "nowrap" }}>{et.texte}</span>
              <button onClick={() => lancer(e.source)} disabled={enCours || busy === e.source}
                className="sym-tap" style={{
                  padding: "8px 16px", borderRadius: "var(--marque-radius-pill)", border: "none",
                  background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
                  color: "var(--marque-text-on-dark)", fontSize: 13, fontWeight: 600,
                  cursor: enCours ? "not-allowed" : "pointer",
                  opacity: enCours || busy === e.source ? 0.6 : 1,
                }}>
                {enCours ? "En cours…" : "Synchroniser"}
              </button>
            </div>
          )
        })}
      </div>

      <style>{`
        /* Barre INDÉTERMINÉE : elle glisse au lieu d'afficher un pourcentage
           inventé. Un connecteur qui ne sait pas compter à l'avance ne doit pas
           faire semblant — mais l'écran doit quand même montrer que ça vit. */
        @keyframes sym-sync-glisse {
          0%   { margin-left: 0;   opacity: .55 }
          50%  { margin-left: 65%; opacity: 1 }
          100% { margin-left: 0;   opacity: .55 }
        }
        @media (prefers-reduced-motion: reduce) {
          [style*="sym-sync-glisse"] { animation: none !important; opacity: .8 }
        }
      `}</style>
    </div>
  )
}
