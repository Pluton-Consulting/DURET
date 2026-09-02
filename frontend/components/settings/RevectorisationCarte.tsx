"use client"
import { useCallback, useEffect, useState } from "react"

/**
 * RE-VECTORISER LE CORPUS — 02/09.
 *
 * L'écran disait déjà « changer de modèle impose de re-vectoriser tout le
 * corpus ». Il l'annonçait sans permettre de le faire : l'avertissement était
 * exact et sans issue, ce qui revenait à interdire le changement de modèle.
 *
 * CETTE CARTE SÉPARE REGARDER ET AGIR. Elle mesure d'abord ce que rend le
 * modèle choisi, montre l'écart avec la base et le nombre de morceaux
 * concernés, et n'ouvre le bouton qu'ensuite. Une opération qui efface 9 400
 * vecteurs ne doit pas partir au premier clic d'un menu déroulant, et la
 * confirmation demande d'écrire le nombre plutôt que de cliquer « oui » : on
 * ne confirme bien que ce qu'on a lu.
 *
 * ELLE S'AFFICHE TOUJOURS, même quand tout va bien : l'avancement de la
 * vectorisation était invisible jusqu'ici, alors que 6 514 morceaux sur 9 427
 * attendaient depuis des jours derrière un quota épuisé. Un chiffre qu'on ne
 * regarde jamais est un chiffre qui dérive.
 */
type CatalogueModele = {
  reference: string
  libelle: string
  modele: string
  dimension: number | null
  detail: string
  meme_dimension: boolean
  utilisable: boolean
}

type Etat = {
  morceaux: number
  vectorises: number
  restants: number
  avancement: number
  file: Record<string, number>
  colonnes: Record<string, string>
  dimension_base: number
  dimension_modele: number | null
  detail: string
  revectorisation_necessaire: boolean
  mesure_possible: boolean
}

