import { auth } from "@/lib/auth"

export default async function CommercialPage() {
  const session = await auth()

  return (
    <div style={{ padding: 32, maxWidth: 1300, margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 28 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "-0.5px" }}>
            Commercial / Admin
          </h1>
          <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--color-text-muted)" }}>
            Agent 1 — RAG, NER, LLM · Requêtes commerciales et administratives
          </p>
        </div>
        <a href="/chat" style={{
          background: "var(--color-primary)", color: "white",
          padding: "12px 24px", borderRadius: 9999, fontSize: 14, fontWeight: 700,
        }}>
          Nouvelle requête
        </a>
      </div>

      {/* KPI row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        {[
          { label: "Requêtes aujourd'hui", value: "—" },
          { label: "Docs indexés", value: "—" },
          { label: "Taux de succès", value: "—" },
          { label: "Temps moyen", value: "—" },
        ].map((kpi, i) => (
          <div key={i} style={{ background: "white", borderRadius: "var(--radius-card-sm, 14px)", padding: 20, boxShadow: "var(--shadow-card)" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
              {kpi.label}
            </div>
            <div style={{ fontSize: 32, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "-0.5px" }}>{kpi.value}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: 24 }}>
        {/* Left */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Conversations — non implémenté */}
          <div style={{ background: "white", borderRadius: "var(--radius-card)", padding: 24, boxShadow: "var(--shadow-card)" }}>
            <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 700, color: "var(--color-text-primary)" }}>
              Requêtes récentes
            </h3>
            <div style={{
              padding: "48px 24px", textAlign: "center",
              color: "var(--color-text-muted)", fontSize: 13,
              border: "1.5px dashed var(--color-border)", borderRadius: 12,
            }}>
              Route <code style={{ fontFamily: "monospace", background: "var(--color-canvas)", padding: "2px 6px", borderRadius: 4 }}>/api/chat/history</code> non implémentée
            </div>
          </div>

          {/* Pipeline status — réel */}
          <div style={{ background: "var(--color-primary)", borderRadius: "var(--radius-card)", padding: 24, boxShadow: "var(--shadow-card)" }}>
            <h3 style={{ margin: "0 0 18px", fontSize: 16, fontWeight: 700, color: "white" }}>Pipeline Agent 1</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                { step: "1. Anonymisation NER", status: "stub", desc: "spaCy fr_core_news_lg — nœud TODO" },
                { step: "2. Recherche RAG", status: "stub", desc: "pgvector + TRGM — nœud TODO" },
                { step: "3. LLM (Claude Haiku)", status: "partial", desc: "Router implémenté — invocation TODO" },
                { step: "4. Réhydratation PII", status: "stub", desc: "Remplacement entity_map — TODO" },
                { step: "5. Vérification devis", status: "stub", desc: "Human-in-the-loop — TODO" },
              ].map((item, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, background: item.status === "partial" ? "#C8E6C0" : "#ffffff44" }} />
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "white" }}>{item.step}</div>
                    <div style={{ fontSize: 11, color: "#A8D4A0" }}>{item.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* RAG — non implémenté */}
          <div style={{ background: "white", borderRadius: "var(--radius-card-sm, 14px)", padding: 20, boxShadow: "var(--shadow-card)" }}>
            <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>
              Index RAG
            </h3>
            <div style={{
              padding: "32px 16px", textAlign: "center",
              color: "var(--color-text-muted)", fontSize: 12,
              border: "1.5px dashed var(--color-border)", borderRadius: 10,
            }}>
              Pipeline d'ingestion non implémenté
            </div>
          </div>

          {/* Routage LLM — non implémenté */}
          <div style={{ background: "white", borderRadius: "var(--radius-card-sm, 14px)", padding: 20, boxShadow: "var(--shadow-card)" }}>
            <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>
              Routage LLM
            </h3>
            <div style={{
              padding: "32px 16px", textAlign: "center",
              color: "var(--color-text-muted)", fontSize: 12,
              border: "1.5px dashed var(--color-border)", borderRadius: 10,
            }}>
              Route <code style={{ fontFamily: "monospace", background: "var(--color-canvas)", padding: "1px 5px", borderRadius: 3 }}>/api/stats/llm</code> non implémentée
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
