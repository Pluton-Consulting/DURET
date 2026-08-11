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
  routeur: "Orientation de la demande",
  recherche: "Consultation de la mémoire d'entreprise",
  browser: "Recherche sur le web",
  llm: "Rédaction de la réponse",
  tools: "Exécution d'une action",
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

// Une action a effet externe suspendue, en attente d'une decision humaine.
interface EnAttente {
  id: string
  motif?: string | null
  skill?: string | null
  args?: Record<string, any> | null
}

// Ce que l'action va faire, dit en francais. Le nom technique (`nas_deposer`)
// n'apprend rien a qui doit decider s'il l'autorise.
const ACTIONS_EXTERNES: Record<string, string> = {
  nas_deposer: "Déposer un fichier sur le serveur de l'entreprise",
  generer_visuel: "Générer un visuel — cette génération est facturée",
  rediger_email: "Envoyer un message",
  redaction_email: "Envoyer un message",
}

// Les reperes qui permettent de decider : ou, quoi, pour qui. Jamais le
// contenu lui-meme — une bulle de chat n'est pas le bon endroit pour relire un
// corps de mail, et la file de validation le montre deja.
const REPERES = ["dossier", "chemin", "nom", "destinataire", "titre", "format"]

function decrireAction(v: EnAttente): { titre: string; details: string } {
  const titre =
    (v.skill && ACTIONS_EXTERNES[v.skill]) || v.motif || "Action à effet externe"
  const a = v.args || {}
  const details = REPERES
    .filter((k) => a[k] !== undefined && a[k] !== null && a[k] !== "")
    .map((k) => `${k} : ${String(a[k])}`)
    .join("  ·  ")
  return { titre, details }
}

