import { md } from "../text/inline"

/**
 * COMPTE RENDU DE RÉUNION — bloc MÉCANIQUE, écrit par le backend
 * (`skills/reunion.py`), jamais par le modèle.
 *
 * POURQUOI CE COMPOSANT PLUTÔT QU'UN TEXTE. Un compte rendu se LIT en
 * diagonale : on cherche « qu'est-ce qui a été décidé » et « qu'est-ce que je
 * dois faire ». En prose, ces deux réponses sont noyées dans le reste. Ici les
 * décisions ont leur bloc, et les actions leur tableau — avec la colonne qui
 * compte : QUI, et POUR QUAND.
 *
 * LE TROU EST MONTRÉ, PAS COMBLÉ. Une action dont personne n'a pris la charge
 * affiche « à désigner », une échéance non dite affiche « à fixer », tous deux
 * en gris. C'est le pendant à l'écran de la règle du skill : ne jamais deviner
 * un responsable. Une réunion qui distribue mal ses tâches doit se voir.
 */
interface Action { quoi?: string; qui?: string; quand?: string }
interface Section { titre?: string; items?: string[] }

export function CompteRendu({ titre, sous_titre, resume = "", participants, sections, actions }: {
  titre?: string
  sous_titre?: string
  resume?: string
  participants?: string[]
  sections?: Section[]
  actions?: Action[]
}) {
  const manquant: React.CSSProperties = { color: "var(--marque-text-muted)", fontStyle: "italic" }

  return (
    <div style={{
      background: "var(--marque-surface)", border: "1px solid var(--marque-border)",
      borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)",
      maxWidth: "min(var(--bloc-largeur), 100%)", width: "100%", overflow: "hidden",
    }}>
      {(titre || sous_titre) && (
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--marque-border)" }}>
          {titre && (
            <div style={{ fontSize: 14, fontWeight: 700, color: "var(--marque-text-primary)" }}>
              {titre}
            </div>
          )}
          {sous_titre && (
            <div style={{ fontSize: 11.5, color: "var(--marque-text-muted)", marginTop: 2 }}>
              {sous_titre}
            </div>
          )}
        </div>
      )}

      <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 14 }}>
        {resume && (
          <div style={{ fontSize: 13, lineHeight: 1.6, color: "var(--marque-text-body)" }}>
            {md(resume)}
          </div>
        )}

        {participants && participants.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {participants.map((p, i) => (
              <span key={i} style={{
                fontSize: 11.5, fontWeight: 600, padding: "2px 9px",
                borderRadius: "var(--marque-radius-pill)",
                background: "var(--marque-primary-subtle)", color: "var(--marque-primary)",
              }}>{p}</span>
            ))}
          </div>
        )}

        {(sections ?? []).filter((s) => (s.items ?? []).length > 0).map((s, i) => (
          <div key={i}>
            <div style={{
              fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em",
              color: "var(--marque-text-muted)", marginBottom: 5,
            }}>{s.titre}</div>
            <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 4 }}>
              {(s.items ?? []).map((item, j) => (
                <li key={j} style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--marque-text-body)" }}>
                  {md(item)}
                </li>
              ))}
            </ul>
          </div>
        ))}

        {actions && actions.length > 0 && (
          <div>
            <div style={{
              fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em",
              color: "var(--marque-text-muted)", marginBottom: 5,
            }}>Actions</div>
            {/* Un tableau, pas une liste : « qui » et « quand » sont deux
                colonnes qu'on balaie du regard. Il défile seul si l'écran est
                étroit — le corps de la page, lui, ne défile jamais en largeur. */}
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5 }}>
                <tbody>
                  {actions.map((a, i) => (
                    <tr key={i} style={{ borderTop: i ? "1px solid var(--marque-border)" : "none" }}>
                      <td style={{ padding: "6px 10px 6px 0", color: "var(--marque-text-body)", lineHeight: 1.5 }}>
                        {md(a.quoi ?? "")}
                      </td>
                      <td style={{ padding: "6px 10px", whiteSpace: "nowrap", fontWeight: 600, color: "var(--marque-text-primary)" }}>
                        {a.qui ? a.qui : <span style={manquant}>à désigner</span>}
                      </td>
                      <td style={{ padding: "6px 0", whiteSpace: "nowrap", color: "var(--marque-text-muted)" }}>
                        {a.quand ? a.quand : <span style={manquant}>à fixer</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
