"use client"
import type { ReactNode } from "react"
import {
  QuoteCard, InvoiceCard, EmailCard, DocCard, ContactCard, ProjectCard,
  SimpleTable, StatusTable, KeyValueTable,
  BarChart, HBarChart, ProgressBars, DonutChart, LineChart, Gauge,
  Callout, StatTile, Badge, QuickReplies, BulletList,
} from "@/components/blocks"

// Une réponse de l'IA = du texte, avec éventuellement des composants intercalés
// sous forme de blocs ```ui {json}```. On parse, on rend le composant du registre.
// L'IA n'émet JAMAIS de HTML/CSS : uniquement de la donnée (JSON) → sûr + thémé par tokens.

type Part = { kind: "text"; text: string } | { kind: "ui"; block: any }

function parse(content: string): Part[] {
  const parts: Part[] = []
  const re = /```ui\s*([\s\S]*?)```/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    if (m.index > last) parts.push({ kind: "text", text: content.slice(last, m.index) })
    try { parts.push({ kind: "ui", block: JSON.parse(m[1].trim()) }) } catch { /* JSON invalide → bloc ignoré */ }
    last = re.lastIndex
  }
  if (last < content.length) parts.push({ kind: "text", text: content.slice(last) })
  return parts
}

function renderBlock(block: any, onAction?: (v: string) => void): ReactNode {
  if (!block || typeof block !== "object") return null
  const { type, ...p } = block
  switch (type) {
    case "quote":         return <QuoteCard {...p} />
    case "invoice":       return <InvoiceCard {...p} />
    case "email":         return <EmailCard {...p} />
    case "doc":           return <DocCard {...p} />
    case "contact":       return <ContactCard {...p} />
    case "project":       return <ProjectCard {...p} />
    case "table":         return <SimpleTable {...p} />
    case "status_table":  return <StatusTable {...p} />
    case "keyvalue":      return <KeyValueTable {...p} />
    case "bars":          return <BarChart {...p} />
    case "hbars":         return <HBarChart {...p} />
    case "progress":      return <ProgressBars {...p} />
    case "donut":         return <DonutChart {...p} />
    case "line":          return <LineChart {...p} />
    case "gauge":         return <Gauge {...p} />
    case "stat":          return <StatTile {...p} />
    case "list":          return <BulletList {...p} />
    case "badge":         return <Badge tone={p.tone}>{p.text}</Badge>
    case "callout":       return <Callout tone={p.tone} title={p.title}>{p.text}</Callout>
    case "quick_replies": return <QuickReplies options={p.options} onPick={onAction} />
    default:              return null
  }
}

export function MessageRenderer({ content, onAction }: { content: string; onAction?: (v: string) => void }) {
  const parts = parse(content)
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-start", maxWidth: "90%" }}>
      {parts.map((part, i) => {
        if (part.kind === "text") {
          const t = part.text.trim()
          if (!t) return null
          return (
            <div key={i} className="sym-in" style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", color: "var(--color-text-primary)", padding: "12px 16px", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", fontSize: 14, lineHeight: 1.55, whiteSpace: "pre-wrap", maxWidth: 560 }}>{t}</div>
          )
        }
        const node = renderBlock(part.block, onAction)
        return node ? <div key={i} className="sym-in">{node}</div> : null
      })}
    </div>
  )
}
