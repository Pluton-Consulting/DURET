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
  ollama_cloud_api_key: { nom: "Ollama Cloud", role: "Abonnement : modèle rapide, modèle puissant et lecture d'images" },
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

// LES DEUX MODÈLES DE L'ASSISTANT — ET RIEN D'AUTRE.
//
// Demande de Noa du 31/08 : « deux modèles fiables et rapides, un pour répondre
// vite et un pour les grosses tâches ; on oublie tous les autres LLM ». Quand au
// moins un des deux est choisi, la cascade habituelle N'EST PLUS UTILISÉE : le
// rapide sert les paliers LIGHT et STANDARD (orientation, mémoire, rédaction
// courante), le puissant sert COMPLEX (analyse, synthèse) et les campagnes
// d'enrichissement, et chacun est le secours de l'autre. Deux modèles, deux
// comportements, une facture lisible. « Retirer » les deux rend la cascade.
// La vision, les images et les embeddings gardent leur modèle dédié.
//
// Le forçage fin par palier (`llm_tete`, fichier de configuration) est montré
// s'il traîne encore en base, et retirable : un réglage invisible est un
// réglage qu'on ne peut pas vérifier.
interface FicheFournisseur {
  fournisseur: string
  libelle: string
  cle_presente: boolean
  modeles: { id: string; ecarte: boolean; raison: string }[]
}

function LigneModele({ titre, aide, actuel, fiches, busy, onChoisir, onRetirer }: {
  titre: string; aide: string; actuel: string; fiches: FicheFournisseur[]; busy: boolean
  onChoisir: (valeur: string) => void; onRetirer: () => void
}) {
  const [fournisseur, setFournisseur] = useState("")
  const [modele, setModele] = useState("")
  const [autre, setAutre] = useState("")
  useEffect(() => {
    const [f, ...reste] = actuel.split(":")
    const m = reste.join(":")
    const premier = fiches.find((x) => x.cle_presente)
    const fChoisi = (actuel && f) || premier?.fournisseur || ""
    setFournisseur(fChoisi)
    const fiche = fiches.find((x) => x.fournisseur === fChoisi)
    const connu = fiche?.modeles.some((x) => x.id === m)
    setModele(connu ? m : (fiche?.modeles[0]?.id || ""))
    setAutre(actuel && !connu ? m : "")
  }, [actuel, fiches])
  const fiche = fiches.find((x) => x.fournisseur === fournisseur)
  const choisi = `${fournisseur}:${(autre.trim() || modele).trim()}`
  const pret = Boolean(fournisseur && (autre.trim() || modele) && fiche?.cle_presente)
  const champ = { padding: "8px 10px", borderRadius: "var(--marque-radius-pill)",
                  border: "1px solid var(--marque-border)", fontSize: 13 } as const
  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--marque-border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--marque-text-primary)" }}>{titre}</div>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>{aide}</div>
        </div>
        <span style={{
          background: actuel ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
          color: actuel ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
          padding: "4px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
          fontWeight: 600, whiteSpace: "nowrap",
        }}>
          {actuel || "non choisi"}
        </span>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
        <select value={fournisseur} disabled={busy} style={{ ...champ, minWidth: 190 }}
          onChange={(e) => {
            const f = e.target.value
            setFournisseur(f)
            setModele(fiches.find((x) => x.fournisseur === f)?.modeles[0]?.id || "")
            setAutre("")
          }}>
          {fiches.length === 0 && <option value="">chargement…</option>}
          {fiches.map((f) => (
            <option key={f.fournisseur} value={f.fournisseur} disabled={!f.cle_presente}>
              {f.libelle}{f.cle_presente ? "" : " — clé absente"}
            </option>
          ))}
        </select>
        <select value={modele} disabled={busy || !fiche} style={{ ...champ, minWidth: 230 }}
          onChange={(e) => { setModele(e.target.value); setAutre("") }}>
          {(fiche?.modeles || []).map((m) => (
            <option key={m.id} value={m.id}>{m.id}{m.ecarte ? ` — écarté (${m.raison})` : ""}</option>
          ))}
        </select>
        <input value={autre} disabled={busy} onChange={(e) => setAutre(e.target.value)}
          placeholder="ou l'identifiant exact d'un autre modèle" style={{ ...champ, minWidth: 240 }} />
        <button onClick={() => onChoisir(choisi)} disabled={busy || !pret || choisi === actuel}
          className="sym-tap" style={{
            padding: "8px 16px", borderRadius: "var(--marque-radius-pill)", border: "none",
            background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
            color: "var(--marque-text-on-dark)", fontSize: 13, fontWeight: 700,
            cursor: busy || !pret || choisi === actuel ? "not-allowed" : "pointer",
            opacity: busy || !pret || choisi === actuel ? 0.6 : 1,
          }}>
          Utiliser
        </button>
        {actuel && (
          <button onClick={onRetirer} disabled={busy} className="sym-tap" style={{
            padding: "8px 14px", borderRadius: "var(--marque-radius-pill)",
            border: "1px solid var(--marque-border)", background: "var(--marque-canvas)",
            color: "var(--marque-text-body)", fontSize: 13, fontWeight: 600, cursor: "pointer",
          }}>
            Retirer
          </button>
        )}
      </div>
    </div>
  )
}

