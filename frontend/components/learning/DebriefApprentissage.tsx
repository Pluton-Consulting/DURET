"use client"

import { useCallback, useEffect, useState } from "react"
import type { CSSProperties, ReactNode } from "react"
import { apiRequest } from "@/lib/api"

// Débrief manuel : l'assistant relit la dernière conversation, propose ce qu'il
// retiendrait, et n'écrit QUE ce qui a été coché. Deux appels distincts côté
// backend (/analyser puis /enregistrer) — l'analyse seule ne touche à rien.

interface Connaissance { titre: string; contenu: string; acces: string }
interface Procedure { titre: string; contenu: string }
interface Competence { nom: string; description: string; entrees: string }

interface Analyse {
  token: string
  thread_id: string
  titre: string
  messages: number
  total: number
  connaissances: Connaissance[]
  procedures: Procedure[]
  competences: Competence[]
}

interface Dernier {
  disponible: boolean
  message?: string
  titre?: string
  date?: string
  messages?: number
}

const ACCES_LABEL: Record<string, string> = {
  all: "Tout le monde",
  commercial_plus: "Commercial et +",
  bureau_etudes_plus: "Bureau d'études et +",
  direction_only: "Direction uniquement",
  admin_only: "Admin uniquement",
}

const carte: CSSProperties = {
  background: "var(--color-surface)",
  borderRadius: "var(--radius-card-sm)",
  border: "1px solid var(--color-border)",
  boxShadow: "var(--shadow-card)",
}

const bouton = (principal: boolean): CSSProperties => ({
  padding: "10px 18px",
  borderRadius: "var(--radius-pill)",
  border: principal ? "none" : "1px solid var(--color-border)",
  background: principal
    ? "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))"
    : "var(--color-surface)",
  color: principal ? "var(--color-text-on-dark)" : "var(--color-text-body)",
  fontSize: 14,
  fontWeight: 600,
  cursor: "pointer",
})

