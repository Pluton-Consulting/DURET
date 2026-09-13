"use client"
import { useEffect, useRef, useState } from "react"

/**
 * LE CODE D'UNE CARTE (13/09, Duret). La page de connexion est un choix de
 * prénom ; une carte de direction (ou d'un profil qui en a posé un) demande
 * un code de 4 à 6 chiffres avant d'ouvrir la session. Le même panneau sert
 * à « Changer de profil ». Rien n'est vérifié ici : le serveur compte les
 * essais et bloque la carte au cinquième.
 */

/** La raison courte du serveur, dite en français. */
export function messageCode(raison: string | undefined): string {
  if (raison === "code_bloque") return "Trop d'essais : cette carte est bloquée un quart d'heure."
  if (raison === "code_faux") return "Code incorrect."
  if (raison === "code_requis") return "Cette carte demande son code."
  return "Ce profil n'a pas pu être ouvert. Réessayez ; si cela persiste, prévenez un administrateur."
}

export default function CodeCarte({ nom, onValider, onAnnuler, erreur, enCours }: {
  nom: string
  onValider: (code: string) => void
  onAnnuler: () => void
  erreur?: string
  enCours?: boolean
}) {
  const [code, setCode] = useState("")
  const champ = useRef<HTMLInputElement>(null)
  useEffect(() => { champ.current?.focus() }, [])
  // Un code refusé se retape en entier : on vide le champ à chaque refus.
  useEffect(() => { if (erreur) { setCode(""); champ.current?.focus() } }, [erreur])

  return (
    <form data-testid="code-carte" className="sym-card sym-pop"
          onSubmit={(e) => { e.preventDefault(); if (code.length >= 4 && !enCours) onValider(code) }}
          style={{ background: "var(--marque-surface)", borderRadius: "var(--marque-radius-card)",
                   boxShadow: "var(--marque-shadow-card)", padding: "26px 24px", width: "100%",
                   maxWidth: 340, textAlign: "center", boxSizing: "border-box" }}>
      <div style={{ fontSize: 28, marginBottom: 8 }} aria-hidden>🔒</div>
      <p style={{ margin: "0 0 4px", fontWeight: 700, fontSize: 16, color: "var(--marque-text-primary)" }}>{nom}</p>
      <p style={{ margin: "0 0 16px", fontSize: 13, color: "var(--marque-text-muted)" }}>Saisissez le code de cette carte.</p>
      <input ref={champ} type="password" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
             aria-label="Code" value={code} disabled={enCours}
             onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
             style={{ width: "100%", boxSizing: "border-box", textAlign: "center", fontSize: 22,
                      letterSpacing: "0.5em", padding: "10px 12px", borderRadius: 12,
                      border: "1.5px solid var(--marque-border)", outline: "none", marginBottom: 12 }} />
      {erreur && <p role="alert" style={{ color: "var(--marque-error-text)", fontSize: 13, margin: "0 0 12px" }}>{erreur}</p>}
      <button type="submit" disabled={enCours || code.length < 4} className="sym-tap"
              style={{ width: "100%", padding: "11px 20px", border: "none", borderRadius: "var(--marque-radius-pill)",
                       background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
                       color: "var(--marque-text-on-dark)", fontSize: 14, fontWeight: 600,
                       cursor: enCours ? "wait" : "pointer", opacity: code.length < 4 ? 0.6 : 1 }}>
        {enCours ? "Vérification…" : "Entrer"}
      </button>
      <button type="button" onClick={onAnnuler} className="sym-tap"
              style={{ marginTop: 10, background: "none", border: "none", cursor: "pointer",
                       fontSize: 13, color: "var(--marque-primary)" }}>
        ← Retour aux profils
      </button>
    </form>
  )
}
