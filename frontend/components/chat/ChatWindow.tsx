"use client"
import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import MessageList from "./MessageList"
import InputBar, { PieceJointe } from "./InputBar"
import ReasoningPath from "./ReasoningPath"
import { apiRequest } from "@/lib/api"
import { openChatSocket, sendQuery, ChatEvent } from "@/lib/ws"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
}

interface ChatWindowProps {
  threadId?: string | null
  token?: string        // passé côté serveur (fiable) ; sinon repli sur useSession
}

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

// Au-delà de ce délai sans le moindre événement WS, on bascule sur le POST.
// Élevé volontairement : évite de lancer un traitement POST en DOUBLE quand le WS
// est simplement lent (machine chargée) plutôt que réellement bloqué.
const WS_STALL_MS = 14000

// Mémorise le thread courant (localStorage) pour restaurer la conversation quand on
// quitte l'onglet puis qu'on y revient (le composant se démonte/remonte → état perdu).
// Clé préfixée par l'utilisateur : sur un poste partagé, sans ça, l'utilisateur B
// hérite du thread_id de A (rien ne purge le localStorage à la déconnexion) et se
// voit refuser chaque message depuis que l'appartenance du fil est contrôlée.
const STORAGE_PREFIX = "duret_thread_id"
const storageKey = (userKey?: string | null) =>
  userKey ? `${STORAGE_PREFIX}:${userKey}` : STORAGE_PREFIX

// Traduction des nœuds techniques en étapes lisibles (« ce que fait Duret & Sols »).
const NODE_LABELS: Record<string, string> = {
  classify: "Analyse de votre demande",
  check_schedule: "Vérification des accès",
  rag: "Recherche dans la mémoire d'entreprise",
  similar_projects: "Recherche de projets similaires",
  search_docs: "Recherche dans les documents",
  anonymize: "Protection des données personnelles",
  browser: "Recherche sur le web",
  llm: "Rédaction de la réponse",
  vision: "Analyse du plan / de la photo",
  preprocess: "Préparation du document",
  extraction: "Extraction des informations",
  rehydrate: "Finalisation de la réponse",
  validation_check: "Vérification",
  prechiffrage: "Préparation du chiffrage",
  generate_skill: "Création d'une compétence",
  test_skill: "Test de la compétence",
  submit_validation: "Envoi en validation",
  human_gate: "Validation humaine requise",
  agent1: "Assistant commercial au travail",
  agent2: "Assistant conception au travail",
  agent3: "Apprentissage d'une compétence",
}
function stepLabel(node: string | null | undefined): string {
  if (!node) return "Analyse de votre demande"
  return NODE_LABELS[node] || "Traitement en cours"
}

