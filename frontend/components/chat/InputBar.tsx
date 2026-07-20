"use client"
import { useState, KeyboardEvent } from "react"

interface InputBarProps {
  onSend: (text: string) => void
  disabled?: boolean
}

export default function InputBar({ onSend, disabled }: InputBarProps) {
  const [value, setValue] = useState("")

  const handleSend = () => {
    if (!value.trim() || disabled) return
    onSend(value.trim())
    setValue("")
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div style={{ padding: "16px 32px", background: "white", borderTop: "1px solid #eee" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Posez votre question à Duret & Sols... (Entrée pour envoyer, Maj+Entrée pour saut de ligne)"
          disabled={disabled}
          rows={1}
          style={{
            flex: 1,
            resize: "none",
            border: "1px solid #ddd",
            borderRadius: 8,
            padding: "10px 14px",
            fontSize: 14,
            fontFamily: "inherit",
            outline: "none",
          }}
        />
        <button
          onClick={handleSend}
          disabled={disabled || !value.trim()}
          style={{
            background: "#304D32",
            color: "white",
            border: "none",
            borderRadius: 8,
            padding: "10px 20px",
            fontSize: 14,
            fontWeight: 500,
            cursor: disabled || !value.trim() ? "not-allowed" : "pointer",
            opacity: disabled || !value.trim() ? 0.6 : 1,
            whiteSpace: "nowrap",
          }}
        >
          Envoyer
        </button>
      </div>
    </div>
  )
}
