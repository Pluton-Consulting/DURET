"use client"
import { useEffect, useState } from "react"

/**
 * POSER SON CODE, TOUT DE SUITE (16/09, audit D-19).
 *
 * Le code de PREMIÈRE ENTRÉE du serveur ne sert qu'une fois : l'administrateur
 * qui vient d'entrer avec lui n'a plus rien pour revenir demain. Ce panneau se
 * pose donc devant l'application tant qu'aucun vrai code n'est enregistré — on
 * ne le referme pas, on pose son code.
 *
 * Il ne s'affiche que pour un administrateur sans code (`code_par_defaut`) :
 * personne d'autre ne le voit jamais.
 */
export default function CodeAPoser({ jeton }: { jeton: string }) {
  const api = process.env.NEXT_PUBLIC_API_URL || ""
  const [aPoser, setAPoser] = useState(false)
  const [code, setCode] = useState("")
  const [erreur, setErreur] = useState("")
  const [enCours, setEnCours] = useState(false)

  useEffect(() => {
    let vivant = true
    fetch(`${api}/api/users/me/code`, { headers: { Authorization: `Bearer ${jeton}` }, cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((j) => { if (vivant) setAPoser(!!j?.code_par_defaut) })
      .catch(() => { /* le serveur ne répond pas : rien ne s'impose à l'écran */ })
    return () => { vivant = false }
  }, [api, jeton])

  if (!aPoser) return null

  const valide = /^\d{4,6}$/.test(code)
  const enregistrer = async () => {
    setEnCours(true); setErreur("")
    try {
      const r = await fetch(`${api}/api/users/me/code`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${jeton}` },
        body: JSON.stringify({ code }),
      })
      const j = await r.json().catch(() => ({}))
      if (!r.ok) { setErreur(j?.detail || "Le code n'a pas pu être enregistré."); return }
      setAPoser(false)
    } catch { setErreur("Le serveur n'a pas répondu. Réessayez.") } finally { setEnCours(false) }
  }

  return (
    <div data-testid="code-a-poser" role="dialog" aria-modal="true"
         style={{ position: "fixed", inset: 0, zIndex: 900, display: "grid", placeItems: "center",
                  background: "rgba(15, 23, 42, 0.55)", padding: 16 }}>
      <form className="sym-card sym-pop" onSubmit={(e) => { e.preventDefault(); if (valide && !enCours) enregistrer() }}
            style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)",
                     boxShadow: "var(--marque-shadow-card)", padding: "26px 24px", width: "100%",
                     maxWidth: 380, boxSizing: "border-box", textAlign: "center" }}>
        <div style={{ fontSize: 28, marginBottom: 8 }} aria-hidden>🔑</div>
        <p style={{ margin: "0 0 6px", fontWeight: 700, fontSize: 16, color: "var(--marque-text-primary)" }}>
          Choisissez votre code d&apos;administrateur
        </p>
        <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--marque-text-muted)", lineHeight: 1.5 }}>
          Le code de première entrée vient d&apos;être utilisé : il ne servira plus. Posez le vôtre
          (4 à 6 chiffres) — c&apos;est lui qui ouvrira votre carte la prochaine fois.
        </p>
        <input type="password" inputMode="numeric" autoComplete="new-password" maxLength={6}
               aria-label="Nouveau code" value={code} disabled={enCours} autoFocus
               onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
               style={{ width: "100%", boxSizing: "border-box", textAlign: "center", fontSize: 22,
                        letterSpacing: "0.5em", padding: "10px 12px", borderRadius: 12,
                        border: "1.5px solid var(--marque-border)", outline: "none", marginBottom: 12 }} />
        {erreur && <p role="alert" style={{ color: "var(--marque-error-text)", fontSize: 13, margin: "0 0 12px" }}>{erreur}</p>}
        <button type="submit" disabled={!valide || enCours} className="sym-tap"
                style={{ width: "100%", padding: "11px 20px", border: "none", borderRadius: "var(--marque-radius-pill)",
                         background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
                         color: "var(--marque-text-on-dark)", fontSize: 14, fontWeight: 600,
                         cursor: enCours ? "wait" : "pointer", opacity: valide ? 1 : 0.6 }}>
          {enCours ? "Enregistrement…" : "Enregistrer mon code"}
        </button>
      </form>
    </div>
  )
}