export default function ChatWindow({ threadId: initialThreadId = null, token: tokenProp }: ChatWindowProps) {
  const { data: session } = useSession()
  const token = tokenProp || (session as any)?.backendToken
  const [messages, setMessages] = useState<Message[]>([])
  const [threadId, setThreadId] = useState<string | null>(initialThreadId)
  const [loading, setLoading] = useState(false)
  const [thinkingNode, setThinkingNode] = useState<string | null>(null)
  const [thinkingSteps, setThinkingSteps] = useState<string[]>([])
  // Ce que l'assistant FAIT, en clair, au-dessus du champ de saisie. Une
  // SEULE ligne qui se remplace : un journal qui s'allonge oblige a lire
  // pour retrouver l'etat courant, alors qu'on veut le voir d'un coup d'oeil.
  const [activite, setActivite] = useState<string>("")
  // CE QUI est en attente, pas seulement QU'IL Y A une attente. L'ecran
  // affichait « en attente de validation humaine » et rien d'autre : ni ce
  // qu'on validait, ni ou le faire — les boutons vivaient sur une autre page,
  // que personne ne peut deviner. La decision se prend ici, dans la
  // conversation ou elle a ete demandee.
  const [pendingValidation, setPendingValidation] = useState<EnAttente | null>(null)
  const [validationBusy, setValidationBusy] = useState(false)
  const [validationErreur, setValidationErreur] = useState<string | null>(null)
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

  // Décision humaine prise DANS la conversation. Le tour est suspendu au
  // `human_gate` : la réponse de cet appel est la SUITE du tour, une fois
  // l'action exécutée (ou refusée) — on la pousse donc comme un message de
  // l'assistant, sans quoi la conversation resterait figée sur l'attente.
  const resoudreValidation = async (accorde: boolean) => {
    const attente = pendingValidation
    if (!attente || !attente.id || validationBusy) return
    setValidationBusy(true)
    setValidationErreur(null)
    try {
      const res = await apiRequest<{ status?: string; response?: string; validation_id?: string | null }>(
        `/api/validations/${attente.id}/resolve`,
        { method: "POST", token, body: JSON.stringify({ approved: accorde }) }
      )
      setPendingValidation(null)
      // La reprise peut buter sur une NOUVELLE action à effet externe : une
      // demande en plusieurs étapes en compte parfois deux. Sans ce cas, la
      // seconde attente ne s'afficherait jamais et le tour semblerait perdu.
      if (res.status === "pending_validation" && res.validation_id) {
        setPendingValidation({ id: String(res.validation_id) })
      }
      if (res.response) {
        setMessages((prev) => [...prev, { id: newId(), role: "assistant", content: res.response as string }])
      } else if (!accorde) {
        setMessages((prev) => [...prev, { id: newId(), role: "assistant", content: "Action refusée — rien n'a été fait." }])
      }
    } catch (e: any) {
      // 403 : la personne n'a pas le droit de valider. Le dire, plutôt que de
      // laisser un bouton qui échoue sans expliquer pourquoi.
      setValidationErreur(
        e?.status === 403
          ? "Vous n'avez pas le droit d'approuver cette action. Une personne de la direction doit le faire, depuis la file de validation."
          : e?.message || "La décision n'a pas pu être enregistrée."
      )
    } finally {
      setValidationBusy(false)
    }
  }

  // Restaure la conversation au montage : thread passé en prop, sinon dernier thread
  // mémorisé en localStorage → recharge son historique depuis le backend.
  // Relit le fil mémorisé. Replie sur la clé NON préfixée : au tout premier
  // message, la session peut ne pas être encore chargée (userKey null), le fil
  // est alors enregistré sans préfixe. Sans ce repli, on le relirait sous la clé
  // préfixée une fois la session prête et la conversation semblerait perdue à
  // chaque changement d'onglet.
  const lireThreadMemorise = (): string | null => {
    if (typeof window === "undefined") return null
    const prefixe = window.localStorage.getItem(storageKey(userKey))
    if (prefixe) return prefixe
    const ancien = window.localStorage.getItem(STORAGE_PREFIX)
    if (ancien && userKey) {
      // Migration : on le range sous la bonne clé pour ne plus dépendre du repli.
      try {
        window.localStorage.setItem(storageKey(userKey), ancien)
        window.localStorage.removeItem(STORAGE_PREFIX)
      } catch { /* no-op */ }
    }
    return ancien
  }

  useEffect(() => {
    if (!token) return
    const tid = initialThreadId || lireThreadMemorise()
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
    setActivite("")
    setPendingValidation(null)
    setValidationErreur(null)

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

    const finish = (assistantContent: string | null, enAttente: EnAttente | null) => {
      if (settled) return
      settled = true
      clearStall()
      setThinkingNode(null)
      if (enAttente) setPendingValidation(enAttente)
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
        apiRequest<{
          response: string; thread_id: string; status?: string
          validation_id?: string | null
          validation?: { reason?: string | null; payload?: Record<string, any> | null } | null
        }>(
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
        if (needsValidation && res.validation_id) {
          const charge = res.validation?.payload || {}
          setPendingValidation({
            id: String(res.validation_id),
            motif: res.validation?.reason ?? null,
            skill: charge.skill ?? null,
            args: charge.args ?? null,
          })
        } else pushAssistant(res.response ?? "")
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
            finish(event.response ?? "", null)
          } else if (t === "pending_validation") {
            finish(null, {
              id: String(event.validation_id ?? ""),
              motif: event.reason ?? null,
              skill: event.skill ?? null,
              args: event.args ?? null,
            })
          } else if (t === "validation_required") {
            // Emis PENDANT le parcours, avant que la ligne de validation existe :
            // il n'a pas encore d'identifiant, donc rien a decider. On laisse
            // `pending_validation`, qui suit, ouvrir la decision.
            const d = event.data || {}
            const charge = d.payload || {}
            if (d.validation_id) {
              finish(null, {
                id: String(d.validation_id),
                motif: d.reason ?? null,
                skill: charge.skill ?? null,
                args: charge.args ?? null,
              })
            }
          } else if (t === "error") {
            fallbackPost()
          } else if (t === "node" || event.node !== undefined) {
            const n = String(event.node ?? (event.data && event.data.node) ?? "")
            if (n) {
              setThinkingNode(n)
              setThinkingSteps((prev) => (prev[prev.length - 1] === n ? prev : [...prev, n]))
            }
            // Un noeud sans libelle laisse la ligne PRECEDENTE en place :
            // l'effacer ferait clignoter le bandeau a chaque etape muette.
            const libelle = typeof event.libelle === "string" ? event.libelle.trim() : ""
            if (libelle) setActivite(libelle)
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
        <MessageList messages={messages} onAction={sendMessage}
                     apiUrl={process.env.NEXT_PUBLIC_API_URL || ""} backendToken={token} />

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
            <div className="sym-step" key={activite || thinkingNode || "start"}>
              {/* Le libelle concret prime : « je liste un dossier du serveur »
                  situe le travail, « Execution d'une action » ne dit rien. On
                  retombe sur le nom d'etape tant qu'aucun libelle n'est arrive. */}
              {activite || stepLabel(thinkingNode)}
              <span className="sym-dots" aria-hidden="true"><i /><i /><i /></span>
            </div>
          </div>
        )}

        {pendingValidation && (() => {
          const { titre, details } = decrireAction(pendingValidation)
          return (
            <div className="sym-pop sym-card" role="group" aria-label="Action en attente de votre décision"
                 style={{ margin: "8px 32px", padding: 16, background: "var(--color-surface)", border: "1px solid var(--color-pending-text)", borderRadius: "var(--radius-card)", boxShadow: "var(--shadow-card)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{ background: "var(--color-pending-bg)", color: "var(--color-pending-text)", padding: "3px 10px", borderRadius: "var(--radius-pill)", fontSize: 12, fontWeight: 700 }}>
                  ⏳ Votre accord est nécessaire
                </span>
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: "var(--color-text-primary)", lineHeight: 1.45 }}>
                {titre}
              </div>
              {details && (
                <div style={{ fontFamily: "monospace", fontSize: 12, color: "var(--color-text-muted)", marginTop: 6, wordBreak: "break-word" }}>
                  {details}
                </div>
              )}
              {validationErreur && (
                <div style={{ marginTop: 10, fontSize: 13, color: "var(--color-pending-text)" }}>
                  {validationErreur}
                </div>
              )}
              <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
                <button onClick={() => resoudreValidation(true)} disabled={validationBusy} className="sym-tap"
                        style={{ flex: 1, padding: "10px 16px", borderRadius: "var(--radius-pill)", border: "none", cursor: "pointer", fontWeight: 700, fontSize: 14, background: "linear-gradient(180deg, var(--color-primary), var(--color-primary-hover))", color: "var(--color-text-on-dark)", opacity: validationBusy ? 0.6 : 1 }}>
                  {validationBusy ? "…" : "Approuver"}
                </button>
                <button onClick={() => resoudreValidation(false)} disabled={validationBusy} className="sym-tap"
                        style={{ flex: 1, padding: "10px 16px", borderRadius: "var(--radius-pill)", border: "1px solid var(--color-pending-text)", cursor: "pointer", fontWeight: 700, fontSize: 14, background: "var(--color-surface)", color: "var(--color-pending-text)", opacity: validationBusy ? 0.6 : 1 }}>
                  Refuser
                </button>
              </div>
            </div>
          )
        })()}

        <InputBar onSend={sendMessage} disabled={loading} />
      </div>

      <ReasoningPath steps={thinkingSteps} loading={loading} />
    </div>
  )
}
