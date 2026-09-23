"use client"
import { useCallback, useEffect, useRef, useState } from "react"
import { MessageRenderer } from "@/components/chat/MessageRenderer"

/**
 * L'ONGLET FICHIERS — l'explorateur du NAS de Duret (23/09).
 *
 * Demande de Noa, après la comparaison des deux options : un onglet « Fichiers »
 * à gauche du tableau de bord, avec l'explorateur refait (option 1) en grand,
 * et « toutes les actions qu'un explorateur de fichiers permet — sinon un message
 * qui donne le chemin à copier et dit de le faire dans les fichiers ».
 *
 * CE QUI SE FAIT ICI : naviguer (fil d'Ariane, dossier parent), chercher par nom
 * sur tout le NAS ou dans le dossier ouvert, trier (nom, date, taille), ouvrir un
 * fichier en aperçu et le télécharger, copier un chemin, créer un dossier, déposer
 * des fichiers (bouton ou glisser-déposer). Aucune de ces écritures n'écrase quoi
 * que ce soit : le NAS refuse un nom déjà pris.
 *
 * CE QUI NE SE FAIT PAS ICI, EXPRÈS : renommer, déplacer, supprimer. Ces gestes
 * se font dans l'explorateur de fichiers de l'ordinateur, où existent la corbeille
 * et l'annulation ; l'écran donne le chemin exact à copier.
 *
 * Le serveur tranche l'accès (403 à tout autre rôle que super_admin pour l'instant)
 * et applique les droits par dossier : ce que la personne ne peut pas voir n'existe
 * pas pour elle, ni dans la liste ni dans la recherche.
 */
interface Props { apiUrl: string; token: string }

type Entree = { nom: string; chemin: string; dossier: boolean; octets?: number | null; modifie?: number | null }
type Tri = "nom" | "date" | "taille"

