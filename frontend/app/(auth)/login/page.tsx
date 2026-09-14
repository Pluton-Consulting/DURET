"use client"
import { useEffect, useState } from "react"

// L'ADRESSE DE LA DERNIÈRE CONNEXION (03/09, demande de Noa : « sans resaisir
// le mail »). Cet écran ne se voit plus qu'une fois par appareil — la session
// dure ensuite d'elle-même — mais quand il se voit, l'adresse est déjà là.
// C'est un CONFORT, pas une preuve : le lien magique reste envoyé à l'adresse,
// et il faut toujours l'ouvrir. Rien de sensible ne dort donc ici.
const CLE_DERNIER_EMAIL = "pluton.dernier_email"
import { signIn } from "next-auth/react"
import { MarqueDuret } from "@/components/nav/Logo"
import ChoixProfil, { type CarteProfil } from "@/components/nav/ChoixProfil"
import CodeCarte, { messageCode } from "@/components/nav/CodeCarte"

type State = "idle" | "loading" | "sent" | "refused" | "error"

// LA PAGE DE CONNEXION EST UN CHOIX DE PRÉNOM (13/09, demande de Noa, Duret) :
// tout le monde partage la boîte Gmail de l'entreprise, alors l'écran montre
// les cartes des profils, « comme Netflix », et chacun clique sur son nom. Le
// lien magique ne sert plus qu'aux administrateurs, derrière un petit bouton
// en bas. L'écran des cartes est TOUJOURS l'écran d'arrivée : sans carte, il
// dit ce qui manque et garde le bouton Admin (relevé de Noa, 13/09 : la page
// basculait seule sur le lien magique quand aucun profil n'existait encore).
type Vue = "chargement" | "cartes" | "admin"

export default function LoginPage() {
  const [email, setEmail] = useState("")
  const [state, setState] = useState<State>("idle")
  const [error, setError] = useState("")
  const [vue, setVue] = useState<Vue>("chargement")
  const [profils, setProfils] = useState<CarteProfil[]>([])
  const [enCours, setEnCours] = useState<string | null>(null)
  const [refusCarte, setRefusCarte] = useState("")
  const [raisonVide, setRaisonVide] = useState<string | null>(null)
  // La carte à code en cours de saisie (direction, ou profil qui en a posé un).
  const [aCoder, setACoder] = useState<CarteProfil | null>(null)
  const [erreurCode, setErreurCode] = useState("")

  const chargerCartes = async () => {
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/connexion/profils`, { cache: "no-store" })
      const j = r.ok ? await r.json() : null
      const liste: CarteProfil[] = Array.isArray(j?.profils) ? j.profils : []
      setProfils(liste)
      setRaisonVide(j ? (j.raison ?? null) : "serveur")
      return liste
    } catch {
      // Serveur muet : on le dit ; le bouton Admin reste là.
      setProfils([])
      setRaisonVide("serveur")
      return []
    }
  }

  useEffect(() => {
    chargerCartes().then(() => setVue("cartes"))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const entrer = async (id: string, code?: string) => {
    if (enCours) return
    const carte = profils.find((p) => p.id === id)
    if (carte?.code && !code) { setACoder(carte); setErreurCode(""); return }
    setEnCours(id)
    setRefusCarte("")
    try {
      const res = await signIn("credentials", { carte: "1", user_id: id, code: code || "", redirect: false })
      if (res?.error && carte?.code && res.code && res.code !== "credentials") {
        setErreurCode(messageCode(res.code))
        return
      }
      if (res?.error) {
        setACoder(null)
        // Le profil a pu être désactivé ou déplacé depuis l'affichage : on
        // relit les cartes plutôt que de laisser un bouton mort à l'écran.
        setRefusCarte("Ce profil ne s'ouvre pas depuis cette page. Choisissez de nouveau, ou demandez à un administrateur.")
        await chargerCartes()
        return
      }
      window.location.href = "/chat"
    } finally {
      setEnCours(null)
    }
  }

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

  const fond: React.CSSProperties = {
    minHeight: "100vh",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "32px 16px",
    boxSizing: "border-box",
    background: "radial-gradient(circle at 50% -10%, var(--marque-primary-subtle), transparent 55%), var(--marque-canvas)",
  }

  // Le temps d'une requête : ne rien montrer plutôt que faire clignoter le
  // formulaire du lien magique avant les cartes.
  if (vue === "chargement") return <div style={fond} aria-busy="true" />

  if (vue === "cartes") {
    return (
      <div style={{ ...fond, flexDirection: "column" }}>
        <div className="sym-in" style={{ marginBottom: 18 }}>
          <MarqueDuret taille={48} />
        </div>
        {aCoder ? (
          <CodeCarte nom={aCoder.nom} enCours={enCours === aCoder.id} erreur={erreurCode}
                     onValider={(code) => entrer(aCoder.id, code)}
                     onAnnuler={() => { setACoder(null); setErreurCode("") }} />
        ) : profils.length > 0 ? (
        <ChoixProfil profils={profils} onChoisir={(id) => entrer(id)} enCours={enCours}
                     sousTitre="Choisissez votre nom pour retrouver vos conversations, vos documents et vos mails." />
        ) : (
          <div data-testid="cartes-vides" className="sym-in" style={{ maxWidth: 440, textAlign: "center" }}>
            <h1 style={{ margin: "0 0 8px", fontSize: 24, fontWeight: 800, color: "var(--marque-text-primary)" }}>Qui êtes-vous ?</h1>
            <p style={{ margin: 0, fontSize: 14, color: "var(--marque-text-muted)", lineHeight: 1.5 }}>
              {raisonVide === "boite_absente"
                ? "Aucun profil à afficher : la boîte mail de l'entreprise n'est pas encore reliée. Un administrateur l'enregistre dans Paramètres → Clés API, puis crée les profils dans Paramètres → Utilisateurs."
                : raisonVide === "serveur"
                ? "Le serveur ne répond pas pour le moment. Réessayez dans un instant."
                : "Aucun profil n'est encore créé. Un administrateur les ajoute dans Paramètres → Utilisateurs (la boîte mail peut être reliée plus tard)."}
            </p>
          </div>
        )}
        {refusCarte && (
          <p className="sym-pop" style={{ color: "var(--marque-error-text)", fontSize: 13, margin: "18px 0 0", textAlign: "center" }}>
            {refusCarte}
          </p>
        )}
        {/* Le petit bouton des administrateurs : volontairement discret, il
            ouvre le lien magique d'aujourd'hui. */}
        <button type="button" data-testid="bouton-admin" onClick={() => { setVue("admin"); setRefusCarte("") }}
                className="sym-tap"
                style={{ marginTop: 36, background: "none", border: "none", cursor: "pointer", padding: "4px 8px",
                         fontSize: 11, color: "var(--marque-text-muted)", letterSpacing: ".06em", opacity: 0.7 }}>
          Admin
        </button>
      </div>
    )
  }

  return (
    <div style={{ ...fond, flexDirection: "column" }}>
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
          Connexion administrateur par lien magique
        </p>
      </div>
      {(
        <button type="button" onClick={() => setVue("cartes")} className="sym-tap"
                style={{ marginTop: 20, background: "none", border: "none", cursor: "pointer",
                         fontSize: 13, color: "var(--marque-primary)" }}>
          ← Retour aux profils
        </button>
      )}
    </div>
  )
}
