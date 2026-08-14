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
