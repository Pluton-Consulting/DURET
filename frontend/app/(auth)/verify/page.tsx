"use client"
import { Suspense, useEffect, useRef, useState } from "react"
import { signIn } from "next-auth/react"
import { useSearchParams } from "next/navigation"
import ChoixProfil, { type CarteProfil } from "@/components/nav/ChoixProfil"

function VerifyContent() {
  const params = useSearchParams()
  const [status, setStatus] = useState<"loading" | "error" | "choix">("loading")
  // LES PRÉNOMS D'UNE BOÎTE PARTAGÉE (11/09, Duret) : plusieurs profils sur
  // l'adresse du lien — on montre les cartes, et c'est le clic qui ouvre la
  // session. Le lien n'est consommé qu'à ce moment-là.
  const [profils, setProfils] = useState<CarteProfil[]>([])
  const [enCours, setEnCours] = useState<string | null>(null)
  // POURQUOI le lien est refusé (08/09). `signIn` de next-auth ne rend qu'un
  // booléen : la raison se demande au serveur, par une route qui ne consomme
  // rien. Sans elle, « Lien invalide ou expiré » couvrait quatre situations
  // dont un compte désactivé — impossible à deviner depuis l'écran.
  const [raison, setRaison] = useState("")
  // Le lien est à usage unique : on garantit un SEUL appel de vérification,
  // même avec le double-rendu de React en dev (sinon le token est consommé 2×).
  const started = useRef(false)

  const ouvrir = (token: string, email: string, userId?: string) =>
    signIn("credentials", { token, email, user_id: userId || "", redirect: false }).then(async (res) => {
      if (res?.error) {
        setStatus("error")
        try {
          const api = process.env.NEXT_PUBLIC_API_URL || ""
          const r = await fetch(`${api}/api/auth/magic-link/etat`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token, email }),
          })
          if (r.ok) {
            const j = await r.json()
            if (j?.message) setRaison(String(j.message))
          }
        } catch { /* le serveur ne répond pas : le message générique suffit */ }
      } else {
        window.location.href = "/chat"
      }
    })

  useEffect(() => {
    if (started.current) return
    const token = params.get("token")
    const email = params.get("email")
    // Le lien remis par un administrateur désigne déjà le prénom : pas de cartes.
    const profil = params.get("profil")

    if (!token || !email) {
      setStatus("error")
      return
    }
    started.current = true
    if (profil) { ouvrir(token, email, profil); return }

    ;(async () => {
      try {
        const api = process.env.NEXT_PUBLIC_API_URL || ""
        const r = await fetch(`${api}/api/auth/magic-link/profils`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token, email }),
        })
        const j = r.ok ? await r.json() : null
        if (Array.isArray(j?.profils) && j.profils.length > 1) {
          setProfils(j.profils)
          setStatus("choix")
          return
        }
      } catch { /* le serveur tranchera : il refuse d'ouvrir sans prénom quand il en faut un */ }
      ouvrir(token, email)
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params])

  const choisir = (id: string) => {
    const token = params.get("token"), email = params.get("email")
    if (!token || !email || enCours) return
    setEnCours(id)
    ouvrir(token, email, id).finally(() => setEnCours(null))
  }

  if (status === "choix") {
    return (
      <div style={{
        minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center",
        padding: "32px 16px", boxSizing: "border-box",
        background: "radial-gradient(circle at 50% -10%, var(--marque-primary-subtle), transparent 55%), var(--marque-canvas)",
      }}>
        <ChoixProfil profils={profils} onChoisir={choisir} enCours={enCours} />
      </div>
    )
  }

  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "radial-gradient(circle at 50% -10%, var(--marque-primary-subtle), transparent 55%), var(--marque-canvas)",
    }}>
      <div className="sym-in sym-card" style={{
        background: "var(--marque-surface)",
        borderRadius: "var(--marque-radius-card)",
        padding: "clamp(24px, 7vw, 40px) clamp(18px, 8vw, 48px)",
        boxShadow: "var(--marque-shadow-card)",
        textAlign: "center",
        maxWidth: 380,
      }}>
        <div className="sym-pop" style={{ width: 46, height: 46, margin: "0 auto 16px", borderRadius: "50%", background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--marque-text-on-dark)", fontSize: 20, fontWeight: 800 }}>D</div>
        {status === "loading" ? (
          <>
            <p className="sym-in sym-in-1" style={{ fontWeight: 500, margin: "0 0 8px", color: "var(--marque-text-primary)" }}>Connexion en cours...</p>
            <p className="sym-in sym-in-2" style={{ color: "var(--marque-text-muted)", fontSize: 13, margin: 0 }}>Vous allez être redirigé automatiquement.</p>
          </>
        ) : (
          <>
            <p className="sym-in sym-in-1" style={{ fontWeight: 500, margin: "0 0 8px", color: "var(--marque-error-text)" }}>Connexion impossible</p>
            <p className="sym-in sym-in-2" style={{ color: "var(--marque-text-muted)", fontSize: 13, margin: "0 0 20px" }}>
              {raison || "Le lien a peut-être déjà été utilisé ou a expiré (15 min)."}
            </p>
            <a href="/login" className="sym-tap sym-in sym-in-3" style={{
              display: "inline-block",
              background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
              color: "var(--marque-text-on-dark)",
              padding: "10px 20px",
              borderRadius: "var(--marque-radius-pill)",
              textDecoration: "none",
              fontSize: 14,
              fontWeight: 500,
              boxShadow: "var(--marque-shadow-card)",
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
