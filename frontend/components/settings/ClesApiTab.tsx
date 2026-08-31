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

// LE MODÈLE DE L'ASSISTANT — UN SEUL, PARTOUT.
//
// Demande de Noa du 31/08 : « une seule clé, un seul modèle, le même partout —
// pas vingt mille modèles différents à chaque endroit ». Avant, le forçage se
// réglait PAR PALIER (« standard=…, complex=…, light=… ») avec des préréglages :
// juste, mais illisible pour qui n'a pas la cascade en tête. Ici : un
// fournisseur (parmi ceux dont la clé est présente), un modèle, un bouton.
// Le réglage `modele_unique` met ce couple en tête des TROIS paliers ET des
// campagnes d'enrichissement ; la cascade reste derrière en secours. La
// vision, les images et les embeddings gardent leur modèle dédié : un modèle
// de texte ne lit pas un plan.
//
// Le forçage par palier (`llm_tete`) existe toujours pour le fichier de
// configuration ; s'il est posé en base, la carte le montre et permet de le
// retirer — un réglage invisible est un réglage qu'on ne peut pas vérifier.
interface FicheFournisseur {
  fournisseur: string
  libelle: string
  cle_presente: boolean
  modeles: { id: string; ecarte: boolean; raison: string }[]
}

function ReglageModeleUnique({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [fiches, setFiches] = useState<FicheFournisseur[]>([])
  const [actuel, setActuel] = useState("")
  const [avance, setAvance] = useState("")
  const [fournisseur, setFournisseur] = useState("")
  const [modele, setModele] = useState("")
  const [autre, setAutre] = useState("")
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState("")
  const [erreur, setErreur] = useState("")

  const charger = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/settings/modeles`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      const liste: FicheFournisseur[] = json?.fournisseurs || []
      setFiches(liste)
      setActuel(json?.modele_unique || "")
      setAvance(json?.llm_tete || "")
      const [f, m] = String(json?.modele_unique || "").split(":")
      const premier = liste.find((x) => x.cle_presente)
      const fChoisi = f || premier?.fournisseur || ""
      setFournisseur(fChoisi)
      const fiche = liste.find((x) => x.fournisseur === fChoisi)
      setModele(m || fiche?.modeles[0]?.id || "")
      setErreur("")
    } catch (e: any) {
      setErreur(e?.message || "chargement impossible")
    }
  }, [apiUrl, backendToken])
  useEffect(() => { charger() }, [charger])

  const ecrire = async (cle: string, valeur: string, message: string) => {
    setBusy(true); setNote("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/reglages`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${backendToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ cle, valeur }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setNote(message)
      setErreur("")
      await charger()
    } catch (e: any) {
      setErreur(e?.message || "enregistrement impossible")
    } finally {
      setBusy(false)
    }
  }

  const fiche = fiches.find((x) => x.fournisseur === fournisseur)
  const choisi = `${fournisseur}:${(autre.trim() || modele).trim()}`
  const pret = Boolean(fournisseur && (autre.trim() || modele) && fiche?.cle_presente)

  return (
    <div className="sym-card" style={{
      background: "var(--marque-surface)", border: "2px solid var(--marque-primary)",
      borderRadius: "var(--marque-radius-card-sm)", padding: "16px 18px", marginBottom: 22,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
            Le modèle de l&apos;assistant
          </div>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 3, lineHeight: 1.5 }}>
            Un seul modèle pour tout ce qui écrit : le chat, la rédaction, l&apos;enrichissement.
            S&apos;il ne répond pas, la cascade prend le relais. La vision (plans, photos), les
            images et les embeddings gardent leur modèle dédié.
          </div>
        </div>
        <span style={{
          background: actuel ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
          color: actuel ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
          padding: "5px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
          fontWeight: 600, whiteSpace: "nowrap",
        }}>
          {actuel || "cascade automatique"}
        </span>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12, alignItems: "center" }}>
        <select value={fournisseur} disabled={busy}
          onChange={(e) => {
            const f = e.target.value
            setFournisseur(f)
            setModele(fiches.find((x) => x.fournisseur === f)?.modeles[0]?.id || "")
            setAutre("")
          }}
          style={{ padding: "8px 10px", borderRadius: "var(--marque-radius-pill)",
                   border: "1px solid var(--marque-border)", fontSize: 13, minWidth: 190 }}>
          {fiches.length === 0 && <option value="">chargement…</option>}
          {fiches.map((f) => (
            <option key={f.fournisseur} value={f.fournisseur} disabled={!f.cle_presente}>
              {f.libelle}{f.cle_presente ? "" : " — clé absente"}
            </option>
          ))}
        </select>
        <select value={modele} disabled={busy || !fiche} onChange={(e) => { setModele(e.target.value); setAutre("") }}
          style={{ padding: "8px 10px", borderRadius: "var(--marque-radius-pill)",
                   border: "1px solid var(--marque-border)", fontSize: 13, minWidth: 240 }}>
          {(fiche?.modeles || []).map((m) => (
            <option key={m.id} value={m.id}>
              {m.id}{m.ecarte ? ` — écarté (${m.raison})` : ""}
            </option>
          ))}
        </select>
        <input value={autre} disabled={busy} onChange={(e) => setAutre(e.target.value)}
          placeholder="ou un autre identifiant de modèle"
          style={{ padding: "8px 10px", borderRadius: "var(--marque-radius-pill)",
                   border: "1px solid var(--marque-border)", fontSize: 13, minWidth: 220 }} />
        <button onClick={() => ecrire("modele_unique", choisi,
                                      `${choisi} est maintenant le modèle de tout ce qui écrit. Effet immédiat.`)}
          disabled={busy || !pret || choisi === actuel} className="sym-tap" style={{
            padding: "9px 18px", borderRadius: "var(--marque-radius-pill)", border: "none",
            background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
            color: "var(--marque-text-on-dark)", fontSize: 13, fontWeight: 700,
            cursor: busy || !pret || choisi === actuel ? "not-allowed" : "pointer",
            opacity: busy || !pret || choisi === actuel ? 0.6 : 1,
          }}>
          Utiliser partout
        </button>
        {actuel && (
          <button onClick={() => ecrire("modele_unique", "",
                                        "Retour à la cascade automatique : chaque palier reprend son ordre habituel.")}
            disabled={busy} className="sym-tap" style={{
              padding: "9px 16px", borderRadius: "var(--marque-radius-pill)",
              border: "1px solid var(--marque-border)", background: "var(--marque-canvas)",
              color: "var(--marque-text-body)", fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}>
            Retirer
          </button>
        )}
      </div>

      {avance && (
        <div style={{ marginTop: 10, fontSize: 12, color: "var(--marque-text-muted)",
                      display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span>
            Réglage avancé par palier encore posé (<code>{avance}</code>)
            {actuel ? " — sans effet tant qu'un modèle unique est choisi." : " — il s'applique tant qu'aucun modèle unique n'est choisi."}
          </span>
          <button onClick={() => ecrire("llm_tete", "", "Le réglage par palier est retiré.")}
            disabled={busy} className="sym-tap" style={{
              padding: "5px 12px", borderRadius: "var(--marque-radius-pill)",
              border: "1px solid var(--marque-border)", background: "var(--marque-canvas)",
              color: "var(--marque-text-body)", fontSize: 12, cursor: "pointer",
            }}>
            Retirer
          </button>
        </div>
      )}
      {note && <div style={{ marginTop: 10, fontSize: 13, color: "var(--marque-text-body)" }}>{note}</div>}
      {erreur && <div style={{ marginTop: 10, fontSize: 13, color: "var(--marque-error-text)" }}>⚠ {erreur}</div>}
    </div>
  )
}

// L'anonymisation PII se coupe et se rallume EN UN CLIC (demande de Noa,
// 30/08 : le masquage cassait des flux réels — une adresse tapée masquée en
// boucle, des balises dans les comptes rendus de mails). Le réglage vit en
// base (`anonymisation`), effet immédiat, sans redéploiement. Seul le
// MASQUAGE se coupe : les jetons déjà posés dans l'historique continuent de
// se résoudre.
function ReglageAnonymisation({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [desactivee, setDesactivee] = useState(true)   // le défaut est « désactivée » (31/08) : on l'affiche tel quel le temps du chargement
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
      const r = (lignes || []).find((l: any) => l.cle === "anonymisation")
      // Le défaut est « désactivée » (31/08) : seule la valeur « active »,
      // posée en base ou dans le .env, allume le masquage.
      setDesactivee((r?.valeur || "").trim().toLowerCase() !== "active")
      setErreur("")
    } catch (e: any) {
      setErreur(e?.message || "chargement impossible")
    }
  }, [apiUrl, backendToken])

  useEffect(() => { charger() }, [charger])

  const basculer = async () => {
    setBusy(true); setNote("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/reglages`, {
        method: "PUT",
        headers: { Authorization: `Bearer ${backendToken}`, "Content-Type": "application/json" },
        // Vider la valeur retire la surcharge : « active » redevient le défaut.
        body: JSON.stringify({ cle: "anonymisation", valeur: desactivee ? "active" : "desactivee" }),
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`)
      setNote(desactivee
        ? "Anonymisation réactivée : les données personnelles sont masquées avant tout envoi aux modèles."
        : "Anonymisation désactivée : les textes partent tels quels aux modèles. Les balises déjà présentes dans les anciennes conversations restent lisibles.")
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
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
            Anonymisation des données personnelles
          </div>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2 }}>
            Désactivée par défaut depuis le 31/08 : les demandes passent de bout en bout sans
            masquage. Activée, noms, e-mails et coordonnées sont remplacés par des balises avant
            tout envoi aux modèles externes — au prix de balises dans certaines réponses.
          </div>
        </div>
        <span style={{
          background: desactivee ? "var(--marque-late-bg)" : "var(--marque-paid-bg)",
          color: desactivee ? "var(--marque-late-text)" : "var(--marque-paid-text)",
          padding: "4px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
          fontWeight: 600, whiteSpace: "nowrap",
        }}>
          {desactivee ? "Désactivée" : "Active"}
        </span>
        <button onClick={basculer} disabled={busy}
          className="sym-tap" style={{
            padding: "8px 16px", borderRadius: "var(--marque-radius-pill)",
            border: desactivee ? "none" : "1px solid var(--marque-border)",
            background: desactivee
              ? "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))"
              : "var(--marque-canvas)",
            color: desactivee ? "var(--marque-text-on-dark)" : "var(--marque-text-body)",
            fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}>
          {busy ? "…" : desactivee ? "Réactiver" : "Désactiver"}
        </button>
      </div>
      {note && <div style={{ fontSize: 12, color: "var(--marque-text-body)", marginTop: 8 }}>{note}</div>}
      {erreur && <div style={{ fontSize: 12, color: "var(--marque-error-text)", marginTop: 8 }}>⚠ {erreur}</div>}
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
      <ReglageModeleUnique apiUrl={apiUrl} backendToken={backendToken} />
      <ReglageKpiDepuis apiUrl={apiUrl} backendToken={backendToken} />
      <ReglageAnonymisation apiUrl={apiUrl} backendToken={backendToken} />

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
