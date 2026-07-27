"use client"
import { useState } from "react"

type State = "idle" | "loading" | "sent" | "refused" | "error"

export default function LoginPage() {
  const [email, setEmail] = useState("")
  const [state, setState] = useState<State>("idle")
  const [error, setError] = useState("")

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
      setState("sent")
    } catch {
      setError("Une erreur est survenue. Réessayez.")
      setState("error")
    }
  }

  const card: React.CSSProperties = {
    background: "var(--color-surface)",
    borderRadius: "var(--radius-card)",
    padding: "40px 48px",
    boxShadow: "var(--shadow-card)",
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
      background: "radial-gradient(circle at 50% -10%, var(--color-primary-subtle), transparent 55%), var(--color-canvas)",
    }}>
      <div className="sym-in sym-card" style={card}>
        <div className="sym-in sym-in-1" style={{ textAlign: "center", margin: "0 auto 32px" }}>
          <span style={{ fontSize: 30, fontWeight: 800, color: "var(--color-primary)", letterSpacing: "-0.02em" }}>
            Duret <span style={{ color: "var(--color-primary-mid)" }}>&amp; Sols</span>
          </span>
        </div>

        {state === "sent" && (
          <div className="sym-fade">
            <div className="sym-pop" style={{ fontSize: 40, marginBottom: 16 }}>📬</div>
            <p className="sym-in sym-in-1" style={{ fontWeight: 500, margin: "0 0 8px", color: "var(--color-text-primary)" }}>Vérifiez votre boîte mail</p>
            <p className="sym-in sym-in-2" style={{ color: "var(--color-text-muted)", fontSize: 13, margin: "0 0 24px" }}>
              Un lien de connexion a été envoyé à<br />
              <strong>{email}</strong>
            </p>
            <button
              onClick={() => { setState("idle"); setEmail("") }}
              className="sym-tap sym-in sym-in-3"
              style={{ color: "var(--color-primary)", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}
            >
              Utiliser un autre email
            </button>
          </div>
        )}

        {state === "refused" && (
          <div className="sym-fade">
            <div className="sym-pop" style={{ fontSize: 40, marginBottom: 16 }}>🔒</div>
            <p className="sym-in sym-in-1" style={{ fontWeight: 500, margin: "0 0 8px", color: "var(--color-error-text)" }}>Accès non autorisé</p>
            <p className="sym-in sym-in-2" style={{ color: "var(--color-text-muted)", fontSize: 13, margin: "0 0 24px" }}>
              L'adresse <strong>{email}</strong> n'est pas enregistrée.<br />
              Contactez votre administrateur.
            </p>
            <button
              onClick={() => { setState("idle"); setEmail("") }}
              className="sym-tap sym-in sym-in-3"
              style={{ color: "var(--color-primary)", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}
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
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius-pill)",
                fontSize: 14,
                marginBottom: 12,
                boxSizing: "border-box",
                outline: "none",
                transition: "border-color .2s ease, box-shadow .2s ease",
              }}
            />
            {error && (
              <p className="sym-pop" style={{ color: "var(--color-error-text)", fontSize: 13, margin: "0 0 12px" }}>{error}</p>
            )}
            <button
              type="submit"
              disabled={state === "loading"}
              className="sym-tap sym-in sym-in-2"
              style={{
                width: "100%",
                padding: "12px 24px",
                background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
                color: "var(--color-text-on-dark)",
                border: "none",
                borderRadius: "var(--radius-pill)",
                fontSize: 14,
                fontWeight: 500,
                cursor: state === "loading" ? "not-allowed" : "pointer",
                opacity: state === "loading" ? 0.7 : 1,
                boxShadow: "var(--shadow-card)",
              }}
            >
              {state === "loading" ? "Vérification..." : "Recevoir un lien de connexion"}
            </button>
          </form>
        )}

        <p className="sym-in sym-in-4" style={{ color: "var(--color-text-muted)", fontSize: 11, margin: "24px 0 0", letterSpacing: ".04em" }}>
          Accès réservé aux collaborateurs Duret & Sols
        </p>
      </div>
    </div>
  )
}
