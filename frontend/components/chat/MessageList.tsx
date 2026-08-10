"use client"
import { useEffect, useRef } from "react"
import { MessageRenderer } from "./MessageRenderer"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
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
      {messages.map((msg) =>
        msg.role === "user" ? (
          <div
            key={msg.id}
            className="sym-in sym-card sym-bulle"
            data-testid="message-utilisateur"
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
