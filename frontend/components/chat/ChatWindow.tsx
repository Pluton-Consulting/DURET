"use client"
import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import MessageList from "./MessageList"
import InputBar, { PieceJointe } from "./InputBar"
import ReasoningPath from "./ReasoningPath"
import FileAttente, { TacheFond, AccordEnAttente } from "./FileAttente"
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

// Cadence de sondage de la file d'attente et des accords. Quatre secondes :
// assez vif pour que la progression d'une carte semble vivante, assez lent pour
// que dix onglets ouverts ne pèsent rien.
const POLL_MS = 4000

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

  // ── La file d'attente ────────────────────────────────────────────────
  // Trois populations dans la colonne de droite :
  //  - tachesLocales : la tache principale du chat quand son ecran a ete cede
  //    a une plus recente. Elle continue sur sa connexion WS ; seule sa CARTE
  //    vit ici. Locale a l'onglet — a la fermeture, son echange atterrit de
  //    toute facon dans l'historique de la conversation.
  //  - tachesFile : les taches differees cote backend (base + sondage). Elles
  //    survivent a tout : onglet ferme, redemarrage, jours qui passent.
  //  - accords : les validations en suspens. Persistantes en base, elles
  //    restent la tant qu'on n'a pas tranche — meme plusieurs jours apres.
  const [tachesLocales, setTachesLocales] = useState<TacheFond[]>([])
  const [tachesFile, setTachesFile] = useState<TacheFond[]>([])
  const [accords, setAccords] = useState<AccordEnAttente[]>([])
  const [accordEnCours, setAccordEnCours] = useState<string | null>(null)
  // L'erreur porte l'id de la carte : rattachee au seul « en cours », elle
  // n'etait jamais visible (les deux etats retombent dans le meme lot de rendu).
  const [erreurAccord, setErreurAccord] = useState<{ id: string; message: string } | null>(null)
  // Le role permet-il de trancher ? Les accords sont servis au demandeur, mais
  // seul un valideur peut les resoudre : sans ca, deux boutons qui echouent.
  const [peutDecider, setPeutDecider] = useState(false)
  // Miroir REACT de principalOccupeRef : une ref ne provoque aucun rendu, donc
  // la barre de saisie ne pouvait pas refleter « le fil est encore pris ».
  const [principalOccupe, setPrincipalOccupe] = useState(false)
  // La tache differee qui PILOTE le chat en ce moment (sa progression tient la
  // banniere). Les autres vivent en cartes.
  const [tacheActive, setTacheActive] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  // Cible des evenements de la tache WS en cours : null = le chat, sinon
  // l'identifiant de sa carte. C'est ce qui permet de « deplacer » une tache
  // vers la colonne sans toucher a sa connexion.
  const cibleWsRef = useRef<{ carte: string | null } | null>(null)
  // Le fil PRINCIPAL est-il occupe ? Distinct de `loading` : une tache WS
  // deplacee en carte occupe toujours le fil, meme quand le chat est libre.
  // Envoyer un nouveau message dessus corromprait l'historique (deux
  // executions sur le meme checkpointer) — dans ce cas, on met en file.
  const principalOccupeRef = useRef(false)
  // L'accord qui tient le fil principal suspendu, s'il y en a un. Le fil ne se
  // libere qu'a sa resolution : avant, tout nouveau tour ecraserait
  // l'interruption endormie dans le checkpointer.
  const filSuspenduRef = useRef<string | null>(null)
  const tacheActiveRef = useRef<string | null>(null)
  tacheActiveRef.current = tacheActive

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

  const pushAssistant = (content: string) =>
    setMessages((prev) => [...prev, { id: newId(), role: "assistant", content }])

  const majCarteLocale = (id: string, patch: Partial<TacheFond>) =>
    setTachesLocales((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))

  // ── Sondage : l'etat de la file et des accords, en une requete ───────
  // Non reentrant : un tick lent (le chargement du resultat d'une tache active
  // est un await DANS le handler) ne doit pas se faire doubler par le suivant,
  // qui retraiterait la meme fin de tache et afficherait la reponse deux fois.
  const pollEnCoursRef = useRef(false)
  const pollSeqRef = useRef(0)
  const monteRef = useRef(true)
  useEffect(() => () => { monteRef.current = false }, [])
  const rafraichirEtat = async () => {
    if (!token || pollEnCoursRef.current) return
    pollEnCoursRef.current = true
    const seq = ++pollSeqRef.current
    try {
      const res = await apiRequest<{
        taches: { id: string; query: string; status: string; progress: string
                  node: string; error: string | null; validation_id: string | null }[]
        validations: { id: string; reason: string | null; skill: string | null
                       args: Record<string, any> | null }[]
      }>("/api/file/etat", { token })

      // Une reponse arrivee dans le desordre ferait reapparaitre un accord
      // tout juste resolu, avec ses boutons — et un second clic possible.
      if (seq !== pollSeqRef.current || !monteRef.current) return
      setPeutDecider(Boolean((res as any).peut_decider))
      setTachesFile((res.taches || []).map((t) => ({
        id: t.id, source: "file" as const, question: t.query,
        etat: (t.status === "attente_validation" ? "attente_validation"
               : t.status === "terminee" ? "terminee"
               : t.status === "echec" ? "echec"
               : t.status === "interrompue" ? "interrompue" : "en_cours"),
        activite: t.progress || "", erreur: t.error || undefined,
        validationId: t.validation_id || undefined,
      })))
      setAccords((res.validations || []).map((v) => ({
        id: v.id, motif: v.reason, skill: v.skill, args: v.args,
      })))

      // La tache active pilote la banniere du chat : sa progression est LE
      // texte vivant, exactement comme pour une tache principale.
      const active = tacheActiveRef.current
        ? (res.taches || []).find((t) => t.id === tacheActiveRef.current)
        : null
      if (active) {
        if (active.status === "en_cours") {
          if (active.progress) setActivite(active.progress)
          if (active.node) {
            setThinkingNode(active.node)
            setThinkingSteps((prev) =>
              prev[prev.length - 1] === active.node ? prev : [...prev, active.node])
          }
        } else if (active.status === "terminee") {
          // Le resultat complet s'affiche dans le chat, comme si le tour s'y
          // etait deroule ; la carte est refermee (deja lue). La REF est videe
          // tout de suite : l'etat React ne se propage qu'au prochain rendu,
          // et un tick parti entre-temps rejouerait cette branche.
          tacheActiveRef.current = null
          setTacheActive(null)
          setLoading(false)
          setThinkingNode(null)
          try {
            const d = await apiRequest<{ response: string | null }>(
              `/api/file/taches/${active.id}`, { token })
            // Demonte entre-temps (changement d'onglet) : on n'affiche rien, donc
            // on ne marque RIEN comme vu. Sans ce garde, la reponse disparaissait
            // de la colonne sans jamais avoir ete lue — l'echange d'une tache
            // differee vit sur son propre fil, il n'est pas dans l'historique.
            if (!monteRef.current) return
            pushAssistant(d.response || "La tâche s'est terminée sans réponse.")
            await apiRequest(`/api/file/taches/${active.id}/vu`, { method: "POST", token })
          } catch {
            if (monteRef.current) pushAssistant("La tâche est terminée — sa carte reste dans la colonne de droite.")
          }
        } else if (active.status === "echec" || active.status === "interrompue") {
          setTacheActive(null)
          setLoading(false)
          setThinkingNode(null)
          pushAssistant(`La tâche n'a pas abouti${active.error ? ` : ${active.error}` : "."}`)
          if (monteRef.current) {
            try { await apiRequest(`/api/file/taches/${active.id}/vu`, { method: "POST", token }) } catch { /* no-op */ }
          }
        } else if (active.status === "attente_validation") {
          // Suspendue, pas finie : la decision se prend dans la colonne de
          // droite, aujourd'hui ou dans trois jours. Le chat redevient libre.
          setTacheActive(null)
          setLoading(false)
          setThinkingNode(null)
          pushAssistant("⏳ Une action attend votre accord — voir « En arrière-plan », à droite.")
        }
      }
    } catch { /* un sondage rate n'affiche rien : le suivant corrigera */ }
  }

  useEffect(() => {
    if (!token) return
    rafraichirEtat()
    const id = setInterval(rafraichirEtat, POLL_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  // ── Les accords : decider ici, aujourd'hui ou dans trois jours ───────
  // Le tour est suspendu au `human_gate`, son etat vit dans le checkpointer
  // Postgres : la reprise fonctionne apres n'importe quel delai. La reponse de
  // cet appel est la SUITE du tour — elle se pousse comme un message.
  const resoudreAccord = async (id: string, accorde: boolean) => {
    if (accordEnCours) return
    setAccordEnCours(id)
    setErreurAccord(null)
    try {
      const res = await apiRequest<{ status?: string; response?: string; validation_id?: string | null }>(
        `/api/validations/${id}/resolve`,
        { method: "POST", token, body: JSON.stringify({ approved: accorde }) }
      )
      // La tache de la file liee a cet accord vient d'etre refermee cote
      // backend : sa reponse s'affiche ICI, sa carte n'a plus rien a montrer.
      const liee = tachesFile.find((t) => t.validationId === id)
      if (res.response) pushAssistant(res.response)
      else if (!accorde) pushAssistant("Action refusée — rien n'a été fait.")
      if (liee) {
        try { await apiRequest(`/api/file/taches/${liee.id}/vu`, { method: "POST", token }) } catch { /* no-op */ }
      }
      // Une carte LOCALE suspendue sur ce meme accord n'a plus rien a attendre :
      // sans ca elle restait « en attente de votre accord » jusqu'au
      // rechargement de la page, alors que la decision venait d'etre prise.
      setTachesLocales((prev) => prev.filter((t) => t.validationId !== id))
      // Le fil principal etait suspendu sur CET accord : il redevient libre.
      if (filSuspenduRef.current === id) {
        filSuspenduRef.current = null
        principalOccupeRef.current = false
        setPrincipalOccupe(false)
      }
      await rafraichirEtat()
    } catch (e: any) {
      // 403 : la personne n'a pas le droit de valider. Le dire, plutot que de
      // laisser un bouton qui echoue sans expliquer pourquoi.
      setErreurAccord({
        id,
        message: e?.status === 403
          ? "Vous n'avez pas le droit d'approuver cette action. Une personne de la direction doit le faire."
          : e?.status === 409
            ? "Cette action vient d'être tranchée ailleurs."
            : e?.message || "La décision n'a pas pu être enregistrée.",
      })
    } finally {
      setAccordEnCours(null)
    }
  }

  // Clic sur une carte terminee : le rendu complet s'affiche dans le chat,
  // question comprise — comme si l'echange s'y etait deroule.
  const afficherTache = async (t: TacheFond) => {
    setMessages((prev) => [...prev, { id: newId(), role: "user", content: t.question }])
    if (t.source === "ws") {
      pushAssistant(t.reponse || "La tâche s'est terminée sans réponse.")
      setTachesLocales((prev) => prev.filter((x) => x.id !== t.id))
      return
    }
    try {
      const d = await apiRequest<{ response: string | null }>(`/api/file/taches/${t.id}`, { token })
      if (!monteRef.current) return
      pushAssistant(d.response || "La tâche s'est terminée sans réponse.")
      await apiRequest(`/api/file/taches/${t.id}/vu`, { method: "POST", token })
      await rafraichirEtat()
    } catch {
      pushAssistant("Le résultat n'a pas pu être relu — réessayez depuis la carte.")
    }
  }

  const fermerTache = async (t: TacheFond) => {
    if (t.source === "ws") {
      setTachesLocales((prev) => prev.filter((x) => x.id !== t.id))
      return
    }
    setTachesFile((prev) => prev.filter((x) => x.id !== t.id))
    try { await apiRequest(`/api/file/taches/${t.id}/vu`, { method: "POST", token }) } catch { /* no-op */ }
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

  // ── Ceder l'ecran du chat a une nouvelle demande ─────────────────────
  // La tache en cours glisse en carte dans la colonne de droite ; sa connexion
  // et son execution ne bougent pas. Seul l'AFFICHAGE change de place.
  const basculerActifVersCarte = () => {
    if (tacheActiveRef.current) {
      // Tache differee : elle apparait deja dans la liste sondee — la
      // « detacher » du chat suffit, sa carte prend le relais au prochain tick.
      setTacheActive(null)
      return
    }
    const cible = cibleWsRef.current
    if (cible && cible.carte === null) {
      const carteId = `ws-${newId()}`
      setTachesLocales((prev) => [{
        id: carteId, source: "ws" as const,
        question: queryEnCoursRef.current || "Tâche en cours",
        etat: "en_cours" as const,
        activite: activiteRef.current || "",
      }, ...prev])
      cible.carte = carteId
    }
  }
  const queryEnCoursRef = useRef<string>("")
  const activiteRef = useRef<string>("")
  activiteRef.current = activite

  // ── Mettre une demande en file (le fil principal est occupe) ─────────
  // `afficherDemande` : faux quand le message est DEJA dans le fil — cas du
  // basculement en file apres un refus « fil occupe », ou la demande a ete
  // affichee avant qu'on sache qu'elle ne pourrait pas partir par le chat.
  const lancerEnFile = async (text: string, afficherDemande = true) => {
    if (afficherDemande) {
      setMessages((prev) => [...prev, { id: newId(), role: "user", content: text }])
    }
    try {
      const res = await apiRequest<{ tache_id: string }>(
        "/api/file/taches",
        { method: "POST", token, body: JSON.stringify({ query: text }) })
      setTacheActive(res.tache_id)
      setLoading(true)
      setThinkingNode(null)
      setThinkingSteps([])
      setActivite("en file d'attente")
      await rafraichirEtat()
    } catch (e: any) {
      pushAssistant(`Erreur : ${e?.message ?? "la mise en file a échoué"}`)
    }
  }

  const sendMessage = (text: string, piece?: PieceJointe) => {
    if (!token) {
      setMessages((prev) => [...prev,
        { id: newId(), role: "user", content: text },
        { id: newId(), role: "assistant", content: "Erreur : session expirée, veuillez vous reconnecter." }])
      return
    }

    // Le fil principal est occupe (par le chat, ou par une tache deplacee en
    // carte qui tourne encore dessus) : la nouvelle demande part en FILE, sur
    // son propre fil backend. Deux executions sur un meme fil se disputeraient
    // le checkpointer — c'est un interdit structurel, pas une prudence.
    if (loading || principalOccupeRef.current) {
      basculerActifVersCarte()
      // Les pieces jointes ne voyagent pas encore en file : le dire tout de
      // suite vaut mieux qu'un fichier silencieusement ignore.
      if (piece) {
        setMessages((prev) => [...prev,
          { id: newId(), role: "user", content: `📎 ${piece.name}\n${text}` },
          { id: newId(), role: "assistant",
            content: "Les pièces jointes ne peuvent pas rejoindre la file d'attente : attendez la fin de la tâche en cours, puis renvoyez le fichier." }])
        return
      }
      lancerEnFile(text)
      return
    }

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
    queryEnCoursRef.current = text

    const tid = threadId ?? newId()
    if (!threadId) rememberThread(tid)

    let settled = false
    let stallTimer: ReturnType<typeof setTimeout> | null = null
    const clearStall = () => { if (stallTimer) { clearTimeout(stallTimer); stallTimer = null } }
    const closeWs = () => { try { wsRef.current?.close() } catch { /* no-op */ } }

    // Ou vont les evenements de CE tour : le chat, ou sa carte s'il a ete
    // deplace. L'objet est partage avec `basculerActifVersCarte` via la ref.
    const cible: { carte: string | null } = { carte: null }
    cibleWsRef.current = cible
    principalOccupeRef.current = true
    setPrincipalOccupe(true)

    const libérer = () => {
      principalOccupeRef.current = false
      setPrincipalOccupe(false)
      if (cibleWsRef.current === cible) cibleWsRef.current = null
    }

    const finish = (assistantContent: string | null) => {
      if (settled) return
      settled = true
      clearStall()
      libérer()
      if (cible.carte) {
        // Le tour s'est termine dans sa carte : le resultat y attend le clic.
        majCarteLocale(cible.carte, {
          etat: "terminee",
          reponse: assistantContent ?? "",
          activite: "terminée",
        })
        closeWs()
        return
      }
      setThinkingNode(null)
      if (assistantContent !== null) pushAssistant(assistantContent)
      setLoading(false)
      closeWs()
    }

    // Une action attend un accord : la carte va vivre dans la colonne de
    // droite (sondage), qu'on decide maintenant ou dans trois jours.
    //
    // LE FIL RESTE OCCUPE. Il est suspendu au `human_gate`, son interruption
    // dort dans le checkpointer : y lancer un nouveau tour l'ecraserait, et
    // l'approbation d'apres reprendrait un graphe qui n'est plus au point ou il
    // s'etait arrete. Les messages suivants partent donc en file — le backend
    // refuse de toute facon un tour sur un fil suspendu.
    const suspendre = (validationId?: string) => {
      if (settled) return
      settled = true
      clearStall()
      closeWs()
      if (cibleWsRef.current === cible) cibleWsRef.current = null
      if (cible.carte) {
        majCarteLocale(cible.carte, { etat: "attente_validation",
                                      activite: "en attente de votre accord",
                                      validationId })
      } else {
        setThinkingNode(null)
        setLoading(false)
        pushAssistant("⏳ Une action attend votre accord — voir « En arrière-plan », à droite.")
      }
      // Le fil principal reste PRIS : c'est ce qui envoie les messages suivants
      // en file au lieu de les lancer sur un fil suspendu. On note quel accord
      // le libere, sans quoi il resterait bloque pour toujours.
      if (validationId) filSuspenduRef.current = validationId
      rafraichirEtat()
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
        const attend =
          res.status === "pending_validation" || res.status === "validation_required" || Boolean(res.validation_id)
        if (cible.carte) {
          majCarteLocale(cible.carte, attend
            ? { etat: "attente_validation", activite: "en attente de votre accord",
                validationId: res.validation_id ? String(res.validation_id) : undefined }
            : { etat: "terminee", reponse: res.response ?? "", activite: "terminée" })
          if (attend) rafraichirEtat()
        } else if (attend) {
          pushAssistant("⏳ Une action attend votre accord — voir « En arrière-plan », à droite.")
          rafraichirEtat()
        } else {
          pushAssistant(res.response ?? "")
        }
      } catch (err: any) {
        if (err?.status === 409) {
          // Fil occupe : la demande part en file plutot que d'echouer.
          libérer()
          lancerEnFile(text, false)
          return
        }
        if (cible.carte) majCarteLocale(cible.carte, { etat: "echec", erreur: err?.message ?? "requête impossible" })
        else pushAssistant(`Erreur : ${err?.message ?? "requête impossible"}`)
      } finally {
        libérer()
        if (!cible.carte) {
          setThinkingNode(null)
          setLoading(false)
        }
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
            finish(event.response ?? "")
          } else if (t === "pending_validation") {
            suspendre(String(event.validation_id ?? "") || undefined)
          } else if (t === "validation_required") {
            // Emis PENDANT le parcours ; c'est `pending_validation`, qui suit
            // avec l'identifiant persiste, qui fait foi. Rien a faire ici.
          } else if (t === "fil_occupe") {
            // Refus delibere du backend (un tour tourne deja sur ce fil, ou il
            // attend une decision). Le repli POST retomberait sur le meme fil :
            // on met la demande en file, ce qu'elle aurait du faire.
            if (settled) return
            settled = true
            clearStall()
            closeWs()
            libérer()
            lancerEnFile(text, false)
          } else if (t === "error") {
            fallbackPost()
          } else if (t === "node" || event.node !== undefined) {
            const n = String(event.node ?? (event.data && event.data.node) ?? "")
            const libelle = typeof event.libelle === "string" ? event.libelle.trim() : ""
            if (cible.carte) {
              // La tache vit dans sa carte : c'est ELLE qui recoit le texte
              // vivant. La banniere du chat appartient a la tache suivante.
              if (libelle) majCarteLocale(cible.carte, { activite: libelle })
              return
            }
            if (n) {
              setThinkingNode(n)
              setThinkingSteps((prev) => (prev[prev.length - 1] === n ? prev : [...prev, n]))
            }
            // Un noeud sans libelle laisse la ligne PRECEDENTE en place :
            // l'effacer ferait clignoter le bandeau a chaque etape muette.
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

  // La colonne de droite montre toutes les taches SAUF celle qui pilote le
  // chat : elle, on la regarde deja dans la banniere.
  const cartesTaches = [
    ...tachesLocales,
    ...tachesFile.filter((t) => t.id !== tacheActive),
  ]

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

        <InputBar onSend={sendMessage} disabled={false} modeFile={loading || principalOccupe} />
      </div>

      <ReasoningPath
        steps={thinkingSteps}
        loading={loading}
        rail={
          <FileAttente
            taches={cartesTaches}
            accords={accords}
            accordEnCours={accordEnCours}
            erreurAccord={erreurAccord}
            peutDecider={peutDecider}
            onAfficher={afficherTache}
            onFermer={fermerTache}
            onResoudre={resoudreAccord}
          />
        }
      />
    </div>
  )
}
