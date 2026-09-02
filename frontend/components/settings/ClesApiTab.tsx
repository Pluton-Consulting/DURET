"use client"

import { useCallback, useEffect, useState } from "react"
import RevectorisationCarte from "./RevectorisationCarte"

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
  // « embedding » | « vision » | « texte », déduit du nom par le serveur.
  // Proposer bge-m3 pour la vision ne produit pas une erreur claire, ça
  // produit du silence : chaque ligne ne montre donc que ce qui sait faire
  // son travail.
  modeles: { id: string; ecarte: boolean; raison: string; usage?: string }[]
}

function LigneModele({ titre, aide, actuel, fiches: toutesFiches, busy, onChoisir,
                      onRetirer, avertissement, usage }: {
  titre: string; aide: string; actuel: string; fiches: FicheFournisseur[]; busy: boolean
  onChoisir: (valeur: string) => void; onRetirer: () => void
  // L'usage attendu sur CETTE ligne. Absent = tout est proposé (le texte, qui
  // n'a pas de contrainte de modalité).
  usage?: "embedding" | "vision"
  // Ce qu'un changement COÛTE, dit AVANT le clic. Les embeddings sont le seul
  // réglage de cette carte dont le changement impose un travail derrière : les
  // vecteurs déjà calculés ne se comparent pas à ceux d'un autre modèle.
  avertissement?: string
}) {
  // LE FILTRE EST UNE AIDE, PAS UNE BARRIÈRE. Un fournisseur dont AUCUN modèle
  // ne correspond garde sa liste entière plutôt que de se vider : l'heuristique
  // du serveur déduit l'usage d'un NOM, elle peut se tromper sur un modèle
  // exotique, et un menu vide empêcherait de choisir ce qu'on sait bon. Le
  // champ libre à côté reste de toute façon ouvert.
  const fiches = usage
    ? toutesFiches.map((f) => {
        const gardes = f.modeles.filter((m) => m.usage === usage)
        return gardes.length ? { ...f, modeles: gardes } : f
      })
    : toutesFiches
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
      {avertissement && (
        <div style={{ fontSize: 12, color: "var(--marque-late-text, var(--marque-text-body))",
                      background: "var(--marque-late-bg, rgba(0,0,0,0.04))",
                      padding: "8px 10px", borderRadius: 8, marginBottom: 10 }}>
          {avertissement}
        </div>
      )}
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

// UNE CLÉ QUI VIENT D'ÊTRE SAISIE DOIT SE VOIR ICI TOUT DE SUITE (01/09).
//
// Cette carte et la liste des clés sont deux composants SŒURS, chacun avec son
// état : enregistrer une clé rechargeait la liste des clés, jamais le catalogue
// des modèles. Or le bouton « Appliquer » exige `cle_presente` — choisir un
// modèle dont la clé manque garantirait l'échec. Résultat mesuré en production
// (relevé de Noa) : la clé était bien enregistrée, et le modèle restait
// impossible à choisir jusqu'au rechargement de la page, sans que rien ne
// l'explique. `signal` est incrémenté par le parent après chaque
// enregistrement : la carte relit, et la clé apparaît.
function ReglageModeles({ apiUrl, backendToken, signal = 0 }:
  { apiUrl: string; backendToken: string; signal?: number }) {
  const [fiches, setFiches] = useState<FicheFournisseur[]>([])
  const [rapide, setRapide] = useState("")
  const [puissant, setPuissant] = useState("")
  const [avance, setAvance] = useState("")
  const [vision, setVision] = useState("")
  const [embedding, setEmbedding] = useState("")
  const [image, setImage] = useState<{ fournisseur: string; modele: string } | null>(null)
  const [dimensions, setDimensions] = useState(1536)
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
      setVision(json?.modele_vision || "")
      setEmbedding(json?.modele_embedding || "")
      setImage(json?.modele_image || null)
      setDimensions(json?.embedding_dimensions || 1536)
      setErreur("")
    } catch (e: any) {
      setErreur(e?.message || "chargement impossible")
    }
  }, [apiUrl, backendToken])
  // `signal` n'est pas lu dans `charger` : il n'a qu'un rôle, déclencher une
  // relecture quand le parent dit qu'une clé a bougé.
  useEffect(() => { charger() }, [charger, signal])

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
      <LigneModele titre="Vision et OCR" usage="vision" aide="lecture des plans, des photos et des pièces jointes scannées"
        actuel={vision} fiches={fiches} busy={busy}
        onChoisir={(v) => ecrire("modele_vision", v, `${v} lit désormais les images. Effet immédiat.`)}
        onRetirer={() => ecrire("modele_vision", "", "Modèle de vision retiré : la cascade reprend.")} />
      <LigneModele titre="Embeddings" usage="embedding" aide="la recherche documentaire et la mémoire de conversation"
        actuel={embedding} fiches={fiches} busy={busy}
        avertissement={`Changer de modèle impose de re-vectoriser tout le corpus : les vecteurs existants (${dimensions} dimensions) ne se comparent pas à ceux d'un autre modèle. Un modèle qui rend une autre dimension est refusé à l'écriture, sans rien casser.`}
        onChoisir={(v) => ecrire("modele_embedding", v, `${v} vectorise désormais. Re-vectorisation nécessaire.`)}
        onRetirer={() => ecrire("modele_embedding", "", "Modèle d'embedding retiré.")} />

      {/* L'avertissement au-dessus annonçait la re-vectorisation sans
          permettre de la faire : exact, et sans issue. Cette carte mesure
          l'écart, montre l'avancement, et ouvre l'opération. */}
      <RevectorisationCarte apiUrl={apiUrl} backendToken={backendToken} />

      {/* LA GÉNÉRATION D'IMAGES SE MONTRE, ELLE NE SE CHOISIT PAS — décision de
          Noa. On l'affiche pour qu'on sache ce qui tire les visuels : ne rien
          montrer laisserait croire que rien ne s'en occupe. */}
      {image && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--marque-border)",
                      display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--marque-text-primary)" }}>
              Génération d&apos;images
            </div>
            <div style={{ fontSize: 12, color: "var(--marque-text-muted)" }}>
              visuels d&apos;aménagement et retouches de photos
            </div>
          </div>
          <span style={{ fontSize: 12.5, color: "var(--marque-text-body)",
                         background: "var(--marque-canvas)", padding: "6px 12px",
                         borderRadius: "var(--marque-radius-pill)",
                         border: "1px solid var(--marque-border)" }}>
            {image.fournisseur} : {image.modele} · choix arrêté
          </span>
        </div>
      )}

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
// LES APPELS SIMULTANÉS — UN SEUL CHIFFRE, TOUS COMPTES CONFONDUS.
//
// Décision de Noa (01/09) : « ce paramètre concerne l'ensemble des comptes
// cumulés ». L'abonnement du fournisseur autorise un nombre fixe d'appels de
// front ; au-delà il met en file puis refuse, et un refus coûte cinq minutes de
// quarantaine dans le disjoncteur. Ce qui compte est donc le TOTAL, pas sa
// répartition — les tableaux par rôle et par compte ont été retirés, avec eux
// la seule dépendance de cette carte à l'état des migrations.
function ReglageConcurrence({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [etat, setEtat] = useState<any>(null)
  const [saisie, setSaisie] = useState("")
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState("")
  const [erreur, setErreur] = useState("")

  const charger = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/settings/concurrence`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setEtat(json); setErreur("")
      setSaisie(json?.origine_global === "parametres" ? String(json?.plafond_global ?? "") : "")
    } catch (e: any) { setErreur(e?.message || "Chargement impossible") }
  }, [apiUrl, backendToken])

  useEffect(() => { charger() }, [charger])

  async function envoyer(valeur: string | null, message: string) {
    setBusy(true); setNote(""); setErreur("")
    try {
      const res = await fetch(`${apiUrl}/api/settings/concurrence`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({ global_max: valeur }),
      })
      if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.detail || `HTTP ${res.status}`)
      setNote(message); await charger()
    } catch (e: any) { setErreur(e?.message || "Enregistrement impossible") }
    finally { setBusy(false) }
  }

  return (
    <div style={{ border: "1px solid var(--marque-border)", borderRadius: 12,
                  padding: 16, marginBottom: 16 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)" }}>
        Appels simultanés au modèle
      </div>
      <div style={{ fontSize: 13, color: "var(--marque-text-muted)", marginTop: 4 }}>
        Tous comptes confondus. Au-delà, les demandes attendent leur tour.
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14,
                    flexWrap: "wrap" }}>
        <input
          type="number" min={1} max={64} value={saisie} disabled={busy}
          onChange={(e) => setSaisie(e.target.value)}
          placeholder={String(etat?.plafond_global ?? "")}
          style={{ width: 88, padding: "8px 10px", fontSize: 14,
                   border: "1px solid var(--marque-border)",
                   borderRadius: "var(--marque-radius-pill)" }} />
        <button
          type="button" disabled={busy || !saisie.trim()}
          onClick={() => envoyer(saisie.trim(), "Plafond enregistré.")}
          style={{ padding: "8px 16px", borderRadius: "var(--marque-radius-pill)",
                   border: "none", fontSize: 13, fontWeight: 600,
                   cursor: busy || !saisie.trim() ? "default" : "pointer",
                   opacity: busy || !saisie.trim() ? 0.5 : 1,
                   background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
                   color: "var(--marque-text-on-dark)" }}>
          Appliquer
        </button>
        {etat?.origine_global === "parametres" && (
          <button
            type="button" disabled={busy}
            onClick={() => envoyer(null, "Retour au plafond par défaut.")}
            style={{ padding: "8px 14px", borderRadius: "var(--marque-radius-pill)",
                     border: "1px solid var(--marque-border)", fontSize: 13,
                     background: "var(--marque-canvas)", cursor: "pointer" }}>
            Retirer
          </button>
        )}
        <span style={{ fontSize: 12.5, color: "var(--marque-text-muted)" }}>
          {etat === null ? "…"
            : etat.origine_global === "parametres"
              ? `${etat.plafond_global} en vigueur`
              : `${etat.plafond_global} par défaut`}
          {typeof etat?.libres === "number" ? ` · ${etat.libres} libre(s)` : ""}
        </span>
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
  // Incrémenté à chaque clé enregistrée ou retirée : c'est ce qui fait relire
  // le catalogue des modèles à la carte du dessus.
  const [clesModifiees, setClesModifiees] = useState(0)
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
      // La carte des modèles doit relire son catalogue : sans ce signal, elle
      // continue de croire que la clé manque, et « Appliquer » reste grisé.
      setClesModifiees((n) => n + 1)
      await charger()
    } catch (e: any) {
      setErreur(e?.message || "enregistrement impossible")
    } finally {
      setBusy("")
    }
  }

  return (
    <div>
      <ReglageModeles apiUrl={apiUrl} backendToken={backendToken} signal={clesModifiees} />
      <ReglageKpiDepuis apiUrl={apiUrl} backendToken={backendToken} />
      <ReglageAnonymisation apiUrl={apiUrl} backendToken={backendToken} />
      <ReglageConcurrence apiUrl={apiUrl} backendToken={backendToken} />

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
