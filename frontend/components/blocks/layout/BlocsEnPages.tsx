"use client"
/**
 * PLUSIEURS TABLEAUX DANS UNE RÉPONSE : UN À LA FOIS, AVEC DES FLÈCHES (15/09).
 *
 * Relevé de Noa : « il affiche beaucoup trop le composant de tableau ; quand il
 * y en a cinq ou six à la suite, c'est beaucoup trop grand. Il faudrait qu'il
 * en affiche un et qu'il mette une petite flèche pour passer de 1 à 2, comme
 * le composant de mail ». Même geste que les cartes de réponses aux mails
 * (`ReponsesMail`) : un seul bloc à l'écran, « 2 sur 5 » entre deux flèches.
 * Rien n'est perdu : chaque bloc garde son composant, on ne fait que tourner
 * les pages.
 */
import { useState, type ReactNode } from "react"

export function BlocsEnPages({ blocs, rendre, libelle = "Tableau" }:
  { blocs: any[]; rendre: (bloc: any) => ReactNode; libelle?: string }) {
  const [page, setPage] = useState(0)
  const n = blocs.length
  const sure = Math.min(page, Math.max(0, n - 1))
  if (!n) return null
  return (
    <div className="sym-bp" data-testid="blocs-en-pages">
      <style>{`
        .sym-bp{ display:grid; gap:10px; width:100%; }
        .sym-bp-barre{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
        .sym-bp-titre{ font-size:13px; font-weight:600; color:var(--marque-text-primary); min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .sym-bp-pages{ display:flex; align-items:center; gap:10px; font-size:12px; color:var(--marque-text-muted); margin-left:auto; }
        .sym-bp-fleche{ width:30px; height:30px; border-radius:50%; border:1px solid var(--marque-border);
          background:var(--marque-surface, #fff); color:var(--marque-text-primary); font-size:18px; line-height:1; cursor:pointer; }
        .sym-bp-fleche:hover:not(:disabled){ background:var(--marque-primary-subtle); }
        .sym-bp-fleche:disabled{ opacity:.35; cursor:default; }
      `}</style>
      <div className="sym-bp-barre">
        {/* Le titre de chaque tableau est rendu par le tableau lui-même. */}
        <span className="sym-bp-titre">{n} {libelle.toLowerCase()}x</span>
        <div className="sym-bp-pages">
          <button type="button" className="sym-bp-fleche" aria-label={`${libelle} précédent`}
                  disabled={sure === 0} onClick={() => setPage(Math.max(0, sure - 1))}>‹</button>
          <span>{sure + 1} sur {n}</span>
          <button type="button" className="sym-bp-fleche" aria-label={`${libelle} suivant`}
                  disabled={sure >= n - 1} onClick={() => setPage(Math.min(n - 1, sure + 1))}>›</button>
        </div>
      </div>
      <div key={sure}>{rendre(blocs[sure])}</div>
    </div>
  )
}