function ReglageModeles({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [fiches, setFiches] = useState<FicheFournisseur[]>([])
  const [rapide, setRapide] = useState("")
  const [puissant, setPuissant] = useState("")
  const [avance, setAvance] = useState("")
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
      setFiches(json?.fournisseurs || [])
      setRapide(json?.modele_rapide || "")
      setPuissant(json?.modele_puissant || "")
      setAvance(json?.llm_tete || "")
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

  const exclusif = Boolean(rapide || puissant)
  return (
    <div className="sym-card" style={{
      background: "var(--marque-surface)", border: "2px solid var(--marque-primary)",
      borderRadius: "var(--marque-radius-card-sm)", padding: "16px 18px", marginBottom: 22,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
            Les modèles de l&apos;assistant
          </div>
          <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 3, lineHeight: 1.5 }}>
            Deux modèles, et rien d&apos;autre : un <b>rapide</b> pour répondre au quotidien, un
            <b> puissant</b> pour les grosses tâches (analyse, synthèse, enrichissement). Chacun
            secourt l&apos;autre. Dès qu&apos;un des deux est choisi, la cascade automatique n&apos;est
            plus utilisée. La vision (plans, photos), les images et les embeddings gardent leur
            modèle dédié.
          </div>
        </div>
        <span style={{
          background: exclusif ? "var(--marque-paid-bg)" : "var(--marque-canvas)",
          color: exclusif ? "var(--marque-paid-text)" : "var(--marque-text-muted)",
          padding: "5px 12px", borderRadius: "var(--marque-radius-pill)", fontSize: 12,
          fontWeight: 600, whiteSpace: "nowrap",
        }}>
          {exclusif ? "deux modèles seulement" : "cascade automatique"}
        </span>
      </div>

      <LigneModele titre="Réponses rapides" aide="le chat au quotidien, l'orientation, la rédaction courante"
        actuel={rapide} fiches={fiches} busy={busy}
        onChoisir={(v) => ecrire("modele_rapide", v, `${v} répond désormais au quotidien. Effet immédiat.`)}
        onRetirer={() => ecrire("modele_rapide", "", "Modèle rapide retiré.")} />
      <LigneModele titre="Grosses tâches" aide="analyse, synthèse, enrichissement de la mémoire d'entreprise"
        actuel={puissant} fiches={fiches} busy={busy}
        onChoisir={(v) => ecrire("modele_puissant", v, `${v} prend désormais les grosses tâches. Effet immédiat.`)}
        onRetirer={() => ecrire("modele_puissant", "", "Modèle puissant retiré.")} />

      {avance && (
        <div style={{ marginTop: 10, fontSize: 12, color: "var(--marque-text-muted)",
                      display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span>
            Réglage avancé par palier encore posé (<code>{avance}</code>)
            {exclusif ? " — sans effet tant qu'un modèle est choisi ci-dessus." : " — il s'applique tant qu'aucun modèle n'est choisi ci-dessus."}
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

/** COMBIEN D'APPELS DE MODÈLE PARTENT EN MÊME TEMPS.
 *
 *  L'abonnement du fournisseur en autorise un nombre fixe : au-delà, il met en
 *  file puis refuse — et un refus coûte cinq minutes de quarantaine côté
 *  serveur. Le plafond se règle donc ici, sans redéploiement : globalement, et
 *  par personne pour qu'un seul compte ne prenne pas tous les créneaux.
 *
 *  Un champ vide sur une personne veut dire « elle suit le plafond de son
 *  rôle » — ce n'est pas zéro : un plafond nul l'empêcherait de travailler.
 */
function ReglageConcurrence({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [etat, setEtat] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState("")
  const [erreur, setErreur] = useState("")

  const charger = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/settings/concurrence`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setEtat(await res.json()); setErreur("")
    } catch (e: any) { setErreur(e?.message || "Chargement impossible") }
  }, [apiUrl, backendToken])

  useEffect(() => { charger() }, [charger])

  async function envoyer(corps: any, message: string) {
    setBusy(true); setNote(""); setErreur("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/concurrence`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify(corps),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || `HTTP ${res.status}`)
      setNote(message); await charger()
    } catch (e: any) { setErreur(e?.message || "Enregistrement impossible") }
    finally { setBusy(false) }
  }

  const champ: React.CSSProperties = {
    width: 64, padding: "6px 10px", border: "1px solid var(--marque-border)",
    borderRadius: 8, fontSize: 13, textAlign: "center",
    color: "var(--marque-text-primary)", background: "var(--marque-surface)",
  }

  return (
    <div className="sym-card" style={{
      background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
      borderRadius: "var(--marque-radius-card-sm)", padding: "16px 18px", marginBottom: 22,
    }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
        Appels simultanés au modèle
      </div>
      <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 2, maxWidth: "70ch" }}>
        L'abonnement en autorise un nombre limité à la fois. Au-delà, le fournisseur refuse et le
        modèle est mis de côté cinq minutes : mieux vaut attendre ici. Un champ vide sur une
        personne signifie qu'elle suit le plafond de son rôle.
      </div>

      {etat && (
        <>
          <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", marginTop: 14 }}>
            <label style={{ fontSize: 13, color: "var(--marque-text-body)" }}>
              Plafond global{" "}
              <input type="number" min={1} max={64} defaultValue={etat.plafond_global} style={champ}
                onBlur={(e) => {
                  const v = parseInt(e.target.value, 10)
                  if (v && v !== etat.plafond_global) envoyer({ global_max: v }, `Plafond global : ${v}.`)
                }} />
            </label>
            <span style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>
              {etat.libres !== null && etat.libres !== undefined
                ? `${etat.libres} créneau(x) libre(s) à l'instant`
                : "aucun appel en cours"}
              {" · défaut par personne : "}{etat.plafond_personne_defaut}
              {" · tâches de fond : "}{etat.plafond_fond}
              {" · attente maximale : "}{etat.attente_max_s}{" s"}
            </span>
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--marque-text-muted)",
                          textTransform: "uppercase", letterSpacing: ".07em", marginBottom: 8 }}>
              Par personne
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
              {(etat.par_utilisateur || []).map((u: any) => (
                <div key={u.id} style={{ display: "flex", alignItems: "center", gap: 10,
                                         padding: "8px 10px", border: "1px solid var(--marque-border)",
                                         borderRadius: 10 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--marque-text-primary)",
                                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {u.nom || u.email}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--marque-text-muted)" }}>
                      {u.role}{u.plafond === null ? ` · suit son rôle (${etat.par_role?.[u.role] ?? "—"})` : ""}
                    </div>
                  </div>
                  <input type="number" min={1} max={64} placeholder="—" style={champ}
                    defaultValue={u.plafond ?? ""}
                    onBlur={(e) => {
                      const brut = e.target.value.trim()
                      const v = brut === "" ? null : parseInt(brut, 10)
                      if (v !== (u.plafond ?? null)) {
                        envoyer({ par_utilisateur: { [u.id]: v } },
                                `${u.nom || u.email} : ${v === null ? "suit son rôle" : v + " appels"}.`)
                      }
                    }} />
                </div>
              ))}
            </div>
          </div>
        </>
      )}
      {busy && <div style={{ fontSize: 12, color: "var(--marque-text-muted)", marginTop: 8 }}>Enregistrement…</div>}
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
      <ReglageModeles apiUrl={apiUrl} backendToken={backendToken} />
      <ReglageKpiDepuis apiUrl={apiUrl} backendToken={backendToken} />
      <ReglageAnonymisation apiUrl={apiUrl} backendToken={backendToken} />
      <ReglageConcurrence apiUrl={apiUrl} backendToken={backendToken} />

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
