interface Message {
  id: string
  role: "user" | "assistant"
  content: string
}

export default function MessageList({ messages }: { messages: Message[] }) {
  return (
    <div style={{
      flex: 1,
      overflow: "auto",
      padding: "24px 32px",
      display: "flex",
      flexDirection: "column",
      gap: 16,
    }}>
      {messages.length === 0 && (
        <div style={{ textAlign: "center", marginTop: 80 }}>
          <p style={{ margin: 0, fontSize: 17, fontWeight: 500, color: "var(--color-text-body)" }}>Bonjour, comment puis-je vous aider ?</p>
        </div>
      )}
      {messages.map((msg) => (
        <div
          key={msg.id}
          style={{
            alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
            maxWidth: "70%",
            background: msg.role === "user" ? "var(--color-primary)" : "var(--color-surface)",
            color: msg.role === "user" ? "#fff" : "var(--color-text-primary)",
            padding: "12px 16px",
            borderRadius: "var(--radius-card-sm)",
            boxShadow: "var(--shadow-card)",
            border: msg.role === "user" ? "none" : "1px solid var(--color-border)",
            fontSize: 14,
            lineHeight: 1.5,
          }}
        >
          {msg.content}
        </div>
      ))}
    </div>
  )
}
