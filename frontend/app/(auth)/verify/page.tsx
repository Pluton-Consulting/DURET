"use client"
import { Suspense, useEffect, useRef, useState } from "react"
import { signIn } from "next-auth/react"
import { useSearchParams } from "next/navigation"

function VerifyContent() {
  const params = useSearchParams()
  const [status, setStatus] = useState<"loading" | "error">("loading")
  // Le lien est à usage unique : on garantit un SEUL appel de vérification,
  // même avec le double-rendu de React en dev (sinon le token est consommé 2×).
  const started = useRef(false)

  useEffect(() => {
    if (started.current) return
    const token = params.get("token")
    const email = params.get("email")

    if (!token || !email) {
      setStatus("error")
      return
    }
    started.current = true

    signIn("credentials", { token, email, redirect: false }).then((res) => {
      if (res?.error) {
        setStatus("error")
      } else {
        window.location.href = "/chat"
      }
    })
  }, [params])

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "radial-gradient(circle at 50% -10%, var(--color-primary-subtle), transparent 55%), var(--color-canvas)",
    }}>
      <div className="sym-in sym-card" style={{
        background: "var(--color-surface)",
        borderRadius: "var(--radius-card)",
        padding: "40px 48px",
        boxShadow: "var(--shadow-card)",
        textAlign: "center",
        maxWidth: 380,
      }}>
        <div className="sym-pop" style={{ width: 46, height: 46, margin: "0 auto 16px", borderRadius: "50%", background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-text-on-dark)", fontSize: 20, fontWeight: 800 }}>D</div>
        {status === "loading" ? (
          <>
            <p className="sym-in sym-in-1" style={{ fontWeight: 500, margin: "0 0 8px", color: "var(--color-text-primary)" }}>Connexion en cours...</p>
            <p className="sym-in sym-in-2" style={{ color: "var(--color-text-muted)", fontSize: 13, margin: 0 }}>Vous allez être redirigé automatiquement.</p>
          </>
        ) : (
          <>
            <p className="sym-in sym-in-1" style={{ fontWeight: 500, margin: "0 0 8px", color: "var(--color-error-text)" }}>Lien invalide ou expiré</p>
            <p className="sym-in sym-in-2" style={{ color: "var(--color-text-muted)", fontSize: 13, margin: "0 0 20px" }}>
              Le lien a peut-être déjà été utilisé ou a expiré (15 min).
            </p>
            <a href="/login" className="sym-tap sym-in sym-in-3" style={{
              display: "inline-block",
              background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
              color: "var(--color-text-on-dark)",
              padding: "10px 20px",
              borderRadius: "var(--radius-pill)",
              textDecoration: "none",
              fontSize: 14,
              fontWeight: 500,
              boxShadow: "var(--shadow-card)",
            }}>
              Demander un nouveau lien
            </a>
          </>
        )}
      </div>
    </div>
  )
}

export default function VerifyPage() {
  return (
    <Suspense>
      <VerifyContent />
    </Suspense>
  )
}
