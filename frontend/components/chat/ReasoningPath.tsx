"use client"

// Colonne latérale : le "chemin de réflexion" de Duret & Sols, façon timeline verticale.
// Les étapes s'allument au fur et à mesure que l'agent progresse (événements WS nœud-par-nœud).

const STAGES: { label: string; desc: string; nodes: string[] }[] = [
  { label: "Routeur", desc: "Analyse & orientation", nodes: ["classify", "check_schedule"] },
  { label: "Mémoire d'entreprise", desc: "Recherche documentaire", nodes: ["rag", "search_docs", "similar_projects"] },
  { label: "Protection des données", desc: "Anonymisation", nodes: ["anonymize"] },
  { label: "Recherche web", desc: "Sources externes (si besoin)", nodes: ["browser"] },
  { label: "Agent spécialisé", desc: "Traitement métier", nodes: ["agent1", "agent2", "agent3", "vision", "extraction", "preprocess", "prechiffrage", "generate_skill", "test_skill"] },
  { label: "Rédaction", desc: "Génération de la réponse", nodes: ["llm", "rehydrate"] },
  { label: "Validation", desc: "Contrôle humain", nodes: ["human_gate", "validation_check", "submit_validation"] },
]

function stageOf(node: string): number {
  return STAGES.findIndex((s) => s.nodes.includes(node))
}

interface Props {
  steps: string[]
  loading: boolean
}

export default function ReasoningPath({ steps, loading }: Props) {
  const visited = new Set(steps.map(stageOf).filter((i) => i >= 0))
  const reached = visited.size ? Math.max(...Array.from(visited)) : -1

  const stateOf = (i: number): string => {
    if (visited.has(i)) return loading && i === reached ? "active" : "done"
    if (!loading) return "idle"
    return i < reached ? "skipped" : "pending"
  }

  return (
    <aside className="sym-path">
      <style>{`
        @keyframes symNodePulse { 0%,100%{ box-shadow:0 0 0 4px var(--color-primary-subtle);} 50%{ box-shadow:0 0 0 9px rgba(0,0,0,0);} }
        .sym-path{ width:26%; min-width:242px; max-width:340px; flex-shrink:0; overflow-y:auto;
          border-left:1px solid var(--color-border); background:var(--color-surface); padding:24px 22px; }
        .sym-path-eyebrow{ font-size:11px; letter-spacing:.14em; text-transform:uppercase;
          color:var(--color-primary-mid); font-weight:700; margin-bottom:4px; }
        .sym-path-title{ font-size:15px; font-weight:700; color:var(--color-text-primary); margin-bottom:20px; }
        .sym-node{ position:relative; display:grid; grid-template-columns:24px 1fr; gap:13px; padding-bottom:22px; }
        .sym-node:last-child{ padding-bottom:0; }
        .sym-line{ position:absolute; left:11px; top:-22px; width:2px; height:22px; background:var(--color-border); transition:background .3s; }
        .sym-node.done .sym-line, .sym-node.active .sym-line{ background:var(--color-primary-mid); }
        .sym-dot{ width:24px; height:24px; border-radius:50%; border:2px solid var(--color-border);
          background:var(--color-surface); display:flex; align-items:center; justify-content:center;
          font-size:12px; font-weight:700; color:#fff; z-index:1; transition:all .3s; }
        .sym-node.done .sym-dot{ background:var(--color-primary); border-color:var(--color-primary); }
        .sym-node.active .sym-dot{ border-color:var(--color-primary); animation:symNodePulse 1.4s ease-in-out infinite; }
        .sym-node.pending .sym-dot, .sym-node.idle .sym-dot{ opacity:.55; }
        .sym-node.skipped .sym-dot{ border-style:dashed; opacity:.4; }
        .sym-node-label{ font-size:13.5px; font-weight:600; color:var(--color-text-primary); }
        .sym-node.active .sym-node-label{ color:var(--color-primary); }
        .sym-node.pending .sym-node-label, .sym-node.idle .sym-node-label, .sym-node.skipped .sym-node-label{
          color:var(--color-text-muted); font-weight:500; }
        .sym-node-desc{ font-size:11.5px; color:var(--color-text-muted); margin-top:2px; }
        @media (max-width: 900px){ .sym-path{ display:none; } }
        @media (prefers-reduced-motion: reduce){ .sym-node.active .sym-dot{ animation:none; } }
      `}</style>
      <div className="sym-path-eyebrow">En coulisses</div>
      <div className="sym-path-title">Chemin de réflexion</div>
      <div>
        {STAGES.map((s, i) => (
          <div className={`sym-node ${stateOf(i)}`} key={s.label}>
            {i > 0 && <span className="sym-line" aria-hidden="true" />}
            <span className="sym-dot" aria-hidden="true">{stateOf(i) === "done" ? "✓" : ""}</span>
            <div>
              <div className="sym-node-label">{s.label}</div>
              <div className="sym-node-desc">{s.desc}</div>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
