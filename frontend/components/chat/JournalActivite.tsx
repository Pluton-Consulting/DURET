"use client"

/**
 * Ce que l'assistant fait, en direct, ligne par ligne.
 *
 * La frise d'étapes montre OÙ en est le traitement ; elle ne dit pas QUOI.
 * « Rédaction » pendant quarante secondes n'apprend rien, et quand rien
 * n'aboutit on ne sait pas s'il cherche, écrit, ou tourne en rond.
 *
 * Ici chaque acte s'inscrit : « je liste un dossier du serveur », « j'écris
 * dans le document ». La dernière ligne porte l'indicateur d'activité — c'est
 * elle qui dit que ça avance encore, et c'est sur elle que l'œil se pose quand
 * on se demande si c'est bloqué.
 */
import { useEffect, useRef } from "react"

type Props = {
  lignes: string[]
  actif: boolean
}

// Au-delà, on ne lit plus : on garde la fin, c'est là que ça se passe.
const MAX_VISIBLE = 12

export default function JournalActivite({ lignes, actif }: Props) {
  const bas = useRef<HTMLDivElement>(null)

  // La dernière ligne doit rester visible sans avoir à faire défiler.
  useEffect(() => {
    bas.current?.scrollIntoView({ block: "nearest" })
  }, [lignes.length])

  if (!lignes.length) return null
  const visibles = lignes.slice(-MAX_VISIBLE)
  const caches = lignes.length - visibles.length

  return (
    <div
      aria-live="polite"
      style={{
        border: "1px solid var(--color-border)",
        borderRadius: 10,
        background: "var(--color-surface)",
        padding: "10px 12px",
        margin: "8px 0",
        maxWidth: 620,
        maxHeight: 190,
        overflowY: "auto",
        fontSize: 12.5,
        lineHeight: 1.6,
        color: "var(--color-text-muted)",
      }}
    >
      {caches > 0 && (
        <div style={{ opacity: 0.6, fontStyle: "italic" }}>
          … {caches} étape{caches > 1 ? "s" : ""} précédente{caches > 1 ? "s" : ""}
        </div>
      )}

      {visibles.map((ligne, i) => {
        const derniere = i === visibles.length - 1
        const enCours = derniere && actif
        return (
          <div
            key={`${i}-${ligne}`}
            style={{
              display: "flex", alignItems: "baseline", gap: 8,
              color: enCours ? "var(--color-text-body)" : undefined,
              fontWeight: enCours ? 600 : 400,
            }}
          >
            <span aria-hidden style={{ opacity: enCours ? 1 : 0.45 }}>
              {enCours ? "▸" : "·"}
            </span>
            <span>{ligne}</span>
            {enCours && (
              <span
                aria-hidden
                style={{
                  display: "inline-block", width: 8, height: 8, borderRadius: "50%",
                  background: "var(--color-primary)",
                  animation: "sym-pulse 1.1s ease-in-out infinite",
                  flexShrink: 0, alignSelf: "center",
                }}
              />
            )}
          </div>
        )
      })}
      <div ref={bas} />

      {/* `prefers-reduced-motion` : une animation permanente est pénible, voire
          douloureuse, pour une partie des utilisateurs. On la remplace par une
          opacité fixe plutôt que de la retirer, sinon l'indicateur d'activité
          disparaîtrait complètement. */}
      <style>{`
        @keyframes sym-pulse {
          0%, 100% { opacity: 0.25; transform: scale(0.85); }
          50%      { opacity: 1;    transform: scale(1); }
        }
        @media (prefers-reduced-motion: reduce) {
          [style*="sym-pulse"] { animation: none !important; opacity: 0.8 !important; }
        }
      `}</style>
    </div>
  )
}
