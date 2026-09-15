"use client"

/**
 * LES LEÇONS TIRÉES DES CORRECTIONS (15/09, backend/learning/lecons.py).
 *
 * Quand quelqu'un corrige l'assistant, le modèle en tire une leçon — la
 * situation, l'erreur, la bonne conduite — rappelée ensuite sur les demandes
 * proches. Ce volet les MONTRE : une mémoire qu'on ne peut ni lire ni retirer
 * serait une boîte noire. Retirer ne détruit rien côté serveur.
 *
 * Qui administre peut rendre une leçon valable pour toute l'entreprise (elle
 * est alors rappelée à tout le monde) ; sinon elle ne vaut que pour la
 * personne qui a corrigé.
 */
import { useCallback, useEffect, useState } from "react"
import { apiRequest } from "@/lib/api"

interface Lecon {
  id: string; situation: string; erreur: string; conduite: string
  portee: "personne" | "entreprise"; occurrences: number; rappels: number
  auteur?: string | null; derniere_maj?: string | null
}

export default function LeconsApprises({ token }: { token: string }) {
  const [lecons, setLecons] = useState<Lecon[] | null>(null)
  const [administre, setAdministre] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [occupe, setOccupe] = useState<string | null>(null)

  const charger = useCallback(async () => {
    try {
      const r = await apiRequest<{ administre: boolean; lecons: Lecon[] }>("/api/learning/lecons", { token })
      setLecons(r.lecons); setAdministre(r.administre); setErreur(null)
    } catch (e: any) {
      setErreur(e?.message ?? "Les leçons n'ont pas pu être chargées.")
    }
  }, [token])

  useEffect(() => { charger() }, [charger])

  const retirer = async (id: string) => {
    setOccupe(id)
    try {
      await apiRequest(`/api/learning/lecons/${id}/retirer`, { method: "POST", token })
      await charger()
    } catch (e: any) { setErreur(e?.message ?? "Retrait impossible.") } finally { setOccupe(null) }
  }

  const portee = async (id: string, entreprise: boolean) => {
    setOccupe(id)
    try {
      await apiRequest(`/api/learning/lecons/${id}/portee`,
        { method: "POST", token, body: JSON.stringify({ entreprise }) })
      await charger()
    } catch (e: any) { setErreur(e?.message ?? "Changement impossible.") } finally { setOccupe(null) }
  }

  if (erreur) return <p style={{ color: "var(--marque-danger, #b42318)", fontSize: 13 }}>{erreur}</p>
  if (lecons === null) return <p style={{ color: "var(--marque-text-muted)", fontSize: 13 }}>Chargement…</p>
  if (!lecons.length) {
    return (
      <p style={{ color: "var(--marque-text-muted)", fontSize: 13, lineHeight: 1.6 }}>
        Aucune leçon pour l'instant. Quand quelqu'un corrige l'assistant (« ce n'est pas ma
        signature », « tu as enlevé trop de choses »), il en tire une leçon qui apparaît ici.
      </p>
    )
  }
  return (
    <div style={{ display: "grid", gap: 12 }} data-testid="lecons">
      {lecons.map((l) => (
        <div key={l.id} className="sym-card" style={{
          background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
          borderRadius: "var(--marque-radius-card-sm)", padding: "14px 16px",
        }}>
          <div style={{ fontSize: 13.5, fontWeight: 700, color: "var(--marque-text-primary)" }}>{l.situation}</div>
          {l.erreur && (
            <div style={{ fontSize: 13, color: "var(--marque-text-muted)", marginTop: 6 }}>
              <strong>Erreur commise :</strong> {l.erreur}
            </div>
          )}
          <div style={{ fontSize: 13, color: "var(--marque-text-body)", marginTop: 6 }}>
            <strong>À faire :</strong> {l.conduite}
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 10,
                        fontSize: 12, color: "var(--marque-text-muted)" }}>
            <span>{l.portee === "entreprise" ? "Pour toute l'entreprise" : `Pour ${l.auteur || "la personne"}`}</span>
            <span>· relevée {l.occurrences} fois · rappelée {l.rappels} fois</span>
            <span style={{ flex: 1 }} />
            {administre && (
              <button type="button" className="sym-tap" disabled={occupe === l.id}
                      onClick={() => portee(l.id, l.portee !== "entreprise")}
                      style={{ border: "1px solid var(--marque-border)", background: "transparent", borderRadius: 999,
                               padding: "5px 12px", fontSize: 12, cursor: "pointer", color: "var(--marque-text-body)" }}>
                {l.portee === "entreprise" ? "Ne valoir que pour son auteur" : "Valable pour toute l'entreprise"}
              </button>
            )}
            <button type="button" className="sym-tap" disabled={occupe === l.id} onClick={() => retirer(l.id)}
                    style={{ border: "1px solid var(--marque-border)", background: "transparent", borderRadius: 999,
                             padding: "5px 12px", fontSize: 12, cursor: "pointer", color: "var(--marque-text-body)" }}>
              Retirer
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