export default function ChatWindow({ threadId: initialThreadId = null, token: tokenProp }: ChatWindowProps) {
  const { data: session } = useSession()
  const token = tokenProp || (session as any)?.backendToken
  const [messages, setMessages] = useState<Message[]>([])
  const [threadId, setThreadId] = useState<string | null>(initialThreadId)
  const [loading, setLoading] = useState(false)
  const [thinkingNode, setThinkingNode] = useState<string | null>(null)
  const [thinkingSteps, setThinkingSteps] = useState<string[]>([])
  const [pendingValidation, setPendingValidation] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  // Enregistre le thread courant (state + localStorage) dès qu'il est connu.
  const userKey = (session as any)?.user?.email || null

  const rememberThread = (tid: string) => {
    setThreadId(tid)
    try { if (typeof window !== "undefined") window.localStorage.setItem(storageKey(userKey), tid) } catch { /* no-op */ }
  }

  // Fil périmé (403 : il appartient à quelqu'un d'autre) -> on repart proprement.
  const forgetThread = () => {
    setThreadId(null)
    try {
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(storageKey(userKey))
        window.localStorage.removeItem(STORAGE_PREFIX)   // ancienne clé non préfixée
      }
    } catch { /* no-op */ }
  }

  // Restaure la conversation au montage : thread passé en prop, sinon dernier thread
  // mémorisé en localStorage → recharge son historique depuis le backend.
  useEffect(() => {
    if (!token) return
    const tid = initialThreadId || (typeof window !== "undefined" ? window.localStorage.getItem(storageKey(userKey)) : null)
    if (!tid) return
    setThreadId(tid)
    apiRequest<any[]>(`/api/chat/threads/${tid}/messages`, { token })
      .then((rows) =>
        setMessages(
          (rows || []).map((m) => ({
            id: String(m.id),
            role: m.role === "assistant" ? "assistant" : "user",
            content: m.content ?? "",
          }))
        )
      )
      .catch(() => {})
  }, [initialThreadId, token, userKey])

  useEffect(() => () => { try { wsRef.current?.close() } catch { /* no-op */ } }, [])

  const sendMessage = (text: string, piece?: PieceJointe) => {
    const attachment = piece
      ? { attachment_name: piece.name, attachment_mime: piece.mime, attachment_b64: piece.b64 }
      : undefined
    setMessages((prev) => [
      ...prev,
      { id: newId(), role: "user", content: piece ? `📎 ${piece.name}\n${text}` : text },
    ])
    setLoading(true)
    setThinkingNode(null)
    setThinkingSteps([])
    setPendingValidation(false)

    const tid = threadId ?? newId()
    if (!threadId) rememberThread(tid)

    const pushAssistant = (content: string) =>
      setMessages((prev) => [...prev, { id: newId(), role: "assistant", content }])

    if (!token) {
      pushAssistant("Erreur : session expirée, veuillez vous reconnecter.")
      setLoading(false)
      return
    }

    let settled = false
    let stallTimer: ReturnType<typeof setTimeout> | null = null
    const clearStall = () => { if (stallTimer) { clearTimeout(stallTimer); stallTimer = null } }
    const closeWs = () => { try { wsRef.current?.close() } catch { /* no-op */ } }

    const finish = (assistantContent: string | null, isPending: boolean) => {
      if (settled) return
      settled = true
      clearStall()
      setThinkingNode(null)
      if (isPending) setPendingValidation(true)
      else if (assistantContent !== null) pushAssistant(assistantContent)
      setLoading(false)
      closeWs()
    }

    // Repli POST /api/chat/ — chemin fiable et vérifié.
    const fallbackPost = async () => {
      if (settled) return
      settled = true
      clearStall()
      closeWs()
      const post = (threadForCall: string) =>
        apiRequest<{ response: string; thread_id: string; status?: string; validation_id?: string | null }>(
          "/api/chat/",
          { method: "POST", token, body: JSON.stringify({ query: text, thread_id: threadForCall, ...(attachment || {}) }) }
        )
      try {
        let res
        try {
          res = await post(tid)
        } catch (e: any) {
          // 403 = ce fil ne nous appartient pas (thread_id hérité d'une autre session
          // sur le même poste). On l'oublie et on rejoue sur un fil neuf, sinon le
          // chat resterait définitivement bloqué.
          if (e?.status !== 403) throw e
          forgetThread()
          res = await post(newId())
        }
        if (res.thread_id) rememberThread(res.thread_id)
        const needsValidation =
          res.status === "pending_validation" || res.status === "validation_required" || Boolean(res.validation_id)
        if (needsValidation) setPendingValidation(true)
        else pushAssistant(res.response ?? "")
      } catch (err: any) {
        pushAssistant(`Erreur : ${err?.message ?? "requête impossible"}`)
      } finally {
        setThinkingNode(null)
        setLoading(false)
      }
    }

    // Tente le streaming WebSocket ; garde-fou anti-blocage → POST.
    try {
      openChatSocket(tid, token, {
        onOpen: () => sendQuery(wsRef.current!, text, false, attachment),
        onEvent: (event: ChatEvent) => {
          clearStall()  // le WS répond → on annule le repli anti-blocage
          const t = event.type
          if (t === "final" || (t === undefined && event.response !== undefined)) {
            finish(event.response ?? "", false)
          } else if (t === "validation_required" || t === "pending_validation") {
            finish(null, true)
          } else if (t === "error") {
            fallbackPost()
          } else if (t === "node" || event.node !== undefined) {
            const n = String(event.node ?? (event.data && event.data.node) ?? "")
            if (n) {
              setThinkingNode(n)
              setThinkingSteps((prev) => (prev[prev.length - 1] === n ? prev : [...prev, n]))
            }
          }
        },
        onError: () => fallbackPost(),
        onClose: () => { if (!settled) fallbackPost() },
      })
        .then((ws) => { wsRef.current = ws })
        .catch(() => fallbackPost())
      // Si aucun événement n'arrive (WS bloqué / injoignable), on bascule sur POST.
      stallTimer = setTimeout(() => { if (!settled) fallbackPost() }, WS_STALL_MS)
    } catch {
      fallbackPost()
    }
  }

  return (
    <div style={{ display: "flex", height: "calc(100vh - 64px)" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <MessageList messages={messages} onAction={sendMessage} />

        <style>{`
          @keyframes symOrb { 0%,100%{transform:scale(.8);opacity:.55} 50%{transform:scale(1.15);opacity:1} }
          @keyframes symDot { 0%,80%,100%{transform:translateY(0);opacity:.35} 40%{transform:translateY(-4px);opacity:1} }
          @keyframes symStepIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
          .sym-think{display:flex;gap:12px;align-items:center;padding:10px 32px}
          .sym-orb{width:12px;height:12px;border-radius:50%;flex-shrink:0;
            background:radial-gradient(circle at 35% 35%, var(--color-primary-mid), var(--color-primary));
            box-shadow:0 0 0 4px var(--color-primary-subtle);animation:symOrb 1.3s ease-in-out infinite}
          .sym-step{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:600;
            color:var(--color-text-primary);animation:symStepIn .35s ease}
          .sym-dots{display:inline-flex;gap:3px}
          .sym-dots i{width:4px;height:4px;border-radius:50%;background:var(--color-primary-mid);animation:symDot 1.2s infinite}
          .sym-dots i:nth-child(2){animation-delay:.18s}
          .sym-dots i:nth-child(3){animation-delay:.36s}
          @media (prefers-reduced-motion: reduce){ .sym-orb,.sym-dots i,.sym-step{animation:none} }
        `}</style>

        {loading && (
          <div className="sym-think" role="status" aria-live="polite">
            <span className="sym-orb" aria-hidden="true" />
            <div className="sym-step" key={thinkingNode || "start"}>
              {stepLabel(thinkingNode)}
              <span className="sym-dots" aria-hidden="true"><i /><i /><i /></span>
            </div>
          </div>
        )}

        {pendingValidation && (
          <div className="sym-pop" style={{ display: "inline-flex", alignItems: "center", gap: 8, margin: "8px 32px", padding: "10px 16px", background: "var(--color-pending-bg)", color: "var(--color-pending-text)", borderRadius: "var(--radius-pill)", border: "1px solid var(--color-pending-text)", boxShadow: "var(--shadow-card)", fontSize: 13, fontWeight: 600 }}>
            ⏳ En attente de validation humaine
          </div>
        )}

        <InputBar onSend={sendMessage} disabled={loading} />
      </div>

      <ReasoningPath steps={thinkingSteps} loading={loading} />
    </div>
  )
}
