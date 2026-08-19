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
  { label: "Je lis votre demande", desc: "de quoi il s'agit, et pour qui", nodes: ["classify", "check_schedule"] },
  { label: "Je protège les noms et coordonnées", desc: "rien de personnel ne sort de l'entreprise", nodes: ["rag", "anonymize"] },
  { label: "Je choisis comment m'y prendre", desc: "mémoire, données, web ou expert", nodes: ["routeur"] },
  { label: "Je cherche dans la mémoire d'entreprise", desc: "dossiers, devis, documents, données", nodes: ["recherche", "search_docs", "similar_projects"] },
  { label: "Je regarde sur le web", desc: "seulement si l'entreprise ne sait pas", nodes: ["browser"] },
  { label: "Je confie à l'expert", desc: "le bon expert pour ce sujet", nodes: ["agent1", "agent2", "agent3", "vision", "extraction", "preprocess", "prechiffrage", "generate_skill", "test_skill"] },
  { label: "J'agis et je rédige", desc: "actions, puis réponse", nodes: ["llm", "tools", "rehydrate"] },
  // `validation_check` A ÉTÉ RETIRÉ DE CETTE ÉTAPE. Il s'exécute à CHAQUE tour
  // — c'est l'arête qui suit la rédaction — si bien que « Validation ✓ Contrôle
  // humain » s'affichait toujours, y compris quand aucun bouton n'était jamais
  // apparu. Relevé par l'utilisateur en production, et à raison : une frise qui
  // coche un contrôle humain qui n'a pas eu lieu ne se trompe pas, elle ment.
  //
  // Ne restent que les nœuds qui ATTESTENT d'une décision : `human_gate`
  // suspend réellement le tour, `submit_validation` dépose une demande. Sans
  // eux l'étape reste vide, comme « Recherche web » quand le web n'a pas servi.
  { label: "Je vous demande votre accord", desc: "pour tout ce qui engage l'entreprise", nodes: ["human_gate", "submit_validation"] },
]

// QUI A PRIS LA MAIN, ET SOUS SON NOM DE MÉTIER.
//
// L'étape s'appelait « Agent spécialisé — Traitement métier » quel que soit
// l'expert qui avait traité la demande. C'est exact et ça n'apprend rien :
// personne n'a à savoir qu'il existe un « agent2 », mais tout le monde gagne à
// savoir que son plan est parti chez celui qui lit les plans.
//
// Déduit des nœuds RÉELLEMENT traversés, jamais annoncé d'avance : tant que la
// demande n'a pas été confiée, l'étape garde son nom générique.
const EXPERTS: { noeuds: string[]; label: string; desc: string }[] = [
  { noeuds: ["agent2", "vision", "extraction", "preprocess", "prechiffrage"],
    label: "Expert conception", desc: "Plans, photos, chiffrage" },
  { noeuds: ["agent3", "generate_skill", "test_skill"],
    label: "Atelier", desc: "Apprentissage d'une compétence" },
  { noeuds: ["agent1"],
    label: "Expert commercial", desc: "Devis, clients, documents" },
]

function expertDe(steps: string[]): { label: string; desc: string } | null {
  const vus = new Set(steps)
  for (const e of EXPERTS) {
    if (e.noeuds.some((n) => vus.has(n))) return { label: e.label, desc: e.desc }
  }
  return null
}

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
  const expert = expertDe(steps)
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
          border-left:1px solid var(--marque-border); background:color-mix(in srgb, var(--marque-primary-subtle) 35%, var(--marque-surface)); padding:18px 18px; }
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
        <div className="sym-path-eyebrow">En ce moment</div>
        <div className="sym-path-title">Ce que fait votre assistant</div>
        <div>
          {STAGES.map((s, i) => {
            // L'étape du spécialiste prend le nom de celui qui a réellement
            // pris la main. Tant que la demande n'a été confiée à personne,
            // elle garde son intitulé générique : nommer un expert avant qu'il
            // ait travaillé serait une promesse, pas une information.
            const nomme = s.label === "Je confie à l'expert" && expert ? expert : s
            return (
              <div className={`sym-node ${stateOf(i)} sym-in sym-in-${Math.min(i + 1, 6)}`} key={s.label}
                   data-testid="etape-reflexion" data-etape={nomme.label} data-etat={stateOf(i)}>
                {i > 0 && <span className="sym-line" aria-hidden="true" />}
                <span className="sym-dot" aria-hidden="true">{stateOf(i) === "done" ? "✓" : ""}</span>
                <div>
                  <div className="sym-node-label">{nomme.label}</div>
                  <div className="sym-node-desc">{nomme.desc}</div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
      {rail && <div className="sym-path-bas">{rail}</div>}
    </aside>
  )
}
