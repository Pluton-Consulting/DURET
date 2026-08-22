"use client"
import { useState } from "react"
import ValidationQueue from "@/components/validation/ValidationQueue"
import DebriefApprentissage from "@/components/learning/DebriefApprentissage"
import SkillsClient from "@/app/(app)/skills/SkillsClient"

/**
 * CONNAISSANCES — un seul endroit pour ce que l'assistant sait faire et apprend.
 *
 * Deux onglets disaient la même chose sous deux noms : « Apprentissage » (ce
 * qu'il a retenu, ce qu'il attend de vous) et « Savoir-faire » (la liste de
 * ses compétences). Réunis ici en trois volets, du plus urgent au plus
 * posé : ce qui attend votre décision, ce qu'il a appris, ce qu'il sait faire.
 */
interface Props { apiUrl: string; token: string }
type Volet = "a_valider" | "appris" | "savoir_faire"

export default function ConnaissancesClient({ apiUrl, token }: Props) {
  const [volet, setVolet] = useState<Volet>("a_valider")
  const volets: { key: Volet; label: string; sous: string }[] = [
    { key: "a_valider", label: "À valider", sous: "actions et compétences qui attendent votre décision" },
    { key: "appris", label: "Ce qu'il a appris", sous: "consignes retenues, connaissances acquises, corrections" },
    { key: "savoir_faire", label: "Savoir-faire", sous: "la liste de ses compétences, à activer ou désactiver" },
  ]
  return (
    <div className="sym-page" style={{ padding: "8px 32px 40px", maxWidth: 1200, margin: "0 auto" }}>
      <div className="sym-in" style={{ marginBottom: 18 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: "var(--marque-text-primary)", letterSpacing: "-.5px" }}>Connaissances</h1>
        <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--marque-text-muted)" }}>
          Ce que l'assistant sait faire, ce qu'il apprend, et ce qu'il attend de vous.
        </p>
      </div>
      <div className="sym-in" style={{ display: "inline-flex", gap: 4, padding: 5, borderRadius: 999, background: "var(--marque-surface)",
                                        border: "1px solid var(--marque-border)", boxShadow: "var(--marque-shadow-card)", marginBottom: 22 }}>
        {volets.map((v) => (
          <button key={v.key} type="button" onClick={() => setVolet(v.key)} title={v.sous}
                  style={{ border: "none", cursor: "pointer", borderRadius: 999, padding: "9px 16px", fontSize: 13.5, fontWeight: 600, fontFamily: "inherit",
                           background: volet === v.key ? "var(--marque-primary)" : "transparent",
                           color: volet === v.key ? "var(--marque-text-on-dark)" : "var(--marque-text-body)",
                           transition: "background .35s var(--v2-courbe), color .35s" }}>
            {v.label}
          </button>
        ))}
      </div>
      <p className="sym-in" style={{ margin: "0 0 16px", fontSize: 13, color: "var(--marque-text-muted)" }}>{volets.find((v) => v.key === volet)?.sous}</p>
      {volet === "a_valider" && <ValidationQueue token={token} />}
      {volet === "appris" && <DebriefApprentissage token={token} />}
      {volet === "savoir_faire" && <SkillsClient apiUrl={apiUrl} token={token} />}
    </div>
  )
}
