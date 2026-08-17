import type { CSSProperties } from "react"

type Line = {
  label?: string; qty?: string; price?: string          // forme COURTE (résumé)
  n?: string | number                                    // forme LONGUE (document)
  description?: string; unite?: string; qte?: string | number
  pu?: string; montant?: string
  section?: string                                       // intertitre de lot
}
type Status = "draft" | "sent" | "accepted"

const STATUS: Record<Status, { label: string; bg: string; fg: string }> = {
  draft:    { label: "Brouillon", bg: "var(--marque-pending-bg)", fg: "var(--marque-pending-text)" },
  sent:     { label: "Envoyé",    bg: "var(--marque-paid-bg)",    fg: "var(--marque-paid-text)" },
  accepted: { label: "Accepté",   bg: "var(--marque-paid-bg)",    fg: "var(--marque-paid-text)" },
}

/** DEUX DEVIS POUR UN SEUL BLOC.
 *
 *  Le résumé — trois colonnes, 480 px — répond à « où en est le devis 017 ? ».
 *  Il ne répond pas à « montre-moi le devis » : demandé en chat, le modèle
 *  écrivait alors l'en-tête en markdown, le tableau en markdown, le total en
 *  markdown, et l'écran affichait trois morceaux qui ne formaient pas un
 *  document. Un devis, ça se lit d'un bloc : émetteur, client, objet, lots,
 *  lignes chiffrées, totaux, conditions.
 *
 *  Le même type `quote` porte les deux : c'est la FORME DES LIGNES qui décide.
 *  Une ligne qui porte `description` (ou un en-tête, des totaux, un pied) est
 *  un document et prend toute la largeur ; une ligne `label` reste la carte
 *  compacte d'avant. Rien à réapprendre pour le modèle, et aucune des deux
 *  écritures existantes ne casse.
 */