const taille = (n?: number | null) => {
  if (typeof n !== "number") return ""
  if (n < 1024) return `${n} o`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} Ko`
  return `${(n / (1024 * 1024)).toFixed(1).replace(".", ",")} Mo`
}
const date = (s?: number | null) =>
  typeof s === "number" && s > 0
    ? new Date(s * 1000).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })
    : ""
const parent = (chemin: string) => chemin.split("/").slice(0, -1).join("/") || null

export default function Fichiers({ apiUrl, token }: Props) {
  const [acces, setAcces] = useState<{ explorateur: boolean; dsm: string | null } | null | false>(null)
  const [chemin, setChemin] = useState<string | null>(null)
  const [entrees, setEntrees] = useState<Entree[]>([])
  const [total, setTotal] = useState(0)
  const [charge, setCharge] = useState(false)
  const [erreur, setErreur] = useState("")
  const [note, setNote] = useState("")
  const [motif, setMotif] = useState("")
  const [recherche, setRecherche] = useState<{ motif: string; partiel: boolean } | null>(null)
  const [tri, setTri] = useState<Tri>("nom")
  const [ouvert, setOuvert] = useState<{ nom: string; chemin: string; bloc?: any; message?: string } | null>(null)
  const [ailleurs, setAilleurs] = useState<{ action: string; chemin: string } | null>(null)
  const [nouveauDossier, setNouveauDossier] = useState<string | null>(null)
  const [depot, setDepot] = useState<string>("")
  const [survol, setSurvol] = useState(false)
  const choixFichiers = useRef<HTMLInputElement>(null)

  const appeler = useCallback(async (url: string, init?: RequestInit) => {
    const r = await fetch(`${apiUrl}${url}`, {
      ...init, cache: "no-store",
      headers: { Authorization: `Bearer ${token}`,
                 ...(init?.body && typeof init.body === "string" ? { "Content-Type": "application/json" } : {}) },
    })
    const j = await r.json().catch(() => ({}))
    if (!r.ok) throw new Error(j?.detail || `HTTP ${r.status}`)
    return j
  }, [apiUrl, token])

  useEffect(() => {
    if (!token) return
    appeler("/api/nas-explorateur/acces").then(setAcces).catch(() => setAcces(false))
  }, [appeler, token])

  const aller = useCallback(async (vers: string | null) => {
    setCharge(true); setErreur(""); setRecherche(null)
    try {
      const j = await appeler(`/api/nas-explorateur/lister${vers ? `?chemin=${encodeURIComponent(vers)}` : ""}`)
      setChemin(j.chemin); setEntrees(j.entrees || []); setTotal(j.total ?? (j.entrees || []).length)
    } catch (e: any) {
      setErreur(e?.message || "listage impossible")
    } finally {
      setCharge(false)
    }
  }, [appeler])

  useEffect(() => { if (acces) aller(null) }, [acces, aller])

  const chercher = async () => {
    const m = motif.trim()
    if (m.length < 2) return
    setCharge(true); setErreur("")
    try {
      const j = await appeler(`/api/nas-explorateur/chercher?motif=${encodeURIComponent(m)}${chemin ? `&dossier=${encodeURIComponent(chemin)}` : ""}`)
      setEntrees(j.resultats || []); setTotal(j.total ?? (j.resultats || []).length)
      setRecherche({ motif: m, partiel: !!j.partiel })
    } catch (e: any) {
      setErreur(e?.message || "recherche impossible")
    } finally {
      setCharge(false)
    }
  }

  const ouvrir = async (e: Entree) => {
    setOuvert({ nom: e.nom, chemin: e.chemin })
    try {
      const j = await appeler(`/api/nas-explorateur/ouvrir`, { method: "POST", body: JSON.stringify({ chemin: e.chemin }) })
      setOuvert({ nom: e.nom, chemin: e.chemin, bloc: j.bloc_ui, message: j.message })
    } catch (err: any) {
      setOuvert({ nom: e.nom, chemin: e.chemin, message: err?.message || "ouverture impossible" })
    }
  }

  const copier = async (texte: string) => {
    try { await navigator.clipboard.writeText(texte); setNote("Chemin copié.") }
    catch { setNote(`Copiez ce chemin : ${texte}`) }
  }

  const creerDossier = async () => {
    const nom = (nouveauDossier || "").trim()
    if (!nom || !chemin) return
    setErreur(""); setNote("")
    try {
      const r = await appeler("/api/nas-explorateur/creer-dossier", { method: "POST", body: JSON.stringify({ parent: chemin, nom }) })
      if (r.cree) setNote(`Dossier « ${r.nom} » créé.`)
      else if (r.existait) setNote(`Le dossier « ${r.nom} » existait déjà.`)
      else setErreur(r.message || "Le NAS a refusé la création.")
      setNouveauDossier(null); await aller(chemin)
    } catch (e: any) { setErreur(e?.message || "création impossible") }
  }

  const deposer = async (liste: FileList | File[]) => {
    if (!chemin) { setErreur("Ouvrez d'abord le dossier où déposer."); return }
    const fichiers = Array.from(liste)
    setErreur(""); setNote("")
    const refuses: string[] = []
    for (const [i, f] of fichiers.entries()) {
      setDepot(`Dépôt ${i + 1} sur ${fichiers.length} : ${f.name}`)
      const fd = new FormData(); fd.append("dossier", chemin); fd.append("fichier", f)
      try {
        const r = await appeler("/api/nas-explorateur/deposer", { method: "POST", body: fd })
        if (!r.depose) refuses.push(`${f.name} : ${r.message || "refusé"}`)
      } catch (e: any) { refuses.push(`${f.name} : ${e?.message || "échec"}`) }
    }
    setDepot("")
    if (refuses.length) setErreur(`Non déposé — ${refuses.join(" ; ")}`)
    else setNote(`${fichiers.length} fichier(s) déposé(s).`)
    await aller(chemin)
  }

  if (acces === null) return <div className="fx-vide">Ouverture du serveur de fichiers…</div>
  if (acces === false) return <div className="fx-vide">Le serveur de fichiers n'est pas ouvert à ce compte.</div>

  const segments = (chemin || "").split("/").filter(Boolean)
  const tries = [...entrees].sort((a, b) => {
    if (a.dossier !== b.dossier) return a.dossier ? -1 : 1
    if (tri === "date") return (b.modifie || 0) - (a.modifie || 0)
    if (tri === "taille") return (b.octets || 0) - (a.octets || 0)
    return a.nom.localeCompare(b.nom, "fr", { numeric: true })
  })

  return (
    <div className="fx" onDragOver={(e) => { if (chemin) { e.preventDefault(); setSurvol(true) } }}
         onDragLeave={() => setSurvol(false)}
         onDrop={(e) => { e.preventDefault(); setSurvol(false); if (e.dataTransfer.files?.length) void deposer(e.dataTransfer.files) }}
         data-survol={survol ? "oui" : "non"}>
      <div className="fx-tete">
        <div>
          <h2 className="fx-titre">Fichiers</h2>
          <nav className="fx-ariane" aria-label="Emplacement">
            <button type="button" onClick={() => aller(null)}>NAS</button>
            {segments.map((s, i) => (
              <span key={i}><span aria-hidden>›</span>
                <button type="button" onClick={() => aller("/" + segments.slice(0, i + 1).join("/"))}>{s}</button></span>
            ))}
          </nav>
        </div>
        {acces.dsm && <a className="fx-lien" href={acces.dsm} target="_blank" rel="noopener noreferrer">Site Synology ↗</a>}
      </div>

      <div className="fx-outils">
        <button type="button" disabled={!chemin} onClick={() => aller(chemin ? parent(chemin) : null)} title="Dossier parent">↑ Parent</button>
        <button type="button" onClick={() => aller(chemin)} title="Actualiser" aria-label="Actualiser">↻</button>
        <button type="button" disabled={!chemin} onClick={() => setNouveauDossier("")}>+ Dossier</button>
        <button type="button" disabled={!chemin} onClick={() => choixFichiers.current?.click()}>Déposer des fichiers</button>
        <input ref={choixFichiers} id="fx-choix-fichiers" type="file" multiple hidden
               onChange={(e) => { if (e.target.files?.length) void deposer(e.target.files); e.target.value = "" }} />
        <button type="button" disabled={!chemin} onClick={() => chemin && copier(chemin)}>Copier le chemin</button>
        <select id="fx-tri" aria-label="Trier" value={tri} onChange={(e) => setTri(e.target.value as Tri)}>
          <option value="nom">Tri : nom</option><option value="date">Tri : plus récent</option><option value="taille">Tri : taille</option>
        </select>
        <input id="fx-recherche" className="fx-recherche" value={motif} onChange={(e) => setMotif(e.target.value)}
               onKeyDown={(e) => { if (e.key === "Enter") chercher() }}
               placeholder={chemin ? "Chercher un nom dans ce dossier…" : "Chercher un nom sur tout le NAS…"} />
      </div>

      {nouveauDossier !== null && (
        <div className="fx-bandeau">
          <input id="fx-nouveau-dossier" autoFocus value={nouveauDossier} onChange={(e) => setNouveauDossier(e.target.value)}
                 placeholder="Nom du nouveau dossier"
                 onKeyDown={(e) => { if (e.key === "Enter") creerDossier(); if (e.key === "Escape") setNouveauDossier(null) }} />
          <button type="button" onClick={creerDossier} disabled={!nouveauDossier.trim()}>Créer</button>
          <button type="button" onClick={() => setNouveauDossier(null)}>Annuler</button>
        </div>
      )}
      {ailleurs && (
        <div className="fx-bandeau" role="status">
          <span><b>{ailleurs.action}</b> se fait dans l'explorateur de fichiers de votre ordinateur (corbeille et annulation y existent). Chemin :</span>
          <code>{ailleurs.chemin}</code>
          <button type="button" onClick={() => copier(ailleurs.chemin)}>Copier</button>
          <button type="button" onClick={() => setAilleurs(null)}>Fermer</button>
        </div>
      )}
      {depot && <div className="fx-note">{depot}</div>}
      {note && <div className="fx-note">{note}</div>}
      {erreur && <div className="fx-erreur">⚠ {erreur}</div>}
      {recherche && (
        <div className="fx-note">{total} résultat(s) pour « {recherche.motif} »{recherche.partiel ? " — recherche partielle" : ""}.{" "}
          <button type="button" className="fx-lien-bouton" onClick={() => aller(chemin)}>Revenir au dossier</button></div>
      )}

      <div className="fx-corps">
        <div className="fx-liste" aria-busy={charge} role="list">
          {charge && <div className="fx-vide">Lecture du NAS…</div>}
          {!charge && tries.length === 0 && !erreur && <div className="fx-vide">Dossier vide. Glissez des fichiers ici pour les déposer.</div>}
          {!charge && tries.map((e) => (
            <div key={e.chemin} role="listitem" className="fx-ligne" data-choisi={ouvert?.chemin === e.chemin ? "oui" : "non"}>
              <button type="button" className="fx-nom" title={e.chemin} onClick={() => (e.dossier ? aller(e.chemin) : ouvrir(e))}>
                <span aria-hidden>{e.dossier ? "📁" : "📄"}</span>
                <span className="fx-nom-texte">{e.nom}
                  {recherche && <small> · {parent(e.chemin)}</small>}</span>
              </button>
              <span className="fx-meta">{e.dossier ? "" : taille(e.octets)}</span>
              <span className="fx-meta fx-date">{date(e.modifie)}</span>
              <details className="fx-menu">
                <summary aria-label={`Actions sur ${e.nom}`}>⋯</summary>
                <div>
                  {!e.dossier && <button type="button" onClick={() => ouvrir(e)}>Aperçu et téléchargement</button>}
                  {e.dossier && <button type="button" onClick={() => aller(e.chemin)}>Ouvrir</button>}
                  <button type="button" onClick={() => copier(e.chemin)}>Copier le chemin</button>
                  {["Renommer", "Déplacer", "Supprimer"].map((a) => (
                    <button key={a} type="button" onClick={() => setAilleurs({ action: a, chemin: e.chemin })}>{a}…</button>
                  ))}
                </div>
              </details>
            </div>
          ))}
        </div>

        {ouvert && (
          <aside className="fx-apercu" aria-label="Aperçu">
            <div className="fx-apercu-tete">
              <strong title={ouvert.chemin}>{ouvert.nom}</strong>
              <button type="button" className="fx-lien-bouton" onClick={() => setOuvert(null)}>Fermer</button>
            </div>
            {!ouvert.bloc && !ouvert.message && <div className="fx-vide">Téléchargement depuis le NAS…</div>}
            {ouvert.message && <div className="fx-note">{ouvert.message}</div>}
            {ouvert.bloc && (
              <MessageRenderer content={"```ui\n" + JSON.stringify(ouvert.bloc) + "\n```"} apiUrl={apiUrl} backendToken={token} dernier />
            )}
          </aside>
        )}
      </div>
    </div>
  )
}
