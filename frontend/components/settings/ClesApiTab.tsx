"use client"

import { useCallback, useEffect, useState } from "react"

// Saisie des clés d'API des fournisseurs de modèles, réservée à
// l'administration système. La valeur n'est JAMAIS renvoyée par le serveur :
// on affiche une empreinte (`sk-a…9f2c`), assez pour reconnaître une clé, pas
// pour s'en servir. Le champ est donc toujours vide au chargement — on ne
// pré-remplit pas un secret qu'on ne détient pas.

interface Cle {
  cle: string
  configuree: boolean
  origine: "parametres" | "env" | null
  empreinte: string
}

const LIBELLES: Record<string, { nom: string; role: string }> = {
  longcat_api_key: { nom: "LongCat", role: "Modèle principal pour la rédaction courante" },
  deepseek_api_key: { nom: "DeepSeek", role: "Flash pour l'orientation, Pro pour l'analyse" },
  openrouter_api_key: { nom: "OpenRouter", role: "Passerelle : mêmes modèles, second chemin" },
  groq_api_key: { nom: "Groq", role: "Repli gratuit et rapide" },
  anthropic_api_key: { nom: "Anthropic", role: "Vision et raisonnement (optionnel)" },
  google_api_key: { nom: "Google AI", role: "Embeddings de la mémoire d'entreprise" },
}

// LE MODÈLE FORCÉ EN TÊTE DE CASCADE.
//
// `llm_tete` PRÉFIXE la cascade d'un palier ; le reste demeure derrière, donc
// un essai raté retombe sur le comportement habituel au lieu de casser
// l'application. C'est le réglage le plus expérimental du socle — et c'était
// le plus coûteux à changer : éditer le fichier de configuration de CHAQUE
// serveur, puis recréer le conteneur. Deux clients, deux VPS, deux sessions
// SSH pour un essai qu'on veut pouvoir annuler en dix secondes.
//
// Sa valeur s'AFFICHE, contrairement à une clé : un réglage qu'on ne peut pas
// relire est un réglage qu'on ne peut pas vérifier.
const EXEMPLES: { libelle: string; valeur: string; aide: string }[] = [
  { libelle: "LongCat sur le chat", valeur: "standard=longcat:LongCat-2.0",
    aide: "Rédaction courante uniquement. L'orientation et l'analyse gardent leur cascade." },
  { libelle: "LongCat partout", valeur: "standard=longcat:LongCat-2.0,complex=longcat:LongCat-2.0",
    aide: "Rédaction ET analyse. Plus lent, mais un seul fournisseur en jeu." },
  { libelle: "Groq 70B sur le chat", valeur: "standard=groq:llama-3.3-70b-versatile",
    aide: "Le plus rapide pour la rédaction, quand sa clé est valide." },
]

