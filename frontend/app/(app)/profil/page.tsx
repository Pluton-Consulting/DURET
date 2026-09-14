"use client"
import { useEffect, useState } from "react"
import Link from "next/link"
import { signIn, useSession } from "next-auth/react"
import ChoixProfil, { type CarteProfil } from "@/components/nav/ChoixProfil"
import CodeCarte, { messageCode } from "@/components/nav/CodeCarte"
import MonCode from "@/components/settings/MonCode"

/**
 * MON PROFIL (Duret).
 *
 * 1. LE CODE DE MA CARTE (14/09, Noa : « chacun doit pouvoir modifier le sien
 *    depuis son espace »). La session prouve déjà la personne : on voit son
 *    code, on le change, on le retire — sauf la direction sur une adresse
 *    partagée, dont la carte n'existe pas sans code.
 * 2. CHANGER DE PROFIL (11/09). Les mêmes cartes que la page de connexion,
 *    sans repasser par elle ; une carte à code le demande aussi ici.
 */
export default function PageProfil() {
  const { data: session } = useSession()
  const [profils, setProfils] = useState<CarteProfil[] | null>(null)
  const [actuel, setActuel] = useState<string | null>(null)
  const [enCours, setEnCours] = useState<string | null>(null)
  const [erreur, setErreur] = useState("")
  const [aCoder, setACoder] = useState<CarteProfil | null>(null)
  const [erreurCode, setErreurCode] = useState("")
  const jeton = (session as any)?.backendToken as string | undefined

  useEffect(() => {
    if (!jeton) return
    const api = process.env.NEXT_PUBLIC_API_URL || ""
    fetch(`${api}/api/auth/profils`, { headers: { Authorization: `Bearer ${jeton}` }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j) => { setProfils(j.profils || []); setActuel(j.actuel || null) })
      .catch((e) => setErreur(e?.message || "profils indisponibles"))
  }, [jeton])

  const choisir = async (id: string, code?: string) => {
    if (!jeton || enCours) return
    if (id === actuel) { window.location.href = "/chat"; return }
    // Une carte à code le demande aussi pour passer d'un profil à l'autre (13/09).
    const carte = (profils || []).find((p) => p.id === id)
    if (carte?.code && !code) { setACoder(carte); setErreurCode(""); return }
    setEnCours(id); setErreur("")
    const res = await signIn("credentials", { bascule: jeton, user_id: id, code: code || "", redirect: false })
    if (res?.error && carte?.code && res.code && res.code !== "credentials") {
      setEnCours(null)
      setErreurCode(messageCode(res.code))
      return
    }
    if (res?.error) {
      setACoder(null)
      setEnCours(null)
      setErreur("Ce profil n'a pas pu être ouvert. Réessayez ; si cela persiste, prévenez un administrateur.")
      return
    }
    window.location.href = "/chat"
  }

  return (
    <div style={{ minHeight: "calc(100dvh - 120px)", display: "flex", flexDirection: "column", alignItems: "center",
                  justifyContent: "center", gap: 28, padding: "32px 16px", boxSizing: "border-box" }}>
      {jeton && !aCoder && <MonCode jeton={jeton} />}
      {profils === null && !erreur && (
        <p style={{ color: "var(--marque-text-muted)", fontSize: 14 }}>Chargement des profils…</p>
      )}
      {aCoder && (
        <CodeCarte nom={aCoder.nom} enCours={enCours === aCoder.id} erreur={erreurCode}
                   onValider={(code) => choisir(aCoder.id, code)}
                   onAnnuler={() => { setACoder(null); setErreurCode("") }} />
      )}
      {!aCoder && profils !== null && profils.length > 1 && (
        <ChoixProfil profils={profils} onChoisir={(id) => choisir(id)} enCours={enCours} actuel={actuel}
                     titre="Changer de profil"
                     sousTitre="Chaque prénom a ses conversations, ses documents et ses dossiers de mail." />
      )}
      {!aCoder && profils !== null && profils.length <= 1 && (
        <Link href="/chat" className="sym-tap" style={{ color: "var(--marque-primary)", fontSize: 14 }}>Revenir au chat</Link>
      )}
      {erreur && (
        <p style={{ position: "fixed", bottom: 24, left: 16, right: 16, textAlign: "center",
                    color: "var(--marque-error-text)", fontSize: 13 }}>⚠ {erreur}</p>
      )}
    </div>
  )
}
