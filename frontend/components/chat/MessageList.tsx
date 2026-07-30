"use client"
import { useEffect, useRef } from "react"
import { MessageRenderer } from "./MessageRenderer"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
}

export default function MessageList({ messages, onAction }: { messages: Message[]; onAction?: (v: string) => void }) {
  const finRef = useRef<HTMLDivElement>(null)
  const conteneurRef = useRef<HTMLDivElement>(null)

  // Descend sur le dernier message à chaque nouveau message.
  // On ne le fait PAS si l'utilisateur a remonté le fil pour relire : lui ramener
  // la vue de force pendant qu'il lit serait pire que l'absence de défilement.
  useEffect(() => {
    const boite = conteneurRef.current
    if (!boite) return
    const enBas = boite.scrollHeight - boite.scrollTop - boite.clientHeight < 150
    if (enBas || messages.length <= 1) {
      finRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
    }
  }, [messages])

  return (
    <div ref={conteneurRef} style={{
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
            className="sym-in sym-card"
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
          <div key={msg.id} style={{ alignSelf: "flex-start", maxWidth: "100%" }}>
            <MessageRenderer content={msg.content} onAction={onAction} />
          </div>
        )
      )}
      {/* Ancre de défilement : toujours en dernier. */}
      <div ref={finRef} />
    </div>
  )
}
