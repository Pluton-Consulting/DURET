"use client"
import { useRef, useState } from "react"

/**
 * Import de données dans la mémoire d'entreprise.
 *
 * Déroulé en deux temps, volontaire : le fichier est d'abord ANALYSÉ (l'IA devine
 * sa nature et propose un découpage), rien n'est écrit. L'utilisateur voit ce qui
 * sera enregistré, corrige le type et la colonne identifiante, puis valide.
 */

type Detection = { source_type: string; confiance: string; resume: string; id_col: string | null }
type Analyse = {
  token: string
  filename: string
  kind: "tabulaire" | "document"
  columns: string[]
  documents: number
  detection: Detection
  apercu: string[]
  types_possibles: { cle: string; libelle: string }[]
}

const ACCEPTE = ".csv,.xlsx,.xls,.xlsm,.docx,.pdf,.txt,.md"

const COULEUR_CONFIANCE: Record<string, string> = {
  haute: "var(--color-primary)",
  moyenne: "var(--color-pending-text)",
  faible: "var(--color-error)",
}

export default function ImportTab({ apiUrl, backendToken }: { apiUrl: string; backendToken: string }) {
  const [analyse, setAnalyse] = useState<Analyse | null>(null)
  const [type, setType] = useState("")
  const [idCol, setIdCol] = useState("")
  const [acces, setAcces] = useState("all")
  const [anonymiser, setAnonymiser] = useState(false)
  const [enCours, setEnCours] = useState<"" | "analyse" | "import">("")
  const [erreur, setErreur] = useState("")
  const [resultat, setResultat] = useState<{ documents: number; chunks: number; echecs: number } | null>(null)
  const [survol, setSurvol] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const reinitialiser = () => {
    setAnalyse(null); setErreur(""); setResultat(null)
    if (inputRef.current) inputRef.current.value = ""
  }

  const analyser = async (fichier: File) => {
    setErreur(""); setResultat(null); setEnCours("analyse")
    try {
      const form = new FormData()
      form.append("file", fichier)
      const res = await fetch(`${apiUrl}/api/ingestion/analyze`, {
        method: "POST",
        headers: { Authorization: `Bearer ${backendToken}` },   // pas de Content-Type : le navigateur pose la frontière multipart
        body: form,
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `Erreur ${res.status}`)
      setAnalyse(data)
      setType(data.detection.source_type)
      setIdCol(data.detection.id_col || "")
    } catch (e: any) {
      setErreur(e.message || "Analyse impossible")
    } finally {
      setEnCours("")
    }
  }

  const confirmer = async () => {
    if (!analyse) return
    setErreur(""); setEnCours("import")
    try {
      const res = await fetch(`${apiUrl}/api/ingestion/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${backendToken}` },
        body: JSON.stringify({
          token: analyse.token, source_type: type,
          id_col: idCol || null, access_level: acces, anonymize: anonymiser,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || `Erreur ${res.status}`)
      setResultat(data)
      setAnalyse(null)
      if (inputRef.current) inputRef.current.value = ""
    } catch (e: any) {
      setErreur(e.message || "Import impossible")
    } finally {
      setEnCours("")
    }
  }

  const carte = {
    background: "var(--color-surface)", borderRadius: "var(--radius-card)",
    boxShadow: "var(--shadow-card)", padding: 24, border: "1px solid var(--color-border)",
  } as const
  const label = { fontSize: 12, fontWeight: 700, color: "var(--color-text-muted)", textTransform: "uppercase" as const, letterSpacing: ".05em", marginBottom: 6, display: "block" }
  const champ = {
    width: "100%", padding: "9px 12px", fontSize: 14, fontFamily: "inherit",
    borderRadius: 10, border: "1.5px solid var(--color-border)",
    background: "var(--color-canvas)", color: "var(--color-text-primary)",
  } as const

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 880 }}>
      {/* Dépôt du fichier */}
      {!analyse && (
        <div
          onDragOver={(e) => { e.preventDefault(); setSurvol(true) }}
          onDragLeave={() => setSurvol(false)}
          onDrop={(e) => { e.preventDefault(); setSurvol(false); const f = e.dataTransfer.files?.[0]; if (f) analyser(f) }}
          onClick={() => inputRef.current?.click()}
          style={{
            ...carte, cursor: "pointer", textAlign: "center", padding: "44px 24px",
            border: `2px dashed ${survol ? "var(--color-primary)" : "var(--color-border)"}`,
            background: survol ? "var(--color-primary-subtle)" : "var(--color-surface)",
            transition: "all .15s ease",
          }}
        >
          <input ref={inputRef} type="file" accept={ACCEPTE} style={{ display: "none" }}
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) analyser(f) }} />
          <div style={{ fontSize: 30, marginBottom: 10 }}>📄</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 6 }}>
            {enCours === "analyse" ? "Analyse du fichier…" : "Déposez un fichier ou cliquez pour le choisir"}
          </div>
          <div style={{ fontSize: 13, color: "var(--color-text-muted)" }}>
            Excel, CSV, Word, PDF, texte — l'IA reconnaît le contenu et vous propose un découpage avant tout enregistrement.
          </div>
        </div>
      )}

      {erreur && (
        <div style={{ ...carte, borderColor: "var(--color-error)", color: "var(--color-error)", fontSize: 14, padding: 16 }}>
          {erreur}
        </div>
      )}

      {resultat && (
        <div style={{ ...carte, borderColor: "var(--color-primary)", padding: 20 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-primary)", marginBottom: 6 }}>
            Import terminé
          </div>
          <div style={{ fontSize: 14, color: "var(--color-text-body)" }}>
            {resultat.documents} document{resultat.documents > 1 ? "s" : ""} enregistré{resultat.documents > 1 ? "s" : ""}
            {" "}({resultat.chunks} extraits indexés)
            {resultat.echecs > 0 && <span style={{ color: "var(--color-error)" }}> — {resultat.echecs} en échec</span>}
            .
          </div>
          <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 8 }}>
            La vectorisation se termine en tâche de fond : les données seront interrogeables dans le chat d'ici quelques instants.
          </div>
        </div>
      )}

      {/* Proposition de l'IA, à valider */}
      {analyse && (
        <div style={{ ...carte, display: "flex", flexDirection: "column", gap: 18 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, color: "var(--color-text-primary)" }}>{analyse.filename}</div>
            <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginTop: 4 }}>
              {analyse.kind === "tabulaire"
                ? `${analyse.documents} lignes → ${analyse.documents} documents (une ligne = un document)`
                : "1 document"}
            </div>
          </div>

          <div style={{ background: "var(--color-primary-subtle)", borderRadius: 10, padding: 14, border: "1px solid var(--color-primary-light)" }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-primary)", marginBottom: 6 }}>
              CE QUE L'IA A RECONNU
              <span style={{ marginLeft: 8, fontWeight: 600, color: COULEUR_CONFIANCE[analyse.detection.confiance] || "var(--color-text-muted)" }}>
                confiance {analyse.detection.confiance}
              </span>
            </div>
            <div style={{ fontSize: 14, color: "var(--color-text-body)", lineHeight: 1.5 }}>{analyse.detection.resume}</div>
            {analyse.detection.confiance !== "haute" && (
              <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", marginTop: 8 }}>
                Vérifiez le type ci-dessous avant de valider.
              </div>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: analyse.kind === "tabulaire" ? "1fr 1fr" : "1fr", gap: 14 }}>
            <div>
              <label style={label}>Type de données</label>
              <select value={type} onChange={(e) => setType(e.target.value)} style={champ}>
                {analyse.types_possibles.map((t) => (
                  <option key={t.cle} value={t.cle}>{t.cle} — {t.libelle}</option>
                ))}
              </select>
            </div>
            {analyse.kind === "tabulaire" && (
              <div>
                <label style={label}>Colonne identifiante</label>
                <select value={idCol} onChange={(e) => setIdCol(e.target.value)} style={champ}>
                  <option value="">(numéro de ligne)</option>
                  {analyse.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <div style={{ fontSize: 11.5, color: "var(--color-text-muted)", marginTop: 5 }}>
                  Permet de réimporter le fichier mis à jour sans créer de doublons.
                </div>
              </div>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, alignItems: "end" }}>
            <div>
              <label style={label}>Qui peut le consulter</label>
              <select value={acces} onChange={(e) => setAcces(e.target.value)} style={champ}>
                <option value="all">Tout le monde</option>
                <option value="commercial_plus">Commercial et au-dessus</option>
                <option value="bureau_etudes_plus">Bureau d'études et au-dessus</option>
                <option value="direction_only">Direction uniquement</option>
              </select>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 9, fontSize: 13.5, color: "var(--color-text-body)", cursor: "pointer", paddingBottom: 9 }}>
              <input type="checkbox" checked={anonymiser} onChange={(e) => setAnonymiser(e.target.checked)}
                     style={{ width: 16, height: 16, accentColor: "var(--color-primary)", cursor: "pointer" }} />
              Masquer les données personnelles
            </label>
          </div>

          <div>
            <label style={label}>Aperçu de ce qui sera enregistré</label>
            <div style={{
              background: "var(--color-canvas)", border: "1px solid var(--color-border)", borderRadius: 10,
              padding: 14, maxHeight: 220, overflow: "auto", fontSize: 12.5, lineHeight: 1.55,
              fontFamily: "ui-monospace, Consolas, monospace", color: "var(--color-text-body)", whiteSpace: "pre-wrap",
            }}>
              {analyse.apercu.join("\n\n───────────────\n\n")}
            </div>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={confirmer} disabled={enCours === "import"} className="sym-tap" style={{
              padding: "11px 22px", border: "none", borderRadius: 10, cursor: enCours ? "wait" : "pointer",
              fontSize: 14, fontWeight: 700, fontFamily: "inherit", color: "var(--color-text-on-dark)",
              background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
              opacity: enCours === "import" ? 0.6 : 1,
            }}>
              {enCours === "import"
                ? "Enregistrement…"
                : `Enregistrer ${analyse.documents} document${analyse.documents > 1 ? "s" : ""}`}
            </button>
            <button onClick={reinitialiser} disabled={enCours === "import"} className="sym-tap" style={{
              padding: "11px 20px", borderRadius: 10, cursor: "pointer", fontSize: 14, fontWeight: 600,
              fontFamily: "inherit", background: "transparent", color: "var(--color-text-muted)",
              border: "1.5px solid var(--color-border)",
            }}>
              Annuler
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
