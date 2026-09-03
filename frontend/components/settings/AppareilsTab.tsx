"use client"
// MES APPAREILS — la contrepartie d'une session qui ne périme plus.
//
// Depuis le 03/09, un poste sur lequel on s'est connecté une fois le reste :
// plus de mail à retaper, plus de lien magique à ouvrir chaque jour. Ce
// confort n'est acceptable qu'à une condition — VOIR ce qui reste ouvert, et
// pouvoir le fermer. C'est tout l'objet de cet écran.
//
// Le jeton d'un appareil n'apparaît nulle part ici : le serveur n'en garde
// qu'une empreinte, et l'écran ne montre que ce qui aide à se reconnaître —
// « Chrome sur Mac », depuis quand, dernier usage.
//
// Ouvert à TOUS les rôles, comme « Mon compte Google » : il ne parle que du
// compte de la personne connectée.
import { useEffect, useState } from "react"

interface Appareil {
  id: string
  appareil: string
  depuis: string | null
  derniere_utilisation: string | null
  expire_le: string | null
}

interface Etat {
  disponible: boolean
  appareils: Appareil[]
  migration_absente?: string | null
}

function quand(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  const minutes = Math.round((Date.now() - d.getTime()) / 60000)
  if (minutes < 2) return "à l'instant"
  if (minutes < 60) return `il y a ${minutes} min`
  if (minutes < 60 * 24) return `il y a ${Math.round(minutes / 60)} h`
  return `le ${d.toLocaleDateString("fr-FR")}`
}

export default function AppareilsTab({ apiUrl, backendToken, currentRole }:
  { apiUrl: string; backendToken: string; currentRole: string }) {
  const [etat, setEtat] = useState<Etat | null>(null)
  const [notice, setNotice] = useState<{ ton: "ok" | "souci"; texte: string } | null>(null)
  const [occupe, setOccupe] = useState(false)

  const entetes = { Authorization: `Bearer ${backendToken}` }

  const charger = () =>
    fetch(`${apiUrl}/api/auth/appareils`, { headers: entetes })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (d) setEtat(d) })
      .catch(() => {})

  useEffect(() => { charger() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [])

  const fermer = async (id: string) => {
    if (!window.confirm("Fermer cet appareil ? Il faudra un nouveau lien de connexion pour y revenir.")) return
    setOccupe(true)
    try {
      await fetch(`${apiUrl}/api/auth/appareils/${id}`, { method: "DELETE", headers: entetes })
      setNotice({ ton: "ok", texte: "Appareil fermé." })
      await charger()
    } catch {
      setNotice({ ton: "souci", texte: "La fermeture n'a pas abouti. Réessayez." })
    } finally {
      setOccupe(false)
    }
  }

  const toutFermer = async () => {
    if (!window.confirm(
      "Fermer TOUS vos appareils, y compris celui-ci ? Vous devrez vous reconnecter par lien de connexion."
    )) return
    setOccupe(true)
    try {
      await fetch(`${apiUrl}/api/auth/appareils/tout-fermer`, { method: "POST", headers: entetes })
      // Celui-ci en fait partie : le dire, et laisser la page se rendre à la
      // connexion d'elle-même au prochain geste plutôt que de la couper net.
      setNotice({ ton: "ok", texte: "Tous vos appareils sont fermés. Cet onglet vous renverra à la connexion." })
      await charger()
    } catch {
      setNotice({ ton: "souci", texte: "La fermeture n'a pas abouti. Réessayez." })
    } finally {
      setOccupe(false)
    }
  }

  const carte: React.CSSProperties = {
    maxWidth: 560, padding: "1.25rem 1.5rem", borderRadius: 12,
    border: "1px solid var(--border, #e2e2e2)", background: "var(--card, transparent)",
  }
  const bouton: React.CSSProperties = {
    padding: "0.35rem 0.8rem", borderRadius: 8, cursor: occupe ? "wait" : "pointer",
    border: "1px solid var(--border, #d0d0d0)", fontWeight: 600, fontSize: "0.85rem",
    background: "transparent",
  }

  return (
    <div>
      <h2 style={{ fontSize: "1.05rem", fontWeight: 700, marginBottom: "0.35rem" }}>Mes appareils</h2>
      <p style={{ opacity: 0.75, fontSize: "0.9rem", marginBottom: "0.9rem", maxWidth: 560 }}>
        Un appareil sur lequel vous vous êtes connecté une fois le reste : ni adresse à
        retaper, ni lien de connexion à ouvrir. Fermez ici ceux que vous ne reconnaissez
        pas, ou ceux que vous n'utilisez plus.
      </p>
      {notice && (
        <p role="status" style={{ marginBottom: "0.9rem", fontWeight: 600,
          color: notice.ton === "ok" ? "var(--marque, inherit)" : "#b3261e" }}>
          {notice.texte}
        </p>
      )}
      <div style={carte}>
        {etat === null ? (
          <p>Chargement…</p>
        ) : etat.migration_absente ? (
          // « Je ne peux pas le savoir » ne se dit pas comme « aucun appareil ».
          <p style={{ opacity: 0.85 }}>
            {currentRole === "super_admin"
              ? "La table des sessions d'appareil n'existe pas encore sur ce serveur : appliquez la migration 034, puis rechargez la page."
              : "La liste des appareils n'est pas encore installée sur cette application. Votre administrateur doit terminer la mise en service."}
          </p>
        ) : etat.appareils.length === 0 ? (
          <p style={{ opacity: 0.85 }}>
            Aucun appareil enregistré. Le prochain lien de connexion que vous ouvrirez en
            posera un.
          </p>
        ) : (
          <>
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {etat.appareils.map((a) => (
                <li key={a.id} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  gap: 12, padding: "0.7rem 0", borderBottom: "1px solid var(--border, #ececec)",
                }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{a.appareil}</div>
                    <div style={{ opacity: 0.7, fontSize: "0.82rem" }}>
                      dernier usage {quand(a.derniere_utilisation)}
                      {a.depuis && ` · connecté depuis le ${new Date(a.depuis).toLocaleDateString("fr-FR")}`}
                    </div>
                  </div>
                  <button type="button" style={bouton} disabled={occupe} onClick={() => fermer(a.id)}>
                    Fermer
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" style={{ ...bouton, marginTop: "1rem" }} disabled={occupe} onClick={toutFermer}>
              Fermer tous mes appareils
            </button>
          </>
        )}
      </div>
    </div>
  )
}
