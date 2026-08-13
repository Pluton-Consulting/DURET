"use client"
import { useEffect, useRef } from "react"
import { MessageRenderer } from "./MessageRenderer"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  // La tache qui a produit ce message, quand elle tourne EN ARRIERE-PLAN.
  // Ces bulles-la se dessinent en creux : contour pointille, fond blanc,
  // opacite reduite — elles marquent la place d'un echange dont le detail
  // s'affiche a droite, et qui reviendra ici une fois abouti.
  tacheId?: string
  // Bulle d'attente de la reponse : elle tient le rang du message a venir.
  // Sans elle, la reponse d'une tache de fond apparaitrait bien plus bas,
  // apres les echanges qui l'ont doublee, detachee de sa question.
  placeholder?: boolean
}

export default function MessageList({ messages, onAction, apiUrl, backendToken }:
  { messages: Message[]; onAction?: (v: string) => void; apiUrl?: string; backendToken?: string }) {
  const finRef = useRef<HTMLDivElement>(null)
  const conteneurRef = useRef<HTMLDivElement>(null)
  // L'utilisateur suit-il le fil, ou est-il remonté pour relire ? Cette intention
  // ne se mesure QUE pendant qu'il fait défiler.
  const suitLeFil = useRef(true)

  // Mesurer la position APRÈS l'ajout d'un message ne dit rien de son intention :
  // le message qui vient d'arriver a déjà allongé le conteneur, donc la distance
  // au bas vaut la hauteur de ce message. La vue paraît « remontée » alors que
  // personne n'a rien remonté, et le défilement ne repart jamais.
  // On note donc l'intention au moment du défilement, où la géométrie est encore
  // celle que l'utilisateur voit.
  const surDefilement = () => {
    const boite = conteneurRef.current
    if (!boite) return
    suitLeFil.current = boite.scrollHeight - boite.scrollTop - boite.clientHeight < 150
  }

  useEffect(() => {
    if (suitLeFil.current || messages.length <= 1) {
      finRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
    }
  }, [messages])

  return (
    <div ref={conteneurRef} onScroll={surDefilement} data-testid="liste-messages" style={{
      flex: 1,
      overflow: "auto",
      padding: "24px 32px",
      display: "flex",
      flexDirection: "column",
      gap: 16,
    }}>
      {messages.length === 0 && (
        <div className="sym-in" style={{ textAlign: "center", marginTop: 80 }}>
          <p style={{ margin: 0, fontSize: 17, fontWeight: 500, color: "var(--color-text-body)" }}>Posez votre question pour démarrer.</p>
        </div>
      )}
      <style>{`
        /* Une bulle EN ATTENTE se dessine en creux : le fond plein revient
           quand la reponse arrive. Le pointille dit « ce n'est pas fini »
           sans rien ajouter a l'ecran, et l'opacite l'eloigne juste assez
           pour que la conversation en cours reste au premier plan. */
        .sym-attente{ opacity:.62; box-shadow:none!important; transition:opacity .3s ease; }
        .sym-attente:hover{ opacity:.85; }
        .sym-attente-moi{ background:var(--color-surface)!important;
          color:var(--color-primary)!important;
          border:1.5px dashed var(--color-primary)!important; }
        .sym-attente-ia{ border:1.5px dashed var(--color-border);
          border-radius:var(--radius-card-sm); padding:12px 16px;
          color:var(--color-text-muted); font-size:13.5px; font-style:italic;
          display:flex; align-items:center; gap:9px; }
        @keyframes symPointille { to { background-position: 22px 0 } }
        .sym-attente-fil{ flex:1; height:2px; border-radius:1px;
          background:repeating-linear-gradient(90deg,
            var(--color-border) 0 6px, transparent 6px 11px);
          background-size:22px 2px; animation:symPointille 1.1s linear infinite; }
        @media (prefers-reduced-motion: reduce){ .sym-attente-fil{ animation:none } }
      `}</style>
      {messages.map((msg) =>
        msg.role === "user" ? (
          <div
            key={msg.id}
            className={`sym-in sym-card sym-bulle${msg.tacheId ? " sym-attente sym-attente-moi" : ""}`}
            data-testid="message-utilisateur"
            data-en-attente={msg.tacheId ? "oui" : undefined}
            style={{
              alignSelf: "flex-end",
              maxWidth: "70%",
              background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))",
              color: "var(--color-text-on-dark)",
              padding: "12px 16px",
              borderRadius: "var(--radius-card-sm)",
              boxShadow: "var(--shadow-card)",
              border: "none",
              fontSize: 14,
              lineHeight: 1.5,
              whiteSpace: "pre-wrap",
            }}
          >
            {msg.content}
          </div>
        ) : msg.placeholder ? (
          // La reponse n'est pas encore la : on tient sa place. Le detail de
          // l'avancement vit dans la colonne de droite — le repeter ici ferait
          // deux endroits a suivre pour une seule chose.
          <div key={msg.id} data-testid="message-assistant" data-en-attente="oui"
               className="sym-in sym-attente sym-attente-ia"
               style={{ alignSelf: "flex-start", maxWidth: "70%", minWidth: 260 }}>
            <span>{msg.content || "réponse en cours"}</span>
            <span className="sym-attente-fil" aria-hidden="true" />
          </div>
        ) : (
          <div key={msg.id} data-testid="message-assistant"
               style={{ alignSelf: "flex-start", maxWidth: "100%" }}>
            <MessageRenderer content={msg.content} onAction={onAction}
                             apiUrl={apiUrl} backendToken={backendToken} />
          </div>
        )
      )}
      {/* Ancre de défilement : toujours en dernier. */}
      <div ref={finRef} />
    </div>
  )
}
