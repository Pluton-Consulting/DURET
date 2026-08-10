"use client"
import type { ReactNode } from "react"
import { RichText } from "./RichText"
import {
  QuoteCard, InvoiceCard, EmailCard, DocCard, FileCard, ContactCard, ProjectCard,
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

// Champs requis par type : si l'un manque, le composant n'est PAS rendu (on garde le texte).
const REQUIRED: Record<string, string[]> = {
  quote: ["client", "total", "lines"],
  invoice: ["number", "client", "amount"],
  email: ["subject", "from"],
  doc: ["name"],
  fichier: ["url"],
  contact: ["name"],
  project: ["name", "client"],
  table: ["columns", "rows"],
  status_table: ["columns", "rows"],
  keyvalue: ["rows"],
  bars: ["data"],
  hbars: ["data"],
  progress: ["items"],
  donut: ["segments"],
  line: ["values"],
  gauge: ["value"],
  stat: ["label", "value"],
  list: ["items"],
  badge: ["text"],
  callout: ["text"],
  quick_replies: ["options"],
}

// Un champ est « fourni » s'il n'est ni vide, ni une chaîne blanche, ni un tableau vide.
function present(v: any): boolean {
  if (v === undefined || v === null) return false
  if (typeof v === "string") return v.trim().length > 0
  if (Array.isArray(v)) return v.length > 0
  return true
}

function renderBlock(block: any, onAction?: (v: string) => void,
                     acces?: { apiUrl?: string; backendToken?: string }): ReactNode {
  if (!block || typeof block !== "object") return null
  const { type, ...p } = block
  const req = REQUIRED[type]
  if (req && !req.every((k) => present(p[k]))) return null   // champ requis manquant → pas de composant
  switch (type) {
    case "quote":         return <QuoteCard {...p} />
    case "invoice":       return <InvoiceCard {...p} />
    case "email":         return <EmailCard {...p} />
    case "doc":           return <DocCard {...p} />
    // Le telechargement est controle cote serveur : le composant a besoin
    // du jeton, un lien nu partirait sans en-tete et serait refuse.
    case "fichier":       return <FileCard {...p} {...acces} />
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

export function MessageRenderer({ content, onAction, apiUrl, backendToken }:
  { content: string; onAction?: (v: string) => void; apiUrl?: string; backendToken?: string }) {
  const parts = parse(content)
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "flex-start", maxWidth: "90%" }}>
      {parts.map((part, i) => {
        if (part.kind === "text") {
          const t = part.text.trim()
          if (!t) return null
          return (
            <div key={i} className="sym-in" style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", color: "var(--color-text-primary)", padding: "12px 16px", borderRadius: "var(--radius-card-sm)", boxShadow: "var(--shadow-card)", fontSize: 14, lineHeight: 1.55, maxWidth: 620 }}>
              <RichText texte={t} />
            </div>
          )
        }
        const node = renderBlock(part.block, onAction, { apiUrl, backendToken })
        return node ? <div key={i} className="sym-in">{node}</div> : null
      })}
    </div>
  )
}