// LA DATE DE DÉPART DES INDICATEURS.
//
// « Repartir à zéro » sans rien supprimer. Les chiffres du tableau de bord sont
// calculés à la volée depuis l'activité réelle : il n'existe aucun compteur
// qu'on pourrait remettre à zéro, seulement des lignes qu'on peut cesser de
// compter. Une date au lieu d'un DELETE, donc — c'est réversible, et sur un
// serveur en phase de test client c'est la seule option qui ne fasse rien
// perdre.
//
// L'inventaire n'est PAS concerné (documents connus, devis, clients) : il
// décrit ce que l'outil sait aujourd'hui, et le remettre à zéro ferait mentir
// l'écran sur des documents qui existent.
function ReglageKpiDepuis({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [valeur, setValeur] = useState("")
  const [origine, setOrigine] = useState<string | null>(null)
  const [saisie, setSaisie] = useState("")
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState("")
  const [erreur, setErreur] = useState("")

  const charger = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/settings/reglages`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const lignes = await res.json()
      const d = (lignes || []).find((l: any) => l.cle === "kpi_depuis")
      setValeur(d?.valeur || "")
      setOrigine(d?.origine || null)
      setErreur("")
    } catch (e: any) {
      setErreur(e?.message || "chargement impossible")
    }
  }, [apiUrl, backendToken])

  useEffect(() => { charger() }, [charger])

  const enregistrer = async (v: string) => {
    setBusy(true); setNote("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/reglages`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${backendToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ cle: "kpi_depuis", valeur: v }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setSaisie("")
      setNote(v.trim()
        ? "Enregistré. Le tableau de bord ne compte plus rien avant cette date."
        : "Date retirée : les indicateurs comptent de nouveau tout l'historique.")
      setErreur("")
      await charger()
    } catch (e: any) {
      setErreur(e?.message || "enregistrement impossible")
    } finally {
      setBusy(false)
    }
  }

  const aujourdhui = new Date().toISOString().slice(0, 10)

  return (
    <div className="sym-card" style={{
      background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
      borderRadius: "var(--marque-radius-card-sm)", padding: "14px 18px", marginBottom: 22,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
            Indicateurs comptés depuis
          </div>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2 }}>
            Remet le tableau de bord à zéro <b>sans rien supprimer</b> : l&apos;activité
            antérieure reste en base, elle n&apos;est plus comptée. Retirer la date rend
            tout l&apos;historique.
          </div>
        </div>
        <span style={{
          background: valeur ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
          color: valeur ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
          padding: "4px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
          fontWeight: 600, whiteSpace: "nowrap",
        }}>
          {valeur ? `depuis le ${valeur}` : "tout l'historique"}
        </span>
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          type="date" value={saisie} onChange={(e) => setSaisie(e.target.value)}
          style={{
            padding: "8px 12px", fontSize: 13,
            border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)",
            color: "var(--marque-text-body)", background: "var(--marque-surface)", outline: "none",
          }} />
        <button onClick={() => setSaisie(aujourdhui)}
          className="sym-tap" title="Repartir de zéro à partir d'aujourd'hui"
          style={{
            padding: "8px 14px", borderRadius: "var(--marque-radius-pill)",
            border: "1px solid var(--marque-border)", background: "var(--marque-canvas)",
            color: "var(--marque-text-muted)", fontSize: 12.5, cursor: "pointer",
          }}>
          Aujourd&apos;hui
        </button>
        <button onClick={() => enregistrer(saisie)} disabled={busy || !saisie.trim()}
          className="sym-tap" style={{
            padding: "8px 16px", borderRadius: "var(--marque-radius-pill)", border: "none",
            background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
            color: "var(--marque-text-on-dark)", fontSize: 13, fontWeight: 600,
            cursor: "pointer", opacity: saisie.trim() ? 1 : 0.5,
          }}>
          Appliquer
        </button>
        {origine === "parametres" && (
          <button onClick={() => enregistrer("")} disabled={busy}
            className="sym-tap" title="Recompter tout l'historique"
            style={{
              padding: "8px 14px", borderRadius: "var(--marque-radius-pill)",
              border: "1px solid var(--marque-border)", background: "var(--marque-surface)",
              color: "var(--marque-text-body)", fontSize: 13, cursor: "pointer",
            }}>
            Retirer
          </button>
        )}
      </div>

      {note && <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--marque-paid-text)" }}>{note}</div>}
      {erreur && <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--marque-error-text)" }}>⚠ {erreur}</div>}
    </div>
  )
}

