// Helper WebSocket pour le chat temps réel (streaming nœud-par-nœud de Symbiose/PLUTON).
// Le backend expose /api/chat/ws/{thread_id}?ticket=<ticket éphémère> et pousse des événements JSON.
// Le ticket (usage unique, ~30 s) s'obtient par POST /api/chat/ws-ticket (JWT en en-tête).

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// Événement générique poussé par le backend sur le WebSocket.
// Le contrat côté agents utilise notamment :
//   { type: "node", node: "classify" }            -> progression du graph
//   { type: "final", response: "..." }            -> réponse finale de l'assistant
//   { type: "validation_required" | "pending_validation" } -> human-in-the-loop
//   { type: "error", detail: "..." }              -> erreur serveur
export interface ChatEvent {
  type?: string
  node?: string
  data?: any
  response?: string
  detail?: string
  [key: string]: any
}

export interface ChatSocketHandlers {
  onEvent: (event: ChatEvent) => void
  onOpen?: () => void
  onError?: (err: Event) => void
  onClose?: (ev: CloseEvent) => void
}

/**
 * Ouvre une connexion WebSocket vers le chat streaming.
 * Convertit NEXT_PUBLIC_API_URL de http(s) vers ws(s), parse chaque message JSON
 * et appelle onEvent(event). Retourne l'instance WebSocket (à fermer par l'appelant).
 */
export async function openChatSocket(
  threadId: string,
  token: string,
  handlers: ChatSocketHandlers
): Promise<WebSocket> {
  // Échange le JWT (en-tête Authorization) contre un ticket éphémère à usage unique :
  // le JWT ne transite PLUS dans l'URL du WebSocket (sinon journalisée par uvicorn/nginx, rejouable).
  const ticketRes = await fetch(`${API_URL}/api/chat/ws-ticket`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!ticketRes.ok) throw new Error("ws-ticket refusé")
  const { ticket } = await ticketRes.json()

  const wsBase = API_URL.replace(/^http/, "ws")
  const url = `${wsBase}/api/chat/ws/${encodeURIComponent(threadId)}?ticket=${encodeURIComponent(ticket)}`
  const ws = new WebSocket(url)

  ws.onmessage = (msg: MessageEvent) => {
    let event: ChatEvent
    try {
      event = JSON.parse(msg.data as string)
    } catch {
      return // message non-JSON ignoré (dégradation propre)
    }
    handlers.onEvent(event)
  }

  ws.onopen = () => handlers.onOpen?.()
  ws.onerror = (err: Event) => handlers.onError?.(err)
  ws.onclose = (ev: CloseEvent) => handlers.onClose?.(ev)

  return ws
}

/**
 * Envoie une requête utilisateur sur le socket ouvert.
 * No-op silencieux si le socket n'est pas (encore) ouvert.
 */
export interface AttachmentPayload {
  attachment_name: string
  attachment_mime: string
  attachment_b64: string
}

export function sendQuery(
  ws: WebSocket,
  query: string,
  has_attachment = false,
  attachment?: AttachmentPayload,
): void {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ query, has_attachment: has_attachment || Boolean(attachment), ...(attachment || {}) }))
  }
}
