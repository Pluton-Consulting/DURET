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
        <div style={{ textAlign: "center", color: "#aaa", marginTop: 80 }}>
          <p style={{ fontSize: 32, margin: "0 0 8px" }}>🌿</p>
          <p style={{ margin: 0 }}>Bonjour, je suis Duret & Sols. Comment puis-je vous aider ?</p>
        </div>
      )}
      {messages.map((msg) => (
        <div
          key={msg.id}
          style={{
            alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
            maxWidth: "70%",
            background: msg.role === "user" ? "#304D32" : "white",
            color: msg.role === "user" ? "white" : "#1a1a1a",
            padding: "12px 16px",
            borderRadius: 12,
            boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
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
