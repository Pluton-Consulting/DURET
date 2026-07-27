import { auth } from "@/lib/auth"
import { redirect } from "next/navigation"
import { canAccess } from "@/lib/permissions"

export default async function ConceptionPage() {
  const session = await auth()
  const role = (session as any)?.user?.role || ""
  if (!canAccess(role, "conception")) redirect("/accueil")

  return (
    <div style={{ padding: 32, maxWidth: 1300, margin: "0 auto" }}>
      <div className="sym-in" style={{ marginBottom: 28 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "-0.5px" }}>
          Conception / Visuels
        </h1>
        <p style={{ margin: "4px 0 0", fontSize: 14, color: "var(--color-text-muted)" }}>
          Agent 2 — Vision multimodale, extraction de plans, pré-chiffrage automatique
        </p>
      </div>

      {/* KPI row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        {[
          { label: "Analyses aujourd'hui" },
          { label: "En attente validation" },
          { label: "Fichiers traités" },
          { label: "Confiance moy." },
        ].map((kpi, i) => (
          <div key={i} className={`sym-in sym-in-${i + 1} sym-card`} style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card-sm, 14px)", padding: 20, boxShadow: "var(--shadow-card)" }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
              {kpi.label}
            </div>
            <div style={{ fontSize: 32, fontWeight: 800, color: "var(--color-text-primary)", letterSpacing: "-0.5px" }}>—</div>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 24 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* Upload zone */}
          <div className="sym-in sym-in-1 sym-card" style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card)", padding: 24, boxShadow: "var(--shadow-card)" }}>
            <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 700, color: "var(--color-text-primary)" }}>
              Analyser un fichier
            </h3>
            <div className="sym-fade" style={{
              border: "2px dashed var(--color-primary-light)", borderRadius: 14,
              padding: "40px 24px", textAlign: "center", background: "var(--color-primary-subtle)",
            }}>
              <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 6 }}>
                Glissez un fichier ici
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-muted)", marginBottom: 16 }}>
                Plans DWG, photos chantier, PDF fiches produits, DXF
              </div>
              <div style={{ fontSize: 12, color: "var(--color-pending-text)", marginBottom: 16 }}>
                Route <code style={{ fontFamily: "monospace" }}>/api/analyse</code> non implémentée
              </div>
              <button disabled style={{
                background: "var(--color-border)", color: "var(--color-text-muted)", border: "none",
                borderRadius: "var(--radius-pill)", padding: "10px 24px", fontSize: 14, fontWeight: 600, cursor: "not-allowed",
              }}>
                Parcourir les fichiers
              </button>
            </div>
            <div style={{ marginTop: 12, display: "flex", gap: 8, flexWrap: "wrap" }}>
              {["DWG (.dwg)", "PDF", "Photos (JPG/PNG)", "DXF"].map((fmt) => (
                <span key={fmt} className="sym-pop sym-tap" style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-muted)", border: "1px solid var(--color-border)", padding: "3px 10px", borderRadius: "var(--radius-pill)" }}>
                  {fmt}
                </span>
              ))}
            </div>
          </div>

          {/* Validations — non implémenté */}
          <div className="sym-in sym-in-2 sym-card" style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card)", padding: 24, boxShadow: "var(--shadow-card)" }}>
            <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 700, color: "var(--color-text-primary)" }}>
              En attente de validation
            </h3>
            <div className="sym-fade" style={{
              padding: "48px 24px", textAlign: "center",
              color: "var(--color-text-muted)", fontSize: 13,
              border: "1.5px dashed var(--color-border)", borderRadius: 12,
            }}>
              Route <code style={{ fontFamily: "monospace", background: "var(--color-canvas)", padding: "2px 6px", borderRadius: 4 }}>/api/validations</code> non implémentée
            </div>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Analyses récentes — non implémenté */}
          <div className="sym-in sym-in-3 sym-card" style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card-sm, 14px)", padding: 20, boxShadow: "var(--shadow-card)" }}>
            <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>
              Analyses récentes
            </h3>
            <div className="sym-fade" style={{
              padding: "32px 16px", textAlign: "center",
              color: "var(--color-text-muted)", fontSize: 12,
              border: "1.5px dashed var(--color-border)", borderRadius: 10,
            }}>
              Route <code style={{ fontFamily: "monospace", background: "var(--color-canvas)", padding: "1px 5px", borderRadius: 3 }}>/api/analyses</code> non implémentée
            </div>
          </div>

          {/* Projets — non implémenté */}
          <div className="sym-in sym-in-4 sym-card" style={{ background: "var(--color-surface)", borderRadius: "var(--radius-card-sm, 14px)", padding: 20, boxShadow: "var(--shadow-card)" }}>
            <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>
              Projets actifs
            </h3>
            <div className="sym-fade" style={{
              padding: "32px 16px", textAlign: "center",
              color: "var(--color-text-muted)", fontSize: 12,
              border: "1.5px dashed var(--color-border)", borderRadius: 10,
            }}>
              Route <code style={{ fontFamily: "monospace", background: "var(--color-canvas)", padding: "1px 5px", borderRadius: 3 }}>/api/projects</code> non implémentée
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