function ReglageLlmTete({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [valeur, setValeur] = useState("")
  const [origine, setOrigine] = useState<string | null>(null)
  const [saisie, setSaisie] = useState("")
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState("")
  const [erreur, setErreur] = useState("")

  const charger = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/settings/reglages`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const lignes = await res.json()
      const tete = (lignes || []).find((l: any) => l.cle === "llm_tete")
      setValeur(tete?.valeur || "")
      setOrigine(tete?.origine || null)
      setErreur("")
    } catch (e: any) {
      setErreur(e?.message || "chargement impossible")
    }
  }, [apiUrl, backendToken])

  useEffect(() => { charger() }, [charger])

  const enregistrer = async (v: string) => {
    setBusy(true); setNote("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/reglages`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${backendToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ cle: "llm_tete", valeur: v }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setSaisie("")
      setNote(v.trim()
        ? "Enregistré. Le prochain tour part sur ce modèle, sans redéploiement."
        : "Réglage retiré : la cascade habituelle reprend la main.")
      setErreur("")
      await charger()
    } catch (e: any) {
      setErreur(e?.message || "enregistrement impossible")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="sym-card" style={{
      background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
      borderRadius: "var(--marque-radius-card-sm)", padding: "14px 18px", marginBottom: 22,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
            Modèle en tête de cascade
          </div>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2 }}>
            Force un fournisseur devant la cascade. Le reste demeure derrière : un échec retombe
            sur le comportement habituel.
          </div>
        </div>
        <span style={{
          background: valeur ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
          color: valeur ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
          padding: "4px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
          fontWeight: 600, whiteSpace: "nowrap",
        }}>
          {valeur
            ? `${origine === "parametres" ? "Paramètres" : "fichier serveur"}`
            : "Cascade automatique"}
        </span>
      </div>

      {valeur && (
        <div style={{
          fontFamily: "monospace", fontSize: 12.5, color: "var(--marque-text-body)",
          background: "var(--marque-canvas)", padding: "7px 11px",
          borderRadius: "var(--marque-radius-card-sm)", marginBottom: 10, overflowX: "auto",
        }}>{valeur}</div>
      )}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <input
          type="text" autoComplete="off" spellCheck={false}
          placeholder="palier=fournisseur:modele — ex. standard=longcat:LongCat-2.0"
          value={saisie}
          onChange={(e) => setSaisie(e.target.value)}
          style={{
            flex: 1, minWidth: 240, padding: "8px 12px", fontSize: 13,
            border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)",
            fontFamily: "monospace", color: "var(--marque-text-body)", outline: "none",
          }} />
        <button onClick={() => enregistrer(saisie)} disabled={busy || !saisie.trim()}
          className="sym-tap" style={{
            padding: "8px 16px", borderRadius: "var(--marque-radius-pill)", border: "none",
            background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
            color: "var(--marque-text-on-dark)", fontSize: 13, fontWeight: 600,
            cursor: "pointer", opacity: saisie.trim() ? 1 : 0.5,
          }}>
          Appliquer
        </button>
        {origine === "parametres" && (
          <button onClick={() => enregistrer("")} disabled={busy}
            className="sym-tap" title="Revenir à la cascade automatique"
            style={{
              padding: "8px 14px", borderRadius: "var(--marque-radius-pill)",
              border: "1px solid var(--marque-border)", background: "var(--marque-surface)",
              color: "var(--marque-text-body)", fontSize: 13, cursor: "pointer",
            }}>
            Retirer
          </button>
        )}
      </div>

      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {EXEMPLES.map((ex) => (
          <button key={ex.valeur} onClick={() => setSaisie(ex.valeur)} title={ex.aide}
            className="sym-tap" style={{
              padding: "5px 11px", borderRadius: "var(--marque-radius-pill)",
              border: "1px solid var(--marque-border)", background: "var(--marque-canvas)",
              color: "var(--marque-text-muted)", fontSize: 12, cursor: "pointer",
            }}>
            {ex.libelle}
          </button>
        ))}
      </div>

      {note && <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--marque-paid-text)" }}>{note}</div>}
      {erreur && <div style={{ marginTop: 10, fontSize: 12.5, color: "var(--marque-error-text)" }}>⚠ {erreur}</div>}
    </div>
  )
}