export default function DebriefApprentissage({ token }: { token: string }) {
  const [dernier, setDernier] = useState<Dernier | null>(null)
  const [analyse, setAnalyse] = useState<Analyse | null>(null)
  const [choix, setChoix] = useState<Record<string, Set<number>>>({
    connaissances: new Set(), procedures: new Set(), competences: new Set(),
  })
  const [enCours, setEnCours] = useState<"analyse" | "enregistrement" | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [bilan, setBilan] = useState<string | null>(null)

  const chargerDernier = useCallback(async () => {
    try {
      setDernier(await apiRequest<Dernier>("/api/learning/dernier", { token }))
    } catch (e: any) {
      setErreur(e.message || "Impossible de lire les conversations")
    }
  }, [token])

  useEffect(() => { chargerDernier() }, [chargerDernier])

  async function lancer() {
    setEnCours("analyse"); setErreur(null); setBilan(null); setAnalyse(null)
    try {
      const res = await apiRequest<Analyse>("/api/learning/analyser", {
        method: "POST", token, body: JSON.stringify({}),
      })
      setAnalyse(res)
      // Tout est coché d'emblée : l'humain retire ce qu'il ne veut pas, plutôt
      // que de tout re-cocher. C'est lui qui décide, dans les deux sens.
      setChoix({
        connaissances: new Set(res.connaissances.map((_, i) => i)),
        procedures: new Set(res.procedures.map((_, i) => i)),
        competences: new Set(res.competences.map((_, i) => i)),
      })
    } catch (e: any) {
      setErreur(e.message || "L'analyse a échoué")
    } finally {
      setEnCours(null)
    }
  }

  function basculer(groupe: string, index: number) {
    setChoix((c) => {
      const suivant = new Set(c[groupe])
      if (suivant.has(index)) suivant.delete(index)
      else suivant.add(index)
      return { ...c, [groupe]: suivant }
    })
  }

  const nbCoches = Object.values(choix).reduce((n, s) => n + s.size, 0)

  async function enregistrer() {
    if (!analyse) return
    setEnCours("enregistrement"); setErreur(null)
    try {
      const res = await apiRequest<{ memorise: number; chunks: number; skills: string[]; echecs: string[] }>(
        "/api/learning/enregistrer", {
          method: "POST", token,
          body: JSON.stringify({
            token: analyse.token,
            connaissances: Array.from(choix.connaissances),
            procedures: Array.from(choix.procedures),
            competences: Array.from(choix.competences),
          }),
        })
      const parts = [`${res.memorise} élément(s) en mémoire (${res.chunks} fragments)`]
      if (res.skills.length) parts.push(`${res.skills.length} skill(s) en brouillon : ${res.skills.join(", ")}`)
      if (res.echecs.length) parts.push(`${res.echecs.length} échec(s)`)
      setBilan(parts.join(" · "))
      setAnalyse(null)
      chargerDernier()
    } catch (e: any) {
      setErreur(e.message || "L'enregistrement a échoué")
    } finally {
      setEnCours(null)
    }
  }

  function section(cle: string, titre: string, aide: string, items: any[],
                   rendu: (item: any) => ReactNode) {
    if (!items.length) return null
    return (
      <div style={{ marginTop: 20 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>{titre}</div>
        <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginBottom: 10 }}>{aide}</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {items.map((item, i) => (
            <label key={i} style={{ ...carte, padding: "12px 14px", display: "flex", gap: 12,
                                    alignItems: "flex-start", cursor: "pointer",
                                    opacity: choix[cle].has(i) ? 1 : 0.5 }}>
              <input type="checkbox" checked={choix[cle].has(i)} onChange={() => basculer(cle, i)}
                     style={{ marginTop: 3, cursor: "pointer" }} />
              <div style={{ minWidth: 0 }}>{rendu(item)}</div>
            </label>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                    marginBottom: 6, gap: 16, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--color-text-primary)" }}>
          Débrief de conversation
        </h2>
        <button onClick={lancer} disabled={enCours !== null || dernier?.disponible === false}
                style={{ ...bouton(true), opacity: enCours || dernier?.disponible === false ? 0.6 : 1 }}>
          {enCours === "analyse" ? "Relecture en cours…" : "Relire la dernière conversation"}
        </button>
      </div>

      <p style={{ margin: "0 0 14px", fontSize: 13, color: "var(--color-text-body)",
                  maxWidth: "70ch", lineHeight: 1.55 }}>
        L'assistant relit l'échange, en extrait ce qui mérite d'être retenu, et vous le
        soumet. <b>Rien n'est enregistré sans votre accord</b> : vous décochez ce que vous
        ne voulez pas garder.
      </p>

      {dernier && !dernier.disponible && (
        <div style={{ ...carte, padding: "16px 18px", fontSize: 13, color: "var(--color-text-muted)" }}>
          {dernier.message}
        </div>
      )}

      {dernier?.disponible && !analyse && (
        <div style={{ ...carte, padding: "14px 18px", fontSize: 13, color: "var(--color-text-body)" }}>
          Dernière conversation : <b>{dernier.titre}</b> · {dernier.messages} message(s) ·{" "}
          {dernier.date ? new Date(dernier.date).toLocaleString("fr-FR") : ""}
        </div>
      )}

      {erreur && (
        <div style={{ ...carte, padding: "14px 18px", marginTop: 12, fontSize: 13,
                      background: "var(--color-late-bg)", color: "var(--color-late-text)",
                      border: "none" }}>
          {erreur}
        </div>
      )}

      {bilan && (
        <div style={{ ...carte, padding: "14px 18px", marginTop: 12, fontSize: 13,
                      background: "var(--color-paid-bg)", color: "var(--color-paid-text)",
                      border: "none" }}>
          Enregistré : {bilan}
        </div>
      )}

      {analyse && analyse.total === 0 && (
        <div style={{ ...carte, padding: "24px 18px", marginTop: 12, fontSize: 13,
                      color: "var(--color-text-muted)", textAlign: "center" }}>
          Rien à retenir dans « {analyse.titre} ». C'est un résultat normal : une conversation
          courante n'apporte pas toujours de connaissance durable.
        </div>
      )}

      {analyse && analyse.total > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, color: "var(--color-text-muted)", fontFamily: "monospace" }}>
            {analyse.titre} · {analyse.messages} message(s) relus · {analyse.total} proposition(s)
          </div>

          {section("connaissances", "Connaissances",
            "Faits durables sur l'entreprise — rangés dans la mémoire, retrouvables par le chat.",
            analyse.connaissances, (c: Connaissance) => (
              <>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>{c.titre}</div>
                <div style={{ fontSize: 13, color: "var(--color-text-body)", marginTop: 3, lineHeight: 1.5 }}>{c.contenu}</div>
                <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 5, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Visible par : {ACCES_LABEL[c.acces] || c.acces}
                </div>
              </>
            ))}

          {section("procedures", "Manières de faire",
            "Consignes de présentation ou de méthode — mémorisées pour les prochains échanges.",
            analyse.procedures, (p: Procedure) => (
              <>
                <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>{p.titre}</div>
                <div style={{ fontSize: 13, color: "var(--color-text-body)", marginTop: 3, lineHeight: 1.5 }}>{p.contenu}</div>
              </>
            ))}

          {section("competences", "Compétences à créer",
            "Calculs reproductibles — créés en brouillon, inactifs tant qu'un humain n'a pas relu le code.",
            analyse.competences, (c: Competence) => (
              <>
                <div style={{ fontFamily: "monospace", fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>{c.nom}</div>
                <div style={{ fontSize: 13, color: "var(--color-text-body)", marginTop: 3, lineHeight: 1.5 }}>{c.description}</div>
                {c.entrees && (
                  <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 4 }}>Entrées : {c.entrees}</div>
                )}
              </>
            ))}

          <div style={{ display: "flex", gap: 10, marginTop: 20, alignItems: "center" }}>
            <button onClick={enregistrer} disabled={enCours !== null || nbCoches === 0}
                    style={{ ...bouton(true), opacity: enCours || nbCoches === 0 ? 0.6 : 1 }}>
              {enCours === "enregistrement" ? "Enregistrement…" : `Enregistrer (${nbCoches})`}
            </button>
            <button onClick={() => setAnalyse(null)} disabled={enCours !== null} style={bouton(false)}>
              Abandonner
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
