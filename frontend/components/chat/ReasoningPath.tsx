"use client"

// Colonne latérale : le "chemin de réflexion" de Duret & Sols, façon timeline verticale.
// Les étapes s'allument au fur et à mesure que l'agent progresse (événements WS nœud-par-nœud).
//
// POURQUOI CETTE COLONNE N'EST PAS PASSÉE SUR `ChainOfThought` (AI Elements).
//
// Ce n'est pas un oubli : `ChainOfThoughtStep` ne connaît que trois états
// (terminé, en cours, à venir) là où cette frise en distingue cinq. Les deux
// manquants sont précisément ceux qui portent une information :
//
//   « sauté »  — l'agent est passé PAR-DESSUS cette étape (pas de recherche
//                web, pas de validation humaine). Le trait pointillé le dit.
//                Le rabattre sur « à venir » ferait croire qu'elle va encore
//                arriver, et l'utilisateur l'attendrait pour rien.
//   « inerte » — rien ne tourne. Distinct de « à venir », qui suppose un
//                traitement en cours.
//
// La mise en page non plus n'a pas d'équivalent : la colonne se partage en
// deux zones (frise en haut, cartes en bas plafonnées à 52 %) pour que CE QUI
// ATTEND UNE DÉCISION reste visible sans défiler, et disparaît sous 900 px.
//
// Une frise qui ment sur l'état d'une étape coûte plus cher que la cohérence
// de bibliothèque qu'on gagnerait à l'échanger.

const STAGES: { label: string; desc: string; nodes: string[] }[] = [
  { label: "Analyse", desc: "Nature de la demande", nodes: ["classify", "check_schedule"] },
  { label: "Protection des données", desc: "Anonymisation", nodes: ["rag", "anonymize"] },
  { label: "Orientation", desc: "L'IA décide de la suite", nodes: ["routeur"] },
  { label: "Mémoire d'entreprise", desc: "Recherche documentaire (si besoin)", nodes: ["recherche", "search_docs", "similar_projects"] },
  { label: "Recherche web", desc: "Sources externes (si besoin)", nodes: ["browser"] },
  { label: "Agent spécialisé", desc: "Traitement métier", nodes: ["agent1", "agent2", "agent3", "vision", "extraction", "preprocess", "prechiffrage", "generate_skill", "test_skill"] },
  { label: "Rédaction", desc: "Génération de la réponse", nodes: ["llm", "tools", "rehydrate"] },
  { label: "Validation", desc: "Contrôle humain", nodes: ["human_gate", "validation_check", "submit_validation"] },
]

function stageOf(node: string): number {
  return STAGES.findIndex((s) => s.nodes.includes(node))
}

interface Props {
  steps: string[]
  loading: boolean
  // Le bas de la colonne : cartes des taches en arriere-plan et des accords en
  // attente. Rendu par le parent — cette colonne reste un cadre, elle ne
  // connait ni les taches ni les validations.
  rail?: React.ReactNode
}

export default function ReasoningPath({ steps, loading, rail }: Props) {
  const visited = new Set(steps.map(stageOf).filter((i) => i >= 0))
  const reached = visited.size ? Math.max(...Array.from(visited)) : -1

  const stateOf = (i: number): string => {
    if (visited.has(i)) return loading && i === reached ? "active" : "done"
    if (!loading) return "idle"
    return i < reached ? "skipped" : "pending"
  }

  return (
    <aside className="sym-path sym-fade">
      <style>{`
        @keyframes symNodePulse { 0%,100%{ box-shadow:0 0 0 4px var(--marque-primary-subtle);} 50%{ box-shadow:0 0 0 9px rgba(0,0,0,0);} }
        /* Colonne en deux zones : la frise CONDENSEE en haut (elle defile si la
           place manque), les cartes ancrees en bas. C'est le bas qui porte ce
           qui attend une decision — il doit rester visible sans defilement. */
        .sym-path{ width:26%; min-width:242px; max-width:340px; flex-shrink:0;
          display:flex; flex-direction:column; overflow:hidden;
          border-left:1px solid var(--marque-border); background:var(--marque-surface); padding:16px 18px; }
        .sym-path-haut{ flex:1 1 auto; min-height:0; overflow-y:auto; }
        .sym-path-bas{ flex-shrink:0; max-height:52%; overflow-y:auto; }
        .sym-path-eyebrow{ font-size:11px; letter-spacing:.14em; text-transform:uppercase;
          color:var(--marque-primary-mid); font-weight:700; margin-bottom:3px; }
        .sym-path-title{ font-size:14px; font-weight:700; color:var(--marque-text-primary); margin-bottom:12px; }
        .sym-node{ position:relative; display:grid; grid-template-columns:20px 1fr; gap:10px; padding-bottom:12px; }
        .sym-node:last-child{ padding-bottom:0; }
        .sym-line{ position:absolute; left:9px; top:-12px; width:2px; height:12px; background:var(--marque-border); transition:background .3s; }
        .sym-node.done .sym-line, .sym-node.active .sym-line{ background:var(--marque-primary-mid); }
        .sym-dot{ width:20px; height:20px; border-radius:50%; border:2px solid var(--marque-border);
          background:var(--marque-surface); display:flex; align-items:center; justify-content:center;
          font-size:10px; font-weight:700; color:var(--marque-text-on-dark); z-index:1; transition:all .3s; }
        .sym-node.done .sym-dot{ background:var(--marque-primary); border-color:var(--marque-primary); }
        .sym-node.active .sym-dot{ border-color:var(--marque-primary); animation:symNodePulse 1.4s ease-in-out infinite; }
        .sym-node.pending .sym-dot, .sym-node.idle .sym-dot{ opacity:.55; }
        .sym-node.skipped .sym-dot{ border-style:dashed; opacity:.4; }
        .sym-node-label{ font-size:12.5px; font-weight:600; color:var(--marque-text-primary); }
        .sym-node.active .sym-node-label{ color:var(--marque-primary); }
        .sym-node.pending .sym-node-label, .sym-node.idle .sym-node-label, .sym-node.skipped .sym-node-label{
          color:var(--marque-text-muted); font-weight:500; }
        .sym-node-desc{ font-size:11px; color:var(--marque-text-muted); margin-top:1px; }
        @media (max-width: 900px){ .sym-path{ display:none; } }
        @media (prefers-reduced-motion: reduce){ .sym-node.active .sym-dot{ animation:none; } }
      `}</style>
      <div className="sym-path-haut">
        <div className="sym-path-eyebrow">En coulisses</div>
        <div className="sym-path-title">Chemin de réflexion</div>
        <div>
          {STAGES.map((s, i) => (
            <div className={`sym-node ${stateOf(i)} sym-in sym-in-${Math.min(i + 1, 6)}`} key={s.label}
                 data-testid="etape-reflexion" data-etape={s.label} data-etat={stateOf(i)}>
              {i > 0 && <span className="sym-line" aria-hidden="true" />}
              <span className="sym-dot" aria-hidden="true">{stateOf(i) === "done" ? "✓" : ""}</span>
              <div>
                <div className="sym-node-label">{s.label}</div>
                <div className="sym-node-desc">{s.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
      {rail && <div className="sym-path-bas">{rail}</div>}
    </aside>
  )
}
