"use client"

/**
 * REPONSES PROPOSÉES À PLUSIEURS MAILS — des cartes horizontales, validées en une fois.
 *
 * Demandé par Noa le 31/08 : « toutes ces réponses sont dans des cartes
 * horizontales avec bouton pour valider chacune, et elles se valident tout en
 * une fois à la fin ». Chaque carte porte le mail (expéditeur, objet), la
 * réponse proposée, et une case ; le bouton unique envoie DANS LE CHAT la
 * demande d'envoi des réponses cochées — même canal que les pastilles de
 * suggestion (`onAction`). Ce composant n'envoie donc RIEN lui-même : chaque
 * envoi réel repasse par `envoyer_email` et sa validation (effet externe),
 * la règle du projet ne bouge pas.
 */
import { useState } from "react"

type Reponse = { ref?: string; de?: string; objet?: string; reponse?: string }

type Props = {
  reponses: Reponse[]
  onAction?: (message: string) => void
}

export function ReponsesMail({ reponses, onAction }: Props) {
  const valides = (reponses || []).filter((r) => r && (r.reponse || "").trim())
  const [choisies, setChoisies] = useState<boolean[]>(() => valides.map(() => true))
  const [transmis, setTransmis] = useState(false)
  const n = choisies.filter(Boolean).length

  if (!valides.length) return null

  const basculer = (i: number) =>
    setChoisies((c) => c.map((v, j) => (j === i ? !v : v)))

  const envoyer = () => {
    if (!onAction || !n || transmis) return
    const lignes = valides
      .filter((_, i) => choisies[i])
      .map((r) =>
        `- à ${r.de || "(expéditeur du message)"} — « ${r.objet || "sans objet"} »` +
        (r.ref ? ` (ref ${r.ref})` : "") + ` :\n${(r.reponse || "").trim()}`)
    onAction(
      `Envoie ces ${n} réponse(s) aux mails correspondants, telles quelles :\n${lignes.join("\n\n")}`)
    setTransmis(true)
  }

  return (
    <div style={{ display: "grid", gap: 10 }}>
      {/* Le rail horizontal : une carte par réponse, défilement au doigt ou à la molette. */}
      <div style={{ display: "flex", gap: 10, overflowX: "auto", paddingBottom: 4 }}>
        {valides.map((r, i) => (
          <div
            key={r.ref || i}
            style={{
              flex: "0 0 260px",
              border: `1px solid ${choisies[i] ? "var(--marque-primary, #2F5D3A)" : "var(--marque-border, #d8d8d8)"}`,
              borderRadius: 10,
              padding: "10px 12px",
              display: "grid",
              gap: 6,
              alignContent: "start",
              opacity: transmis && !choisies[i] ? 0.5 : 1,
              background: "var(--marque-surface, transparent)",
            }}
          >
            <label style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: transmis ? "default" : "pointer" }}>
              <input
                type="checkbox"
                checked={!!choisies[i]}
                disabled={transmis}
                onChange={() => basculer(i)}
                aria-label={`Retenir la réponse à ${r.de || "ce message"}`}
                style={{ marginTop: 3 }}
              />
              <span style={{ display: "grid", gap: 2, minWidth: 0 }}>
                <span style={{ fontSize: 12, color: "var(--marque-muted, #666)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.de || "(expéditeur inconnu)"}
                </span>
                <span style={{ fontWeight: 600, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.objet || "(sans objet)"}
                </span>
              </span>
            </label>
            <div style={{ fontSize: 13, whiteSpace: "pre-wrap", maxHeight: 140, overflowY: "auto" }}>
              {(r.reponse || "").trim()}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button
          type="button"
          onClick={envoyer}
          disabled={!onAction || !n || transmis}
          style={{
            border: "1px solid var(--marque-primary, #2F5D3A)",
            background: transmis ? "transparent" : "var(--marque-primary, #2F5D3A)",
            color: transmis ? "var(--marque-primary, #2F5D3A)" : "var(--marque-on-primary, #fff)",
            borderRadius: 8,
            padding: "6px 14px",
            fontSize: 13,
            cursor: !onAction || !n || transmis ? "default" : "pointer",
          }}
        >
          {transmis
            ? "Demande transmise — chaque envoi vous sera soumis"
            : `Envoyer ${n ? `les ${n} réponse(s) cochée(s)` : "(aucune réponse cochée)"}`}
        </button>
        {!transmis && (
          <span style={{ fontSize: 12, color: "var(--marque-muted, #666)" }}>
            Rien ne part sans votre accord : chaque envoi sera présenté à la validation.
          </span>
        )}
      </div>
    </div>
  )
}
