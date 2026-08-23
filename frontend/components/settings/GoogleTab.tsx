"use client"
// Ma boîte Google — la « sous-connexion » de chaque utilisateur.
//
// On se connecte à l'application par lien magique ; ICI, chacun relie SA boîte
// Google (consentement OAuth individuel, chez Google). Une fois reliée, la
// connexion tient toute seule : le serveur garde un refresh token, jamais
// montré à l'écran. Cet onglet est le seul de Paramètres ouvert à TOUS les
// rôles — il ne parle que de la boîte de la personne connectée.
import { useEffect, useState } from "react"

interface Etat {
  disponible: boolean
  connecte: boolean
  email?: string | null
  depuis?: string | null
}

export default function GoogleTab({ apiUrl, backendToken, currentRole }:
  { apiUrl: string; backendToken: string; currentRole: string }) {
  const [etat, setEtat] = useState<Etat | null>(null)
  const [notice, setNotice] = useState<{ ton: "ok" | "souci"; texte: string } | null>(null)
  const [occupe, setOccupe] = useState(false)

  const entetes = { Authorization: `Bearer ${backendToken}` }

  const charger = () =>
    fetch(`${apiUrl}/api/google/etat`, { headers: entetes })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setEtat(d) })
      .catch(() => {})

  useEffect(() => {
    charger()
    // L'issue du parcours OAuth revient dans l'URL (?google=...) : on la dit
    // en clair, puis on la retire de l'URL pour qu'un rechargement ne la
    // répète pas comme si elle venait d'arriver.
    const issue = new URLSearchParams(window.location.search).get("google")
    if (issue === "connecte") setNotice({ ton: "ok", texte: "Votre boîte Google est reliée." })
    else if (issue === "refuse") setNotice({ ton: "souci", texte: "Connexion annulée chez Google : rien n'a été relié." })
    else if (issue === "erreur") setNotice({ ton: "souci", texte: "La connexion n'a pas abouti. Réessayez ; si cela persiste, prévenez votre administrateur." })
    if (issue) {
      try { window.history.replaceState(null, "", window.location.pathname) } catch { /* rien */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const connecter = async () => {
    setOccupe(true)
    try {
      const r = await fetch(`${apiUrl}/api/google/lien`, { headers: entetes })
      const d = await r.json()
      if (r.ok && d.url) { window.location.href = d.url; return }
      setNotice({ ton: "souci", texte: d.detail || "Le lien de connexion n'a pas pu être obtenu." })
    } catch {
      setNotice({ ton: "souci", texte: "Le serveur n'a pas répondu. Réessayez." })
    } finally {
      setOccupe(false)
    }
  }

  const deconnecter = async () => {
    if (!window.confirm("Détacher votre boîte Google de l'assistant ?")) return
    setOccupe(true)
    try {
      await fetch(`${apiUrl}/api/google/`, { method: "DELETE", headers: entetes })
      setNotice({ ton: "ok", texte: "Boîte détachée. Vous pouvez la relier à tout moment." })
      await charger()
    } catch {
      setNotice({ ton: "souci", texte: "La déconnexion n'a pas abouti. Réessayez." })
    } finally {
      setOccupe(false)
    }
  }

  const carte: React.CSSProperties = {
    maxWidth: 560, padding: "1.25rem 1.5rem", borderRadius: 12,
    border: "1px solid var(--border, #e2e2e2)", background: "var(--card, transparent)",
  }
  const bouton: React.CSSProperties = {
    padding: "0.55rem 1.1rem", borderRadius: 8, cursor: occupe ? "wait" : "pointer",
    border: "1px solid var(--border, #d0d0d0)", fontWeight: 600,
  }

  return (
    <div>
      <h2 style={{ fontSize: "1.05rem", fontWeight: 700, marginBottom: "0.75rem" }}>Ma boîte Google</h2>
      {notice && (
        <p role="status" style={{ marginBottom: "0.9rem", fontWeight: 600,
          color: notice.ton === "ok" ? "var(--marque, inherit)" : "#b3261e" }}>
          {notice.texte}
        </p>
      )}
      <div style={carte}>
        {etat === null ? (
          <p>Chargement…</p>
        ) : !etat.disponible ? (
          // Pas configuré côté serveur : le collaborateur n'y peut rien, on ne
          // lui montre pas des noms de variables ; l'administrateur, si.
          <p style={{ opacity: 0.85 }}>
            {currentRole === "super_admin"
              ? "Le client OAuth Google n'est pas configuré : renseignez GOOGLE_OAUTH_CLIENT_ID et GOOGLE_OAUTH_CLIENT_SECRET côté serveur."
              : "La connexion Google n'est pas encore activée sur cette application. Votre administrateur doit la configurer."}
          </p>
        ) : etat.connecte ? (
          <>
            <p style={{ marginBottom: "0.35rem" }}>
              Boîte reliée : <b>{etat.email}</b>
            </p>
            {etat.depuis && (
              <p style={{ opacity: 0.7, fontSize: "0.85rem", marginBottom: "0.9rem" }}>
                depuis le {new Date(etat.depuis).toLocaleDateString("fr-FR")}
              </p>
            )}
            <p style={{ opacity: 0.85, fontSize: "0.9rem", marginBottom: "0.9rem" }}>
              L'assistant peut lire vos messages quand vous le lui demandez. La
              connexion se maintient toute seule : rien à refaire.
            </p>
            <button type="button" onClick={deconnecter} disabled={occupe} style={bouton}>
              Détacher ma boîte
            </button>
          </>
        ) : (
          <>
            <p style={{ marginBottom: "0.9rem", opacity: 0.9 }}>
              Reliez votre boîte Google pour que l'assistant puisse lire vos
              messages quand vous le lui demandez. Vous donnerez votre accord
              chez Google, une seule fois — ensuite la connexion tient toute
              seule, et vous pouvez la détacher ici à tout moment.
            </p>
            <button type="button" onClick={connecter} disabled={occupe} style={bouton}>
              {occupe ? "Ouverture…" : "Connecter ma boîte Google"}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
