"use client"
import { MARQUE } from "@/lib/permissions"

/**
 * « QUI ÊTES-VOUS ? » — LES CARTES DES PRÉNOMS D'UNE BOÎTE PARTAGÉE (11/09).
 *
 * Demande de Noa (Duret) : tout le monde se connecte avec la même adresse — la
 * boîte de l'entreprise — et, après le lien magique, un écran de cartes au
 * milieu ; on clique sur son prénom et l'on entre dans SA vue de l'application.
 * Le même écran sert au bouton « Changer de profil ».
 *
 * Rien n'est décidé ici : le serveur a déjà écarté les administrateurs de la
 * liste, et c'est lui qui vérifie que le prénom cliqué appartient bien à
 * l'adresse. Ce composant montre, et rend l'identifiant cliqué.
 */

export interface CarteProfil { id: string; nom: string }

function initiales(nom: string): string {
  const mots = nom.trim().split(/\s+/).filter(Boolean)
  return ((mots[0]?.[0] || "?") + (mots.length > 1 ? mots[mots.length - 1][0] : "")).toUpperCase()
}

export default function ChoixProfil({ profils, onChoisir, enCours, actuel, titre, sousTitre }: {
  profils: CarteProfil[]
  onChoisir: (id: string) => void
  enCours?: string | null
  actuel?: string | null
  titre?: string
  sousTitre?: string
}) {
  return (
    <div style={{ width: "100%", maxWidth: 760, textAlign: "center" }}>
      <div className="sym-in" style={{ fontSize: 11, fontWeight: 600, color: "var(--marque-text-muted)",
                                       textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
        {MARQUE.nom}
      </div>
      <h1 className="sym-in sym-in-1" style={{ margin: "0 0 6px", fontSize: 26, fontWeight: 800,
                                               color: "var(--marque-text-primary)", letterSpacing: "-0.5px" }}>
        {titre || "Qui êtes-vous ?"}
      </h1>
      <p className="sym-in sym-in-2" style={{ margin: "0 0 26px", fontSize: 14, color: "var(--marque-text-muted)" }}>
        {sousTitre || "Choisissez votre prénom : vous retrouverez vos conversations et vos documents."}
      </p>
      <div role="list" style={{ display: "grid", gap: 14,
                                gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))" }}>
        {profils.map((p, i) => {
          const courant = actuel === p.id
          const occupe = enCours === p.id
          return (
            <button key={p.id} type="button" role="listitem" data-testid="carte-profil"
                    disabled={!!enCours} onClick={() => onChoisir(p.id)}
                    className={`sym-tap sym-card sym-in sym-in-${Math.min(i + 1, 4)}`}
                    style={{
                      background: "var(--marque-surface)", cursor: enCours ? "wait" : "pointer",
                      border: courant ? "2px solid var(--marque-primary)" : "1px solid var(--marque-border)",
                      borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)",
                      padding: "22px 14px 18px", display: "flex", flexDirection: "column",
                      alignItems: "center", gap: 12, opacity: enCours && !occupe ? 0.55 : 1,
                    }}>
              <span aria-hidden style={{
                width: 58, height: 58, borderRadius: "50%", display: "flex", alignItems: "center",
                justifyContent: "center", fontSize: 20, fontWeight: 800,
                background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
                color: "var(--marque-text-on-dark)",
              }}>{occupe ? "…" : initiales(p.nom)}</span>
              <span style={{ fontSize: 15, fontWeight: 700, color: "var(--marque-text-primary)",
                             overflowWrap: "anywhere" }}>{p.nom}</span>
              {courant && (
                <span style={{ fontSize: 11, color: "var(--marque-paid-text)", fontWeight: 600 }}>profil actuel</span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