export default function RevectorisationCarte(
  { apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [etat, setEtat] = useState<Etat | null>(null)
  const [erreur, setErreur] = useState("")
  const [message, setMessage] = useState("")
  const [busy, setBusy] = useState(false)
  const [confirme, setConfirme] = useState("")
  const [ouvert, setOuvert] = useState(false)
  // LE CATALOGUE DES MODÈLES D'EMBEDDING, avec la dimension MESURÉE de chacun.
  // Demande de Noa : « dis-moi quels modèles j'ai accès ». Aucune liste écrite
  // à la main ne peut répondre — cela dépend de l'abonnement, cela change, et
  // la dimension n'est annoncée par aucun catalogue de fournisseur. On la
  // mesure, une fois, et l'écran la montre.
  const [catalogue, setCatalogue] = useState<CatalogueModele[] | null>(null)
  const [chargeCatalogue, setChargeCatalogue] = useState(false)

  const voirCatalogue = async () => {
    setChargeCatalogue(true); setErreur("")
    try {
      const r = await fetch(`${apiUrl}/api/settings/embeddings/catalogue`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      const json = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(json?.detail || `HTTP ${r.status}`)
      setCatalogue(json?.modeles || [])
    } catch (e: any) { setErreur(e?.message || "catalogue illisible") }
    finally { setChargeCatalogue(false) }
  }

  const relire = useCallback(async () => {
    try {
      const r = await fetch(`${apiUrl}/api/settings/embeddings`, {
        headers: { Authorization: `Bearer ${backendToken}` }, cache: "no-store",
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setEtat(await r.json())
      setErreur("")
    } catch (e: any) { setErreur(e?.message || "lecture impossible") }
  }, [apiUrl, backendToken])

  useEffect(() => { relire() }, [relire])

  // Pendant que le corpus se re-vectorise, l'avancement bouge : on relit
  // périodiquement, mais JAMAIS quand l'onglet est en arrière-plan — un écran
  // que personne ne regarde n'a pas besoin d'être à jour.
  useEffect(() => {
    const t = setInterval(() => {
      if (document.visibilityState === "visible") relire()
    }, 20000)
    return () => clearInterval(t)
  }, [relire])

  const lancer = async () => {
    if (!etat?.dimension_modele) return
    setBusy(true); setMessage(""); setErreur("")
    try {
      const r = await fetch(`${apiUrl}/api/settings/embeddings/revectoriser`, {
        method: "POST",
        headers: { Authorization: `Bearer ${backendToken}`, "Content-Type": "application/json" },
        body: JSON.stringify({ dimension: etat.dimension_modele }),
      })
      const json = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(json?.detail || `HTTP ${r.status}`)
      setMessage(json?.note || "Re-vectorisation lancée.")
      setOuvert(false); setConfirme("")
      await relire()
    } catch (e: any) { setErreur(e?.message || "opération impossible") }
    finally { setBusy(false) }
  }

  if (!etat && !erreur) return null

  const cadre: React.CSSProperties = {
    marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--marque-border)",
  }
  const petit: React.CSSProperties = { fontSize: 12, color: "var(--marque-text-muted)" }

  if (!etat) {
    return <div style={cadre}><div style={petit}>Vectorisation : {erreur}</div></div>
  }

  const desaccord = etat.revectorisation_necessaire
  const attendu = String(etat.morceaux)

  return (
    <div style={cadre} data-testid="carte-revectorisation">
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "var(--marque-text-primary)" }}>
          Mémoire vectorisée
        </div>
        <div style={petit}>
          {etat.vectorises.toLocaleString("fr-FR")} morceaux sur{" "}
          {etat.morceaux.toLocaleString("fr-FR")} ({etat.avancement} %)
          {etat.restants > 0 && ` — ${etat.restants.toLocaleString("fr-FR")} en attente`}
        </div>
      </div>

      {/* La barre dit l'avancement d'un coup d'œil. Pas de pourcentage arrondi
          vers le haut : « 100 % » alors qu'il reste des morceaux ferait croire
          l'opération finie. */}
      <div style={{ height: 6, borderRadius: 999, background: "var(--marque-border)",
                    overflow: "hidden", margin: "8px 0" }}>
        <div style={{ width: `${etat.avancement}%`, height: "100%",
                      background: "var(--marque-primary)", transition: "width .4s" }} />
      </div>

      <div style={petit}>
        Base : {etat.dimension_base} dimensions · Modèle choisi :{" "}
        {etat.mesure_possible ? etat.detail : <em>{etat.detail}</em>}
      </div>

      <div style={{ marginTop: 8 }}>
        <button type="button" onClick={voirCatalogue} disabled={chargeCatalogue}
          style={{ padding: 0, border: "none", background: "none", fontSize: 12,
                   color: "var(--marque-primary)", cursor: "pointer",
                   textDecoration: "underline" }}>
          {chargeCatalogue ? "mesure en cours…"
            : catalogue ? "actualiser la liste des modèles"
            : "quels modèles d'embedding puis-je choisir ?"}
        </button>
      </div>

      {catalogue && (
        <div style={{ marginTop: 8, fontSize: 12 }}>
          {catalogue.length === 0 ? (
            <div style={petit}>
              Aucun modèle d&apos;embedding trouvé chez les fournisseurs dont la
              clé est posée. Saisissez une clé, ou écrivez l&apos;identifiant du
              modèle à la main dans le champ libre.
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ borderCollapse: "collapse", width: "100%",
                              fontVariantNumeric: "tabular-nums" }}>
                <thead>
                  <tr style={{ textAlign: "left", color: "var(--marque-text-muted)" }}>
                    <th style={{ padding: "4px 8px 4px 0", fontWeight: 600 }}>Modèle</th>
                    <th style={{ padding: "4px 8px", fontWeight: 600 }}>Fournisseur</th>
                    <th style={{ padding: "4px 8px", fontWeight: 600 }}>Dimension</th>
                  </tr>
                </thead>
                <tbody>
                  {catalogue.map((m) => (
                    <tr key={m.reference}
                        style={{ borderTop: "1px solid var(--marque-border)",
                                 opacity: m.utilisable ? 1 : 0.55 }}>
                      <td style={{ padding: "5px 8px 5px 0" }}>{m.modele}</td>
                      <td style={{ padding: "5px 8px", color: "var(--marque-text-muted)" }}>
                        {m.libelle}
                      </td>
                      <td style={{ padding: "5px 8px" }}>
                        {/* La dimension MESURÉE, ou la raison pour laquelle elle
                            ne l'a pas été : un modèle muet n'est pas un modèle
                            absent, c'est peut-être une clé qui manque. */}
                        {m.dimension
                          ? <>{m.dimension}{m.meme_dimension && (
                              <span style={{ color: "var(--marque-text-muted)" }}>
                                {" "}· celle de la base
                              </span>)}</>
                          : <span style={{ color: "var(--marque-text-muted)" }}>{m.detail}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ ...petit, marginTop: 6 }}>
                Dimensions mesurées en interrogeant chaque modèle, pas déduites
                d&apos;une liste : aucun catalogue de fournisseur ne les annonce.
              </div>
            </div>
          )}
        </div>
      )}

      {/* LE BOUTON NE DOIT PAS DÉPENDRE D'UN ÉCART DE DIMENSION (02/09).
          Il n'était offert que si les tailles différaient — or deux modèles de
          MÊME dimension produisent des vecteurs tout aussi incomparables : une
          distance entre un vecteur Gemini et un vecteur Ollama n'a aucun sens
          géométrique, même à 1536 composantes de part et d'autre. Passer de
          gemini-embedding-001 à text-embedding-3-small (tous deux 1536) aurait
          donc laissé un corpus silencieusement faux, sans aucun moyen de le
          reconstruire depuis l'écran. */}
      {desaccord && (
        <div style={{ marginTop: 10, padding: "10px 12px", borderRadius: 8,
                      background: "var(--marque-warning-bg, #fff8e6)",
                      border: "1px solid var(--marque-warning-border, #f0d69a)",
                      fontSize: 12, color: "var(--marque-text-body)" }}>
          <b>Le modèle choisi ne correspond pas à la base.</b> Il rend{" "}
          {etat.dimension_modele} dimensions, la base en attend {etat.dimension_base} :
          rien ne peut être vectorisé tant que les deux ne concordent pas.
          Re-vectoriser efface les {etat.morceaux.toLocaleString("fr-FR")} vecteurs
          actuels et les recalcule avec le nouveau modèle. Pendant l&apos;opération,
          la recherche continue de répondre par sa voie textuelle.
        </div>
      )}

      {!desaccord && etat.mesure_possible && (
        <div style={{ ...petit, marginTop: 8 }}>
          Les dimensions concordent. Si vous venez de CHANGER de modèle sans
          changer de dimension, re-vectorisez quand même : deux modèles ne
          produisent pas des vecteurs comparables, et la recherche répondrait
          sans rien signaler.
        </div>
      )}

      {!ouvert && (
        <button type="button" onClick={() => setOuvert(true)} disabled={busy || !etat.mesure_possible}
          style={{ marginTop: 10, padding: "6px 12px", borderRadius: 999, fontSize: 13,
                   cursor: "pointer", border: "1px solid var(--marque-border)",
                   background: "var(--marque-surface)" }}>
          Re-vectoriser le corpus…
        </button>
      )}

      {ouvert && (
        <div style={{ marginTop: 10 }}>
          {/* ON NE CONFIRME BIEN QUE CE QU'ON A LU. Recopier le nombre de
              morceaux oblige à regarder ce qu'on efface ; un « oui » se clique
              sans avoir lu la phrase au-dessus. */}
          <div style={{ ...petit, marginBottom: 6 }}>
            Pour confirmer, recopiez le nombre de morceaux concernés : <b>{attendu}</b>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input value={confirme} onChange={(e) => setConfirme(e.target.value)}
              inputMode="numeric" aria-label="Nombre de morceaux à re-vectoriser"
              style={{ width: 120, padding: "6px 10px", borderRadius: 8, fontSize: 13,
                       border: "1px solid var(--marque-border)" }} />
            <button type="button" onClick={lancer} disabled={busy || confirme.trim() !== attendu}
              style={{ padding: "6px 12px", borderRadius: 999, fontSize: 13,
                       cursor: confirme.trim() === attendu ? "pointer" : "not-allowed",
                       border: "1px solid var(--marque-border)",
                       opacity: confirme.trim() === attendu ? 1 : 0.5,
                       background: "var(--marque-surface)" }}>
              {busy ? "En cours…" : "Effacer et re-vectoriser"}
            </button>
            <button type="button" onClick={() => { setOuvert(false); setConfirme("") }}
              disabled={busy}
              style={{ padding: "6px 12px", borderRadius: 999, fontSize: 13,
                       cursor: "pointer", border: "1px solid transparent",
                       background: "transparent", color: "var(--marque-text-muted)" }}>
              Annuler
            </button>
          </div>
        </div>
      )}

      {message && <div style={{ ...petit, marginTop: 8, color: "var(--marque-text-body)" }}>{message}</div>}
      {erreur && <div style={{ ...petit, marginTop: 8, color: "var(--marque-error-text)" }}>{erreur}</div>}
    </div>
  )
}
