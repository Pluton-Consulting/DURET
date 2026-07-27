import { useState } from "react"

type Item = { title: string; body: string }

/** Accordéon (sections dépliables). */
export function Accordion({
  items = [
    { title: "Conditions de règlement", body: "Paiement à 30 jours fin de mois. Acompte de 30 % à la commande." },
    { title: "Garanties", body: "Garantie décennale et biennale. Assurance responsabilité civile professionnelle." },
    { title: "Délais", body: "Démarrage sous 3 semaines après validation du devis et réception de l'acompte." },
  ] as Item[],
}: { items?: Item[] }) {
  const [open, setOpen] = useState(0)
  return (
    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", overflow: "hidden", maxWidth: 400 }}>
      {items.map((it, i) => {
        const on = i === open
        return (
          <div key={i} style={{ borderTop: i ? "1px solid var(--color-border)" : "none" }}>
            <button onClick={() => setOpen(on ? -1 : i)} style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, padding: "13px 16px", background: on ? "var(--color-primary-subtle)" : "transparent", border: "none", cursor: "pointer", fontFamily: "var(--font)", fontSize: 13.5, fontWeight: 600, color: "var(--color-text-primary)", textAlign: "left" }}>
              {it.title}
              <span style={{ color: "var(--color-primary-mid)", transform: on ? "rotate(180deg)" : "none", transition: "transform .2s" }}>⌄</span>
            </button>
            {on && <div style={{ padding: "0 16px 14px", fontSize: 13, color: "var(--color-text-body)", lineHeight: 1.55 }}>{it.body}</div>}
          </div>
        )
      })}
    </div>
  )
}
