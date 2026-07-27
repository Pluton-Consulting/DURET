// Cartes KPI du Dashboard Direction — composant purement présentational.
// Les valeurs sont fournies par le parent (SuperviseurClient) via `data`.

export interface StatsCardsData {
  liveSessions?: number | string | null
  requestsToday?: number | string | null
  costMonth?: number | string | null
  pendingSkills?: number | string | null
}

function fmtNumber(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—"
  return String(v)
}

function fmtEuro(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—"
  const n = Number(v)
  if (Number.isNaN(n)) return "—"
  return `${n.toFixed(2)} €`
}

export default function StatsCards({ data }: { data?: StatsCardsData | null }) {
  const cards = [
    { label: "Sessions live", value: fmtNumber(data?.liveSessions) },
    { label: "Requêtes du jour", value: fmtNumber(data?.requestsToday) },
    { label: "Coût du mois", value: fmtEuro(data?.costMonth) },
    { label: "Skills en attente", value: fmtNumber(data?.pendingSkills) },
  ]

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 20,
        marginBottom: 24,
      }}
    >
      {cards.map((card, i) => {
        const isSignature = i === 0
        return (
          <div
            key={card.label}
            className={`sym-in sym-in-${i + 1} sym-card`}
            style={{
              background: isSignature
                ? "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))"
                : "var(--color-surface)",
              borderRadius: "var(--radius-card)",
              padding: 24,
              boxShadow: "var(--shadow-card)",
            }}
          >
            <div
              style={{
                fontSize: 11,
                fontWeight: 600,
                color: isSignature
                  ? "var(--color-on-dark-accent)"
                  : "var(--color-text-muted)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: 10,
              }}
            >
              {card.label}
            </div>
            <div
              style={{
                fontSize: 36,
                fontWeight: 800,
                color: isSignature
                  ? "var(--color-text-on-dark)"
                  : "var(--color-text-primary)",
                lineHeight: 1,
                letterSpacing: "-1px",
              }}
            >
              {card.value}
            </div>
          </div>
        )
      })}
    </div>
  )
}
