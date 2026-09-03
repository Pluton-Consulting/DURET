"use client"
import { useEffect, useState } from "react"

// L'ADRESSE DE LA DERNIÈRE CONNEXION (03/09, demande de Noa : « sans resaisir
// le mail »). Cet écran ne se voit plus qu'une fois par appareil — la session
// dure ensuite d'elle-même — mais quand il se voit, l'adresse est déjà là.
// C'est un CONFORT, pas une preuve : le lien magique reste envoyé à l'adresse,
// et il faut toujours l'ouvrir. Rien de sensible ne dort donc ici.
const CLE_DERNIER_EMAIL = "pluton.dernier_email"
import { MarqueDuret } from "@/components/nav/Logo"

type State = "idle" | "loading" | "sent" | "refused" | "error"

export default function LoginPage() {
  const [email, setEmail] = useState("")
  const [state, setState] = useState<State>("idle")
  const [error, setError] = useState("")

  // Après le rendu, jamais pendant : lire le stockage local au premier rendu
  // ferait diverger le HTML du serveur et celui du navigateur (hydratation).
  useEffect(() => {
    try {
      const retenu = window.localStorage.getItem(CLE_DERNIER_EMAIL)
      if (retenu) setEmail(retenu)
    } catch {
      // Navigation privée, stockage refusé : l'écran marche comme avant.
    }
  }, [])

  // « Utiliser un autre email » doit vraiment vider le champ — sinon le
  // pré-remplissage le remettrait et le bouton ne servirait à rien.
  const changerDAdresse = () => {
    try { window.localStorage.removeItem(CLE_DERNIER_EMAIL) } catch { /* rien */ }
    setState("idle")
    setEmail("")
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim()) return
    setState("loading")
    setError("")

    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/auth/magic-link/request`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: email.trim() }),
        }
      )
      if (!res.ok) throw new Error()
      // Réponse volontairement uniforme côté serveur (anti-énumération de comptes) :
      // on affiche toujours "email envoyé", qu'il existe ou non.
      try { window.localStorage.setItem(CLE_DERNIER_EMAIL, email.trim()) } catch { /* rien */ }
      setState("sent")
    } catch {
      setError("Une erreur est survenue. Réessayez.")
      setState("error")
    }
  }

  const card: React.CSSProperties = {
    background: "var(--marque-surface)",
    borderRadius: "var(--marque-radius-card)",
    padding: "clamp(24px, 7vw, 40px) clamp(18px, 8vw, 48px)",
    boxShadow: "var(--marque-shadow-card)",
    textAlign: "center",
    maxWidth: 380,
    width: "100%",
  }

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "radial-gradient(circle at 50% -10%, var(--marque-primary-subtle), transparent 55%), var(--marque-canvas)",
    }}>
      <div className="sym-in sym-card" style={card}>
        {/* La marque en grand : c'est le premier écran, et le seul avant
            l'authentification. Elle se déplie ici verticalement — le symbole
            au-dessus du nom — pour tenir dans la largeur de la carte. */}
        <div className="sym-in sym-in-1" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, margin: "0 auto 32px" }}>
          <MarqueDuret taille={54} />
          <span style={{ fontSize: 28, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-0.02em", lineHeight: 1 }}>
            Duret <span style={{ color: "var(--marque-brand-blue)" }}>&amp; Sols</span>
          </span>
        </div>

        {state === "sent" && (
          <div className="sym-fade">
            <div className="sym-pop" style={{ fontSize: 40, marginBottom: 16 }}>📬</div>
            <p className="sym-in sym-in-1" style={{ fontWeight: 500, margin: "0 0 8px", color: "var(--marque-text-primary)" }}>Vérifiez votre boîte mail</p>
            <p className="sym-in sym-in-2" style={{ color: "var(--marque-text-muted)", fontSize: 13, margin: "0 0 24px" }}>
              Un lien de connexion a été envoyé à<br />
              <strong>{email}</strong>
            </p>
            <button
              onClick={changerDAdresse}
              className="sym-tap sym-in sym-in-3"
              style={{ color: "var(--marque-primary)", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}
            >
              Utiliser un autre email
            </button>
          </div>
        )}

        {state === "refused" && (
          <div className="sym-fade">
            <div className="sym-pop" style={{ fontSize: 40, marginBottom: 16 }}>🔒</div>
            <p className="sym-in sym-in-1" style={{ fontWeight: 500, margin: "0 0 8px", color: "var(--marque-error-text)" }}>Accès non autorisé</p>
            <p className="sym-in sym-in-2" style={{ color: "var(--marque-text-muted)", fontSize: 13, margin: "0 0 24px" }}>
              L'adresse <strong>{email}</strong> n'est pas enregistrée.<br />
              Contactez votre administrateur.
            </p>
            <button
              onClick={changerDAdresse}
              className="sym-tap sym-in sym-in-3"
              style={{ color: "var(--marque-primary)", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}
            >
              Essayer un autre email
            </button>
          </div>
        )}

        {(state === "idle" || state === "loading" || state === "error") && (
          <form className="sym-fade" onSubmit={handleSubmit}>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="votre@email.fr"
              required
              className="sym-in sym-in-1"
              style={{
                width: "100%",
                padding: "10px 14px",
                border: "1px solid var(--marque-border)",
                borderRadius: "var(--marque-radius-pill)",
                fontSize: 14,
                marginBottom: 12,
                boxSizing: "border-box",
                outline: "none",
                transition: "border-color .2s ease, box-shadow .2s ease",
              }}
            />
            {error && (
              <p className="sym-pop" style={{ color: "var(--marque-error-text)", fontSize: 13, margin: "0 0 12px" }}>{error}</p>
            )}
            <button
              type="submit"
              disabled={state === "loading"}
              className="sym-tap sym-in sym-in-2"
              style={{
                width: "100%",
                padding: "12px 24px",
                background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
                color: "var(--marque-text-on-dark)",
                border: "none",
                borderRadius: "var(--marque-radius-pill)",
                fontSize: 14,
                fontWeight: 500,
                cursor: state === "loading" ? "not-allowed" : "pointer",
                opacity: state === "loading" ? 0.7 : 1,
                boxShadow: "var(--marque-shadow-card)",
              }}
            >
              {state === "loading" ? "Vérification..." : "Recevoir un lien de connexion"}
            </button>
          </form>
        )}

        <p className="sym-in sym-in-4" style={{ color: "var(--marque-text-muted)", fontSize: 11, margin: "24px 0 0", letterSpacing: ".04em" }}>
          Accès réservé aux collaborateurs Duret & Sols
        </p>
      </div>
    </div>
  )
}
