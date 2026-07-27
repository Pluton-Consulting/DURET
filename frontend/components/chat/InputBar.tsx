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
    <div className="sym-in" style={{ padding: "16px 32px", background: "var(--color-surface)", borderTop: "1px solid var(--color-border)" }}>
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
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-pill)",
            padding: "10px 16px",
            fontSize: 14,
            fontFamily: "var(--font)",
            color: "var(--color-text-body)",
            outline: "none",
            transition: "border-color .2s ease, box-shadow .2s ease",
          }}
        />
        <button
          className="sym-tap"
          onClick={handleSend}
          disabled={disabled || !value.trim()}
          style={{
            background: "linear-gradient(180deg, var(--color-primary-hover), var(--color-primary))",
            color: "var(--color-text-on-dark)",
            border: "none",
            borderRadius: "var(--radius-pill)",
            padding: "10px 20px",
            fontSize: 14,
            fontWeight: 500,
            cursor: disabled || !value.trim() ? "not-allowed" : "pointer",
            opacity: disabled || !value.trim() ? 0.6 : 1,
            whiteSpace: "nowrap",
            boxShadow: "var(--shadow-card)",
          }}
        >
          Envoyer
        </button>
      </div>
    </div>
  )
}