export default function ClesApiTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [cles, setCles] = useState<Cle[]>([])
  const [saisies, setSaisies] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState("")
  const [message, setMessage] = useState("")
  const [erreur, setErreur] = useState("")

  const charger = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/settings/cles-api`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setCles(await res.json())
      setErreur("")
    } catch (e: any) {
      setErreur(e?.message || "chargement impossible")
    }
  }, [apiUrl, backendToken])

  useEffect(() => { charger() }, [charger])

  const enregistrer = async (cle: string, effacer = false) => {
    setBusy(cle)
    setMessage("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/cles-api`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${backendToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ cle, valeur: effacer ? "" : (saisies[cle] || "") }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setSaisies((s) => ({ ...s, [cle]: "" }))
      setMessage(effacer
        ? `${LIBELLES[cle]?.nom || cle} : retour à la valeur du fichier de configuration.`
        : `${LIBELLES[cle]?.nom || cle} enregistrée. Prise en compte immédiate.`)
      setErreur("")
      await charger()
    } catch (e: any) {
      setErreur(e?.message || "enregistrement impossible")
    } finally {
      setBusy("")
    }
  }

  return (
    <div>
      <ReglageKpiDepuis apiUrl={apiUrl} backendToken={backendToken} />
      <ReglageLlmTete apiUrl={apiUrl} backendToken={backendToken} />

      <p style={{ margin: "0 0 6px", fontSize: 14, color: "var(--marque-text-body)",
                  maxWidth: "72ch", lineHeight: 1.55 }}>
        Ces clés déterminent quels modèles répondent. Une clé saisie ici <b>prend effet
        immédiatement</b>, sans redéploiement, et prime sur le fichier de configuration
        du serveur.
      </p>
      <p style={{ margin: "0 0 20px", fontSize: 13, color: "var(--marque-text-muted)",
                  maxWidth: "72ch", lineHeight: 1.5 }}>
        Le serveur ne renvoie jamais une clé : seule une empreinte est affichée. Les champs
        restent donc vides, et laisser un champ vide ne supprime rien.
      </p>

      {erreur && <div className="sym-pop" style={{ color: "var(--marque-error-text)",
                                                   fontSize: 13, marginBottom: 12 }}>⚠ {erreur}</div>}
      {message && <div className="sym-pop" style={{ color: "var(--marque-paid-text)",
                                                    fontSize: 13, marginBottom: 12 }}>{message}</div>}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {cles.map((c) => {
          const info = LIBELLES[c.cle] || { nom: c.cle, role: "" }
          return (
            <div key={c.cle} className="sym-card" style={{
              background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
              borderRadius: "var(--marque-radius-card-sm)", padding: "14px 18px",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
                            marginBottom: 10 }}>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <div style={{ fontSize: 14, fontWeight: 700,
                                color: "var(--marque-text-primary)" }}>{info.nom}</div>
                  <div style={{ fontSize: 12, color: "var(--marque-text-muted)",
                                marginTop: 2 }}>{info.role}</div>
                </div>
                <span style={{
                  background: c.configuree ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
                  color: c.configuree ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
                  padding: "4px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
                  fontWeight: 600, whiteSpace: "nowrap",
                }}>
                  {c.configuree
                    ? `${c.empreinte} · ${c.origine === "parametres" ? "Paramètres" : "fichier serveur"}`
                    : "Non configurée"}
                </span>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input
                  type="password" autoComplete="off" placeholder="Coller la nouvelle clé…"
                  value={saisies[c.cle] || ""}
                  onChange={(e) => setSaisies((s) => ({ ...s, [c.cle]: e.target.value }))}
                  style={{
                    flex: 1, minWidth: 200, padding: "8px 12px", fontSize: 13,
                    border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-pill)",
                    fontFamily: "monospace", color: "var(--marque-text-body)", outline: "none",
                  }} />
                <button onClick={() => enregistrer(c.cle)}
                  disabled={busy === c.cle || !(saisies[c.cle] || "").trim()}
                  className="sym-tap" style={{
                    padding: "8px 16px", borderRadius: "var(--marque-radius-pill)", border: "none",
                    background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
                    color: "var(--marque-text-on-dark)", fontSize: 13, fontWeight: 600,
                    cursor: "pointer", opacity: (saisies[c.cle] || "").trim() ? 1 : 0.5,
                  }}>
                  Enregistrer
                </button>
                {c.origine === "parametres" && (
                  <button onClick={() => enregistrer(c.cle, true)} disabled={busy === c.cle}
                    className="sym-tap" title="Revenir à la valeur du fichier de configuration"
                    style={{
                      padding: "8px 14px", borderRadius: "var(--marque-radius-pill)",
                      border: "1px solid var(--marque-border)", background: "var(--marque-surface)",
                      color: "var(--marque-text-body)", fontSize: 13, cursor: "pointer",
                    }}>
                    Réinitialiser
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
