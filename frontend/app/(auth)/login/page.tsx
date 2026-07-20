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
    background: "white",
    borderRadius: 16,
    padding: "40px 48px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
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
      background: "var(--color-canvas)",
    }}>
      <div style={card}>
        <div style={{ textAlign: "center", margin: "0 auto 32px" }}>
          <span style={{ fontSize: 30, fontWeight: 800, color: "var(--color-primary)", letterSpacing: "-0.02em" }}>
            Duret <span style={{ color: "var(--color-primary-mid)" }}>&amp; Sols</span>
          </span>
        </div>

        {state === "sent" && (
          <div>
            <div style={{ fontSize: 40, marginBottom: 16 }}>📬</div>
            <p style={{ fontWeight: 500, margin: "0 0 8px" }}>Vérifiez votre boîte mail</p>
            <p style={{ color: "#888", fontSize: 13, margin: "0 0 24px" }}>
              Un lien de connexion a été envoyé à<br />
              <strong>{email}</strong>
            </p>
            <button
              onClick={() => { setState("idle"); setEmail("") }}
              style={{ color: "#304D32", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}
            >
              Utiliser un autre email
            </button>
          </div>
        )}

        {state === "refused" && (
          <div>
            <div style={{ fontSize: 40, marginBottom: 16 }}>🔒</div>
            <p style={{ fontWeight: 500, margin: "0 0 8px", color: "#c53030" }}>Accès non autorisé</p>
            <p style={{ color: "#888", fontSize: 13, margin: "0 0 24px" }}>
              L'adresse <strong>{email}</strong> n'est pas enregistrée.<br />
              Contactez votre administrateur.
            </p>
            <button
              onClick={() => { setState("idle"); setEmail("") }}
              style={{ color: "#304D32", background: "none", border: "none", cursor: "pointer", fontSize: 13 }}
            >
              Essayer un autre email
            </button>
          </div>
        )}

        {(state === "idle" || state === "loading" || state === "error") && (
          <form onSubmit={handleSubmit}>
            <input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="votre@email.fr"
              required
              style={{
                width: "100%",
                padding: "10px 14px",
                border: "1px solid #ddd",
                borderRadius: 8,
                fontSize: 14,
                marginBottom: 12,
                boxSizing: "border-box",
                outline: "none",
              }}
            />
            {error && (
              <p style={{ color: "#e53e3e", fontSize: 13, margin: "0 0 12px" }}>{error}</p>
            )}
            <button
              type="submit"
              disabled={state === "loading"}
              style={{
                width: "100%",
                padding: "12px 24px",
                background: "#304D32",
                color: "white",
                border: "none",
                borderRadius: 8,
                fontSize: 14,
                fontWeight: 500,
                cursor: state === "loading" ? "not-allowed" : "pointer",
                opacity: state === "loading" ? 0.7 : 1,
              }}
            >
              {state === "loading" ? "Vérification..." : "Recevoir un lien de connexion"}
            </button>
          </form>
        )}

        <p style={{ color: "#aaa", fontSize: 11, margin: "24px 0 0" }}>
          Accès réservé aux collaborateurs Duret & Sols
        </p>
      </div>
    </div>
  )
}