export function QuoteCard({
  id = "DEV-2024-017",
  client = "SCI Dupont · Résidence Les Tilleuls",
  status = "draft",
  total = "10 380,00 €",
  lines = [
    { label: "Ragréage sol P3", qty: "120 m²", price: "2 160,00 €" },
    { label: "Carrelage grès cérame 60×60", qty: "120 m²", price: "5 400,00 €" },
    { label: "Plinthes assorties", qty: "85 ml", price: "1 020,00 €" },
    { label: "Pose + joints (forfait)", qty: "1", price: "1 800,00 €" },
  ],
  emetteur, adresse, date, objet, suivi_par, reference,
  totals, footer, mentions,
}: {
  id?: string; client?: string; status?: Status; total?: string; lines?: Line[]
  emetteur?: string; adresse?: string | string[]; date?: string; objet?: string
  suivi_par?: string; reference?: string
  totals?: { ht?: string; tva?: string; taux?: string; ttc?: string; acompte?: string }
  footer?: string; mentions?: string | string[]
}) {
  const st = STATUS[status] ?? STATUS.draft
  const document = lines.some((l) => l.description !== undefined || l.section !== undefined)
    || !!(adresse || date || objet || totals || footer || mentions || suivi_par)

  if (!document) return <Resume {...{ id, client, st, total, lines }} />

  const adr = Array.isArray(adresse) ? adresse : adresse ? [adresse] : []
  const bas = Array.isArray(mentions) ? mentions : mentions ? [mentions] : []

  return (
    <div style={cadre}>
      {/* EN-TÊTE — l'émetteur à gauche, la référence à droite, comme sur papier. */}
      <div style={entete}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: "-.2px" }}>
            {emetteur || "Devis"}
          </div>
          {objet && <div style={{ fontSize: 12.5, color: "var(--marque-on-dark-accent)", marginTop: 3 }}>{objet}</div>}
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>N° {reference || id}</div>
          {date && <div style={{ fontSize: 12, color: "var(--marque-on-dark-accent)", marginTop: 3 }}>{date}</div>}
          <span style={{ ...pastille, background: st.bg, color: st.fg, marginTop: 6, display: "inline-block" }}>{st.label}</span>
        </div>
      </div>

      {/* DESTINATAIRE — dans le même cadre, pas au-dessus dans du texte libre. */}
      <div style={destinataire}>
        <div style={{ minWidth: 0 }}>
          <div style={etiquette}>Client</div>
          <div style={{ fontWeight: 700, color: "var(--marque-text-primary)", marginTop: 3 }}>{client}</div>
          {adr.map((l, i) => (
            <div key={i} style={{ color: "var(--marque-text-body)", fontSize: 13 }}>{l}</div>
          ))}
        </div>
        {suivi_par && (
          <div style={{ textAlign: "right", flexShrink: 0 }}>
            <div style={etiquette}>Suivi par</div>
            <div style={{ fontWeight: 700, color: "var(--marque-text-primary)", marginTop: 3 }}>{suivi_par}</div>
          </div>
        )}
      </div>

      {/* LES LIGNES. Le conteneur défile plutôt que de pousser la page. */}
      <div className="sym-defile">
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
          <thead>
            <tr>
              <th style={{ ...thh, width: 44 }}>N°</th>
              <th style={thh}>Description</th>
              <th style={{ ...thh, textAlign: "center", whiteSpace: "nowrap" }}>Unité</th>
              <th style={{ ...thh, textAlign: "right", whiteSpace: "nowrap" }}>Qté</th>
              <th style={{ ...thh, textAlign: "right", whiteSpace: "nowrap" }}>PU HT</th>
              <th style={{ ...thh, textAlign: "right", whiteSpace: "nowrap" }}>Montant HT</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) =>
              l.section ? (
                // INTERTITRE DE LOT : une ligne pleine largeur, pas une cellule
                // vide répétée six fois — c'est ce qui donne au devis sa structure.
                <tr key={i}>
                  <td colSpan={6} style={lot}>{l.section}</td>
                </tr>
              ) : (
                <tr key={i}>
                  <td style={{ ...td, textAlign: "center", color: "var(--marque-text-muted)", fontVariantNumeric: "tabular-nums" }}>{l.n ?? ""}</td>
                  <td style={{ ...td, color: "var(--marque-text-primary)" }}>{l.description ?? l.label}</td>
                  <td style={{ ...td, textAlign: "center", whiteSpace: "nowrap" }}>{l.unite ?? ""}</td>
                  <td style={{ ...td, textAlign: "right", ...chiffres }}>{l.qte ?? l.qty ?? ""}</td>
                  <td style={{ ...td, textAlign: "right", ...chiffres }}>{l.pu ?? ""}</td>
                  <td style={{ ...td, textAlign: "right", ...chiffres, fontWeight: 600, color: "var(--marque-text-primary)" }}>{l.montant ?? l.price ?? ""}</td>
                </tr>
              )
            )}
          </tbody>
        </table>
      </div>

      {/* TOTAUX — alignés à droite, le TTC seul mis en avant. */}
      <div style={{ display: "flex", justifyContent: "flex-end", padding: "14px 20px", background: "var(--marque-primary-subtle)", borderTop: "2px solid var(--marque-primary-light)" }}>
        <table style={{ borderCollapse: "collapse", fontSize: 13.5, minWidth: 260 }}>
          <tbody>
            <Ligne titre="Total HT" valeur={totals?.ht ?? total} />
            {totals?.tva && <Ligne titre={`TVA${totals.taux ? ` ${totals.taux}` : ""}`} valeur={totals.tva} />}
            {totals?.ttc && <Ligne titre="Total TTC" valeur={totals.ttc} fort />}
            {totals?.acompte && <Ligne titre="Acompte à la commande" valeur={totals.acompte} />}
          </tbody>
        </table>
      </div>

      {(footer || bas.length > 0) && (
        <div style={pied}>
          {footer && <div style={{ marginBottom: bas.length ? 6 : 0 }}>{footer}</div>}
          {bas.map((m, i) => <div key={i}>{m}</div>)}
        </div>
      )}
    </div>
  )
}

