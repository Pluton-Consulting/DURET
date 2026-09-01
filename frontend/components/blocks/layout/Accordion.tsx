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
    <div style={{ background: "var(--marque-surface)", border: "1px solid var(--marque-border)", borderRadius: "var(--marque-radius-card-sm)", boxShadow: "var(--marque-shadow-card)", overflow: "hidden", maxWidth: "min(var(--bloc-largeur), 100%)" }}>
      {items.map((it, i) => {
        const on = i === open
        return (
          <div key={i} style={{ borderTop: i ? "1px solid var(--marque-border)" : "none" }}>
            <button onClick={() => setOpen(on ? -1 : i)} style={{ width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, padding: "13px 16px", background: on ? "var(--marque-primary-subtle)" : "transparent", border: "none", cursor: "pointer", fontFamily: "var(--marque-font)", fontSize: 13.5, fontWeight: 600, color: "var(--marque-text-primary)", textAlign: "left" }}>
              {it.title}
              <span style={{ color: "var(--marque-primary-mid)", transform: on ? "rotate(180deg)" : "none", transition: "transform .2s" }}>⌄</span>
            </button>
            {on && <div style={{ padding: "0 16px 14px", fontSize: 13, color: "var(--marque-text-body)", lineHeight: 1.55 }}>{it.body}</div>}
          </div>
        )
      })}
    </div>
  )
}
