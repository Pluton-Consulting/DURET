// Flux d'activité (événements d'audit) du Dashboard Direction.
// Composant présentational — les entrées sont fournies via `items`.

export interface ActivityItem {
  id: string
  action: string
  agent_id?: string | null
  success?: boolean
  created_at?: string
  model_used?: string | null
  [key: string]: any
}

function formatTime(iso?: string): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  return d.toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function ActivityFeed({ items }: { items?: ActivityItem[] | null }) {
  const list = Array.isArray(items) ? items : []

  return (
    <div
      className="sym-in sym-card"
      style={{
        background: "var(--marque-surface)",
        borderRadius: "var(--marque-radius-card)",
        padding: 24,
        boxShadow: "var(--marque-shadow-card)",
      }}
    >
      <h3
        style={{
          margin: "0 0 16px",
          fontSize: 16,
          fontWeight: 700,
          color: "var(--marque-text-primary)",
        }}
      >
        Activité récente
      </h3>

      {list.length === 0 ? (
        <div
          className="sym-fade"
          style={{
            padding: "32px 0",
            textAlign: "center",
            color: "var(--marque-text-muted)",
            fontSize: 13,
          }}
        >
          Aucune activité enregistrée
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column" }}>
          {list.map((item, i) => {
            const ok = item.success !== false
            return (
              <div
                key={item.id ?? i}
                className={`sym-in sym-in-${Math.min(i + 1, 6)}`}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 12,
                  padding: "11px 0",
                  borderBottom:
                    i < list.length - 1 ? "1px solid var(--marque-border)" : "none",
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    marginTop: 5,
                    flexShrink: 0,
                    background: ok
                      ? "var(--marque-paid-text)"
                      : "var(--marque-error-text)",
                  }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 500,
                      color: "var(--marque-text-primary)",
                      lineHeight: 1.4,
                    }}
                  >
                    {item.action}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--marque-text-muted)",
                      marginTop: 2,
                    }}
                  >
                    {item.agent_id ? `Agent ${item.agent_id}` : "Système"}
                    {item.created_at ? ` · ${formatTime(item.created_at)}` : ""}
                  </div>
                </div>
                <span
                  className="sym-pop"
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    flexShrink: 0,
                    padding: "3px 10px",
                    borderRadius: "var(--marque-radius-pill)",
                    color: ok ? "var(--marque-paid-text)" : "var(--marque-error-text)",
                    background: ok ? "var(--marque-paid-bg)" : "var(--marque-error-bg)",
                  }}
                >
                  {ok ? "Succès" : "Échec"}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