/** La carte compacte d'origine, inchangée : un devis qu'on cite, pas qu'on lit. */
function Resume({ id, client, st, total, lines }: any) {
  return (
    <div style={{ ...cadre, maxWidth: 480 }}>
      <div style={{ ...entete, padding: "15px 18px" }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 800, letterSpacing: "-.2px" }}>Devis {id}</div>
          <div style={{ fontSize: 12, color: "var(--marque-on-dark-accent)", marginTop: 2 }}>{client}</div>
        </div>
        <span style={{ ...pastille, background: st.bg, color: st.fg, height: "fit-content" }}>{st.label}</span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            <th style={thh}>Poste</th><th style={{ ...thh, textAlign: "right" }}>Qté</th><th style={{ ...thh, textAlign: "right" }}>Total HT</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l: Line, i: number) => (
            <tr key={i}>
              <td style={{ ...td, color: "var(--marque-text-primary)", fontWeight: 600 }}>{l.label}</td>
              <td style={{ ...td, textAlign: "right", ...chiffres }}>{l.qty}</td>
              <td style={{ ...td, textAlign: "right", ...chiffres }}>{l.price}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "13px 18px", borderTop: "2px solid var(--marque-primary-light)", background: "var(--marque-primary-subtle)" }}>
        <span style={etiquette}>Total HT</span>
        <span style={{ fontSize: 19, fontWeight: 800, color: "var(--marque-primary)", fontVariantNumeric: "tabular-nums" }}>{total}</span>
      </div>
    </div>
  )
}

function Ligne({ titre, valeur, fort }: { titre: string; valeur: string; fort?: boolean }) {
  return (
    <tr>
      <td style={{ padding: "5px 18px 5px 0", color: fort ? "var(--marque-text-primary)" : "var(--marque-text-muted)", fontWeight: fort ? 700 : 600, textTransform: fort ? "none" : "uppercase", fontSize: fort ? 14 : 11.5, letterSpacing: fort ? "normal" : ".05em" }}>{titre}</td>
      <td style={{ padding: "5px 0", textAlign: "right", ...chiffres, fontWeight: fort ? 800 : 600, fontSize: fort ? 19 : 14, color: fort ? "var(--marque-primary)" : "var(--marque-text-primary)" }}>{valeur}</td>
    </tr>
  )
}

const cadre: CSSProperties = { background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden", width: "100%" }
const entete: CSSProperties = { background: "linear-gradient(135deg, var(--marque-primary), var(--marque-primary-hover))", color: "var(--marque-text-on-dark)", padding: "17px 20px", display: "flex", justifyContent: "space-between", gap: 16 }
const destinataire: CSSProperties = { display: "flex", justifyContent: "space-between", gap: 16, padding: "14px 20px", borderBottom: "1px solid var(--marque-border)", fontSize: 13.5 }
const pied: CSSProperties = { padding: "13px 20px", borderTop: "1px solid var(--marque-border)", fontSize: 12, color: "var(--marque-text-muted)", lineHeight: 1.6 }
const pastille: CSSProperties = { fontSize: 11, fontWeight: 700, padding: "4px 10px", borderRadius: "var(--marque-radius-pill)", whiteSpace: "nowrap" }
const etiquette: CSSProperties = { fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--marque-text-muted)" }
const lot: CSSProperties = { padding: "10px 20px", background: "var(--marque-primary-subtle)", borderTop: "1px solid var(--marque-border)", fontWeight: 800, fontSize: 12, textTransform: "uppercase", letterSpacing: ".04em", color: "var(--marque-primary)" }
const chiffres: CSSProperties = { fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }
const thh: CSSProperties = { textAlign: "left", fontSize: 10.5, textTransform: "uppercase", letterSpacing: ".05em", color: "var(--marque-text-muted)", fontWeight: 700, padding: "10px 20px", background: "var(--marque-primary-subtle)" }
const td: CSSProperties = { padding: "11px 20px", borderTop: "1px solid var(--marque-border)", color: "var(--marque-text-body)", verticalAlign: "top" }
