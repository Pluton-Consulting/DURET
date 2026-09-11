"use client"
import { useEffect, useState } from "react"
import Link from "next/link"
import { signIn, useSession } from "next-auth/react"
import ChoixProfil, { type CarteProfil } from "@/components/nav/ChoixProfil"

/**
 * CHANGER DE PROFIL (11/09, Duret). Les cartes des prénoms de la boîte
 * partagée, sans nouveau lien magique : le profil courant a déjà prouvé la
 * boîte. Le serveur ne rend que les prénoms de la MÊME adresse, jamais un
 * administrateur ; le clic ouvre une session à ce prénom sur cet appareil.
 */
export default function PageProfil() {
  const { data: session } = useSession()
  const [profils, setProfils] = useState<CarteProfil[] | null>(null)
  const [actuel, setActuel] = useState<string | null>(null)
  const [enCours, setEnCours] = useState<string | null>(null)
  const [erreur, setErreur] = useState("")
  const jeton = (session as any)?.backendToken as string | undefined

  useEffect(() => {
    if (!jeton) return
    const api = process.env.NEXT_PUBLIC_API_URL || ""
    fetch(`${api}/api/auth/profils`, { headers: { Authorization: `Bearer ${jeton}` }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => { setProfils(j.profils || []); setActuel(j.actuel || null) })
      .catch((e) => setErreur(e?.message || "profils indisponibles"))
  }, [jeton])

  const choisir = async (id: string) => {
    if (!jeton || enCours) return
    if (id === actuel) { window.location.href = "/chat"; return }
    setEnCours(id); setErreur("")
    const res = await signIn("credentials", { bascule: jeton, user_id: id, redirect: false })
    if (res?.error) {
      setEnCours(null)
      setErreur("Ce profil n'a pas pu être ouvert. Réessayez ; si cela persiste, prévenez un administrateur.")
      return
    }
    window.location.href = "/chat"
  }

  return (
    <div style={{ minHeight: "calc(100dvh - 120px)", display: "flex", alignItems: "center",
                  justifyContent: "center", padding: "32px 16px", boxSizing: "border-box" }}>
      {profils === null && !erreur && (
        <p style={{ color: "var(--marque-text-muted)", fontSize: 14 }}>Chargement des profils…</p>
      )}
      {profils !== null && profils.length > 1 && (
        <ChoixProfil profils={profils} onChoisir={choisir} enCours={enCours} actuel={actuel}
                     titre="Changer de profil"
                     sousTitre="Chaque prénom a ses conversations, ses documents et ses dossiers de mail." />
      )}
      {profils !== null && profils.length <= 1 && (
        <div style={{ textAlign: "center" }}>
          <p style={{ color: "var(--marque-text-body)", fontSize: 14, margin: "0 0 14px" }}>
            Ce compte n'a pas d'autre profil sur son adresse.
          </p>
          <Link href="/chat" className="sym-tap" style={{ color: "var(--marque-primary)", fontSize: 14 }}>Revenir au chat</Link>
        </div>
      )}
      {erreur && (
        <p style={{ position: "fixed", bottom: 24, left: 16, right: 16, textAlign: "center",
                    color: "var(--marque-error-text)", fontSize: 13 }}>⚠ {erreur}</p>
      )}
    </div>
  )
}
