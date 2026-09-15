"use client"
import { useEffect, useState } from "react"
import { signIn } from "next-auth/react"
import { MarqueDuret } from "@/components/nav/Logo"
import ChoixProfil, { type CarteProfil } from "@/components/nav/ChoixProfil"
import CodeCarte, { messageCode } from "@/components/nav/CodeCarte"

// LA PAGE DE CONNEXION EST UN CHOIX DE PRÉNOM (13/09, demande de Noa, Duret) :
// tout le monde partage la boîte Gmail de l'entreprise, alors l'écran montre
// les cartes des profils, « comme Netflix », et chacun clique sur son nom.
// Depuis le 15/09 il n'y a PLUS DE LIEN MAGIQUE, même pour l'administration :
// le petit bouton « Admin » en bas ouvre les cartes administrateur, à code. L'écran des cartes est TOUJOURS l'écran d'arrivée : sans carte, il
// dit ce qui manque et garde le bouton Admin (relevé de Noa, 13/09 : la page
// basculait seule sur le lien magique quand aucun profil n'existait encore).
type Vue = "chargement" | "cartes" | "admin"

export default function LoginPage() {
  const [vue, setVue] = useState<Vue>("chargement")
  const [profils, setProfils] = useState<CarteProfil[]>([])
  const [enCours, setEnCours] = useState<string | null>(null)
  const [refusCarte, setRefusCarte] = useState("")
  const [raisonVide, setRaisonVide] = useState<string | null>(null)
  // La carte à code en cours de saisie (direction, ou profil qui en a posé un).
  const [aCoder, setACoder] = useState<CarteProfil | null>(null)
  const [erreurCode, setErreurCode] = useState("")
  const [admins, setAdmins] = useState<CarteProfil[] | null>(null)
  const [erreurAdmins, setErreurAdmins] = useState("")

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

  // Les cartes administrateur, lues à l'ouverture de la vue Admin.
  const ouvrirAdmin = async () => {
    setVue("admin"); setRefusCarte(""); setACoder(null); setErreurCode("")
    setAdmins(null); setErreurAdmins("")
    try {
      const r = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/auth/connexion/admins`, { cache: "no-store" })
      const j = r.ok ? await r.json() : null
      setAdmins(Array.isArray(j?.profils) ? j.profils : [])
      if (!r.ok) setErreurAdmins("Le serveur ne répond pas pour le moment. Réessayez dans un instant.")
    } catch {
      setAdmins([]); setErreurAdmins("Le serveur ne répond pas pour le moment. Réessayez dans un instant.")
    }
  }

  const entrerAdmin = async (id: string, code: string) => {
    if (enCours) return
    setEnCours(id)
    try {
      const res = await signIn("credentials", { admin: "1", user_id: id, code, redirect: false })
      if (res?.error) {
        setErreurCode(messageCode(res.code && res.code !== "credentials" ? res.code : undefined))
        return
      }
      window.location.href = "/chat"
    } finally {
      setEnCours(null)
    }
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

  // Le temps d'une requête : ne rien montrer plutôt que faire clignoter un
  // écran vide avant les cartes.
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
            ouvre les cartes administrateur, à code (15/09). */}
        <button type="button" data-testid="bouton-admin" onClick={ouvrirAdmin}
                className="sym-tap"
                style={{ marginTop: 36, background: "none", border: "none", cursor: "pointer", padding: "4px 8px",
                         fontSize: 11, color: "var(--marque-text-muted)", letterSpacing: ".06em", opacity: 0.7 }}>
          Admin
        </button>
      </div>
    )
  }

  // LA VUE ADMIN (15/09, Noa : « enlève le système magic link même en admin,
  // mets un code pour le compte admin, accessible après avoir cliqué sur le
  // bouton Admin »). Les cartes des administrateurs, TOUTES à code : le code
  // posé dans Paramètres → Mon code de connexion, ou celui par défaut tant
  // qu'aucun n'est posé. Le serveur compte les essais (cinq, puis un quart
  // d'heure bloqué).
  return (
    <div style={{ ...fond, flexDirection: "column" }}>
      <div className="sym-in" style={{ marginBottom: 18 }}>
        <MarqueDuret taille={48} />
      </div>
      {aCoder ? (
        <CodeCarte nom={aCoder.nom} enCours={enCours === aCoder.id} erreur={erreurCode}
                   onValider={(code) => entrerAdmin(aCoder.id, code)}
                   onAnnuler={() => { setACoder(null); setErreurCode("") }} />
      ) : admins === null ? (
        <div aria-busy="true" style={{ minHeight: 80 }} />
      ) : admins.length > 0 ? (
        <ChoixProfil profils={admins} onChoisir={(id) => { const c = admins.find((a) => a.id === id); if (c) { setACoder(c); setErreurCode("") } }}
                     enCours={enCours} sousTitre="Administration : choisissez votre compte, puis tapez votre code." />
      ) : (
        <p data-testid="admins-vides" style={{ margin: 0, fontSize: 14, color: "var(--marque-text-muted)", textAlign: "center", maxWidth: 420 }}>
          {erreurAdmins || "Aucun compte administrateur actif."}
        </p>
      )}
      <button type="button" onClick={() => { setVue("cartes"); setACoder(null); setErreurCode("") }} className="sym-tap"
              style={{ marginTop: 28, background: "none", border: "none", cursor: "pointer",
                       fontSize: 13, color: "var(--marque-primary)" }}>
        ← Retour aux profils
      </button>
    </div>
  )
}
