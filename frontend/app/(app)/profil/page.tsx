"use client"
import { useEffect, useState } from "react"
import Link from "next/link"
import { signIn, useSession } from "next-auth/react"
import ChoixProfil, { type CarteProfil } from "@/components/nav/ChoixProfil"
import CodeCarte, { messageCode } from "@/components/nav/CodeCarte"

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
type MonCode = { a_code: boolean; code: string | null; obligatoire: boolean; possible: boolean }

function SectionCode({ jeton }: { jeton: string }) {
  const api = process.env.NEXT_PUBLIC_API_URL || ""
  const [etat, setEtat] = useState<MonCode | null>(null)
  const [saisie, setSaisie] = useState("")
  const [voir, setVoir] = useState(false)
  const [message, setMessage] = useState("")
  const [erreur, setErreur] = useState("")
  const [enCours, setEnCours] = useState(false)

  useEffect(() => {
    fetch(`${api}/api/users/me/code`, { headers: { Authorization: `Bearer ${jeton}` }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((j: MonCode) => { setEtat(j); setSaisie(j.code || "") })
      .catch(() => setErreur("Le code n'a pas pu être lu."))
  }, [api, jeton])

  const enregistrer = async (retirer: boolean) => {
    setEnCours(true); setErreur(""); setMessage("")
    try {
      const r = await fetch(`${api}/api/users/me/code`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${jeton}` },
        body: JSON.stringify({ code: retirer ? null : saisie.trim() }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) { setErreur(j?.detail || "Le code n'a pas pu être enregistré."); return }
      setEtat((e) => e && { ...e, a_code: !!j.a_code, code: j.code ?? null })
      setSaisie(j.code || "")
      setMessage(retirer ? "Code retiré : votre carte s'ouvre d'un clic." : "Code enregistré : il sera demandé au clic sur votre carte.")
    } catch { setErreur("Le serveur n'a pas répondu. Réessayez.") } finally { setEnCours(false) }
  }

  if (!etat) return erreur ? <p style={{ color: "var(--marque-error-text)", fontSize: 13 }}>{erreur}</p> : null
  if (!etat.possible) return null
  const valide = /^\d{4,6}$/.test(saisie)

  return (
    <section data-testid="mon-code" className="sym-card" style={{
      background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)",
      boxShadow: "var(--marque-shadow-card)", padding: "20px 22px", width: "100%", maxWidth: 420,
      boxSizing: "border-box",
    }}>
      <h2 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 700, color: "var(--marque-text-primary)" }}>
        Mon code de connexion
      </h2>
      <p style={{ margin: "0 0 12px", fontSize: 13, color: "var(--marque-text-muted)", lineHeight: 1.5 }}>
        4 à 6 chiffres, demandés quand on clique sur votre carte à la connexion.
        {etat.obligatoire ? " Votre profil en garde toujours un." : " Sans code, la carte s'ouvre d'un clic."}
      </p>
      {etat.a_code && !etat.code && (
        <p style={{ margin: "0 0 10px", fontSize: 12, color: "var(--marque-text-muted)" }}>
          Un code est posé mais ne peut pas être affiché (posé avant le 14/09) : un nouveau le remplace.
        </p>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <input type={voir ? "text" : "password"} inputMode="numeric" autoComplete="off" maxLength={6}
               value={saisie} aria-label="Mon code"
               onChange={(e) => setSaisie(e.target.value.replace(/\D/g, ""))}
               style={{ width: 140, padding: "9px 12px", borderRadius: 10, fontSize: 15, letterSpacing: "0.3em",
                        border: "1.5px solid var(--marque-border)", color: "var(--marque-text-primary)",
                        background: "var(--marque-surface)" }} />
        <button type="button" onClick={() => setVoir((v) => !v)} className="sym-tap"
                style={{ background: "none", border: "none", color: "var(--marque-primary)", fontSize: 13, cursor: "pointer" }}>
          {voir ? "masquer" : "voir"}
        </button>
        <button type="button" onClick={() => enregistrer(false)} disabled={enCours || !valide || saisie === (etat.code || "")}
                className="sym-tap" style={{
                  background: "var(--marque-primary)", color: "var(--marque-text-on-dark)", border: "none",
                  borderRadius: "var(--marque-radius-pill)", padding: "9px 18px", fontSize: 13, fontWeight: 600,
                  cursor: enCours ? "wait" : "pointer", opacity: valide && saisie !== (etat.code || "") ? 1 : 0.5,
                }}>{enCours ? "…" : "Enregistrer"}</button>
        {etat.a_code && !etat.obligatoire && (
          <button type="button" onClick={() => enregistrer(true)} disabled={enCours} className="sym-tap" style={{
            background: "none", border: "1px solid var(--marque-border)", color: "var(--marque-text-body)",
            borderRadius: "var(--marque-radius-pill)", padding: "9px 16px", fontSize: 13, cursor: "pointer",
          }}>Retirer</button>
        )}
      </div>
      {message && <p role="status" style={{ margin: "10px 0 0", fontSize: 12, color: "var(--marque-text-body)" }}>{message}</p>}
      {erreur && <p role="status" style={{ margin: "10px 0 0", fontSize: 12, color: "var(--marque-error-text)" }}>{erreur}</p>}
    </section>
  )
}

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
      {jeton && !aCoder && <SectionCode jeton={jeton} />}
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
