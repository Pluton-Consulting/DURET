"use client"
import { useEffect, useRef, useState } from "react"
import { useSession } from "next-auth/react"
import MessageList from "./MessageList"
import InputBar, { PieceJointe } from "./InputBar"
import ReasoningPath from "./ReasoningPath"
import { ReflexionEnCours } from "./ReflexionEnCours"
import FileAttente, { TacheFond, AccordEnAttente } from "./FileAttente"
import { apiRequest } from "@/lib/api"
import { openChatSocket, sendQuery, sendStop, ChatEvent } from "@/lib/ws"
import { detacherTour, majTourDetache, reprendreTour, terminerTourDetache, abonnerTour } from "@/lib/tourDetache"

interface Message {
  id: string
  role: "user" | "assistant"
  content: string
  // Renseignes quand l'echange passe EN ARRIERE-PLAN : la bulle se dessine
  // alors en creux (contour pointille), et la reponse viendra remplacer le
  // placeholder A SA PLACE — pas tout en bas, apres les echanges qui l'ont
  // doublee. Une reponse detachee de sa question ne se lit pas.
  tacheId?: string
  placeholder?: boolean
  // Rang d'arrivee croissant : dit laquelle des reponses est la plus RECENTE,
  // ce qui n'est plus la derniere de la liste des qu'une tache de fond repond
  // dans sa bulle. Lu par MessageList (`estLaPlusRecente`).
  arrivee?: number
  // D'OU vient la reponse, et ce qu'elle a coute. Attache AU MESSAGE et non au
  // tour : la provenance doit rester lisible trois questions plus tard, sinon
  // elle ne sert qu'a l'instant ou personne ne la lit.
  provenance?: {
    documents: string[]
    web: string[]
    webFiltre?: boolean
    jetons?: { entree: number; sortie: number }
    modele?: string
  }
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
// Quand une tache differee tient la banniere, son texte doit se renouveler
// aussi souvent que celui d'une tache du chat — sinon l'ecran parait fige.
const POLL_ACTIF_MS = 1500

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
  agent1: "Pris en charge par l'assistant",
  rediger: "Rédaction de la réponse",
  agent2: "Délégué à notre expert conception : plans, photos, chiffrage",
  agent3: "Délégué à notre atelier : apprentissage d'une compétence",
}
function stepLabel(node: string | null | undefined): string {
  if (!node) return "Analyse de votre demande"
  return NODE_LABELS[node] || "Traitement en cours"
}

// LA FRISE SUIT CE QUE LES ACTIONS FONT RÉELLEMENT (01/09). Tout le travail
// des actions s'affichait sous « J'agis et je rédige » pendant que la ligne
// d'activité disait « je cherche dans la mémoire d'entreprise » : les deux
// affichages lisaient le même tour et racontaient deux histoires. Le serveur
// émet désormais le skill en cours avec chaque événement de nœud ; cette
// carte le traduit en étape de la frise — un geste de lecture (documents,
// données, mails, Drive/serveur) allume l'étape mémoire, un geste web l'étape
// web, le reste garde l'étape des actions.
const SKILLS_WEB = new Set(["chercher_web", "ouvrir_page", "naviguer"])
const PREFIXES_MEMOIRE = ["drive_", "nas_", "lire_", "liste_", "rechercher",
  "interroger", "fiche_", "check_mails", "boites_mail", "prix_observes",
  "dossiers_en_attente", "connaissances", "consignes"]
function etapeDuSkill(skill: string): string | null {
  if (!skill) return null
  if (SKILLS_WEB.has(skill)) return "browser"
  if (PREFIXES_MEMOIRE.some((p) => skill.startsWith(p))) return "recherche"
  return null
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
  // TOUTES les phrases franchies, dans l'ordre, et pas seulement la derniere.
  // `thinkingSteps` collecte les noms techniques des noeuds pour la frise de
  // droite ; ici on garde le RAISONNEMENT en francais, celui qu'on relit quand
  // on veut savoir par ou l'assistant est passe, ou bien ou il a coince.
  const [traceReflexion, setTraceReflexion] = useState<string[]>([])
  // La provenance du tour EN COURS. Une ref et non un etat : elle est lue au
  // moment ou la reponse arrive, pas affichee pendant qu'elle se remplit, donc
  // un rendu par document trouve ne servirait a rien.
  const provenanceRef = useRef<{
    documents: string[]; web: string[]; webFiltre: boolean
    entree: number; sortie: number; modele?: string
  }>({ documents: [], web: [], webFiltre: false, entree: 0, sortie: 0 })

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
  // Double de `accordEnCours`, lisible dans le meme tour que le clic : l'etat
  // React ne se met a jour qu'au rendu suivant, trop tard pour bloquer un
  // second clic.
  const accordEnCoursRef = useRef<string | null>(null)
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
  // Le fil courant, lisible au DÉMONTAGE (l'état React n'est plus fiable à ce
  // moment-là) : c'est lui qui permet de détacher un tour en vol.
  const threadIdRef = useRef<string | null>(initialThreadId)

  // Enregistre le thread courant (state + localStorage) dès qu'il est connu.
  const userKey = (session as any)?.user?.email || null

  const rememberThread = (tid: string) => {
    setThreadId(tid)
    threadIdRef.current = tid
    try { if (typeof window !== "undefined") window.localStorage.setItem(storageKey(userKey), tid) } catch { /* no-op */ }
  }

  // Fil périmé (403 : il appartient à quelqu'un d'autre) -> on repart proprement.
  const forgetThread = () => {
    setThreadId(null)
    threadIdRef.current = null
    try {
      if (typeof window !== "undefined") {
        window.localStorage.removeItem(storageKey(userKey))
        window.localStorage.removeItem(STORAGE_PREFIX)   // ancienne clé non préfixée
      }
    } catch { /* no-op */ }
  }

  /** Fige la provenance du tour et repart de zero pour le suivant. */
  const instantane = () => {
    const p = provenanceRef.current
    const gele = {
      documents: [...p.documents], web: [...p.web], webFiltre: p.webFiltre,
      jetons: (p.entree || p.sortie) ? { entree: p.entree, sortie: p.sortie } : undefined,
      modele: p.modele,
    }
    provenanceRef.current = { documents: [], web: [], webFiltre: false, entree: 0, sortie: 0 }
    return gele
  }

  const pushAssistant = (content: string, vivant = false) =>
    // `vivant` : la bulle N'EST PAS une fin de tour. Elle prend alors le
    // traitement d'attente — contour pointillé animé — au lieu de l'aspect
    // d'une réponse terminée.
    //
    // POURQUOI. « Une action attend votre accord » s'affichait exactement comme
    // une réponse finie : rien ne bougeait, et la personne a cru que
    // l'assistant s'était arrêté alors qu'il tenait le tour ouvert. Une bulle
    // qui respire dit « je suis toujours là-dessus » sans un mot de plus.
    setMessages((prev) => [...prev, {
      id: newId(), role: "assistant", content,
      // Une bulle d'attente n'est pas une arrivee : elle ne porte pas encore
      // de reponse, et ne doit donc pas voler le rang a celle qui en porte une.
      ...(vivant ? { placeholder: true } : { arrivee: prochaineArrivee() }),
      // Une bulle d'ATTENTE n'a pas de provenance : le tour n'est pas fini.
      ...(vivant ? {} : { provenance: instantane() }),
    }])

  const majCarteLocale = (id: string, patch: Partial<TacheFond>) =>
    setTachesLocales((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch } : t)))

  // TOUTES les taches dont une bulle d'attente vit dans le fil.
  //
  // POURQUOI CE REGISTRE (02/09). Le sondage ne regardait que `tacheActiveRef`,
  // une place UNIQUE que `basculerActifVersCarte` remet a null juste apres
  // avoir pose la bulle. Une tache ainsi detachee n'avait donc plus personne
  // pour poser sa reponse : elle finissait en carte, et sa bulle « reponse en
  // cours » battait indefiniment dans la conversation. Lancer trois demandes
  // d'affilee n'en ramenait qu'une — c'est le « il en masque une » releve par
  // Noa. Une bulle posee est une promesse d'affichage : ce qui la tient est
  // l'appartenance a ce registre, pas le fait d'etre la derniere demande.
  const tachesSuiviesRef = useRef<Set<string>>(new Set())

  // Rang d'arrivee des reponses, monotone croissant. Un compteur et non
  // l'horloge : deux reponses posees dans le meme milliseconde doivent quand
  // meme s'ordonner.
  const arriveeRef = useRef(0)
  const prochaineArrivee = () => ++arriveeRef.current

  // L'echange part en arriere-plan : sa question passe en creux, et une bulle
  // d'attente tient la place de la reponse a venir.
  const marquerEnAttente = (idMessage: string | null, tacheId: string) => {
    tachesSuiviesRef.current.add(tacheId)
    return setMessages((prev) => {
      const suite = prev.map((m) =>
        m.id === idMessage ? { ...m, tacheId } : m)
      return [...suite, { id: newId(), role: "assistant" as const,
                          content: "réponse en cours", tacheId, placeholder: true }]
    })
  }

  /** Remplit la bulle d'une tache SANS la refermer : elle attend encore. */
  const majBulle = (tacheId: string, contenu: string) =>
    setMessages((prev) => prev.map((m) =>
      (m.tacheId === tacheId && m.placeholder) ? { ...m, content: contenu } : m))

  // La reponse arrive : elle REMPLACE la bulle d'attente, et la question
  // reprend son aspect normal. Si le placeholder a disparu (fil recharge),
  // on ajoute a la suite plutot que de perdre la reponse.
  const poserReponse = (tacheId: string, contenu: string) => {
    // La promesse est tenue : la tache sort du registre des bulles a remplir.
    tachesSuiviesRef.current.delete(tacheId)
    const rang = prochaineArrivee()
    return setMessages((prev) => {
      let pose = false
      const suite = prev.map((m) => {
        if (m.tacheId !== tacheId) return m
        if (m.placeholder && !pose) {
          pose = true
          return { ...m, content: contenu, tacheId: undefined,
                   placeholder: false, arrivee: rang }
        }
        return { ...m, tacheId: undefined }
      })
      return pose ? suite
                  : [...suite, { id: newId(), role: "assistant" as const,
                                 content: contenu, arrivee: rang }]
    })
  }

  // ── Sondage : l'etat de la file et des accords, en une requete ───────
  // Non reentrant : un tick lent (le chargement du resultat d'une tache active
  // est un await DANS le handler) ne doit pas se faire doubler par le suivant,
  // qui retraiterait la meme fin de tache et afficherait la reponse deux fois.
  const pollEnCoursRef = useRef(false)
  const pollSeqRef = useRef(0)
  const monteRef = useRef(true)
  useEffect(() => () => { monteRef.current = false }, [])
  // Un rafraîchissement demandé pendant qu'un autre tourne était simplement
  // PERDU : le refus de réentrance rendait la main sans rien faire. On note la
  // demande et on la rejoue dès que la place est libre — l'appel qui suit une
  // décision doit aboutir, pas se faire avaler.
  const rappelDemandeRef = useRef(false)
  const rafraichirEtat = async () => {
    if (!token) return
    if (pollEnCoursRef.current) { rappelDemandeRef.current = true; return }
    pollEnCoursRef.current = true
    const seq = ++pollSeqRef.current
    try {
      const res = await apiRequest<{
        taches: { id: string; query: string; status: string; progress: string
                  node: string; error: string | null; validation_id: string | null
                  // Ce que l'assistant a produit AVANT de demander l'accord :
                  // pour une retouche, l'aperçu de la photo de départ.
                  response?: string | null }[]
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
      const toutes = res.taches || []
      const active = tacheActiveRef.current
        ? toutes.find((t) => t.id === tacheActiveRef.current)
        : null
      if (active && active.status === "en_cours") {
        if (active.progress) setActivite(active.progress)
        if (active.node) {
          setThinkingNode(active.node)
          setThinkingSteps((prev) =>
            prev[prev.length - 1] === active.node ? prev : [...prev, active.node])
        }
      }

      // LES FINS DE TACHE — pour TOUTES celles qui ont une bulle dans le fil,
      // et plus seulement pour l'active (02/09, cf. `tachesSuiviesRef`). La
      // banniere, elle, reste au singulier : il n'y en a qu'une a l'ecran.
      for (const t of toutes) {
        const suivie = tachesSuiviesRef.current.has(t.id)
        const etaitActive = t.id === tacheActiveRef.current
        if (!suivie && !etaitActive) continue
        if (t.status === "en_cours") continue
        if (etaitActive) {
          // La REF est videe tout de suite : l'etat React ne se propage qu'au
          // prochain rendu, et un tick parti entre-temps rejouerait la branche.
          tacheActiveRef.current = null
          setTacheActive(null)
          setLoading(false)
          setThinkingNode(null)
        }
        if (t.status === "terminee") {
          // Le resultat complet s'affiche dans le chat, comme si le tour s'y
          // etait deroule ; la carte est refermee (deja lue).
          tachesSuiviesRef.current.delete(t.id)
          try {
            const d = await apiRequest<{ response: string | null }>(
              `/api/file/taches/${t.id}`, { token })
            // Demonte entre-temps (changement d'onglet) : on n'affiche rien, donc
            // on ne marque RIEN comme vu. Sans ce garde, la reponse disparaissait
            // de la colonne sans jamais avoir ete lue — l'echange d'une tache
            // differee vit sur son propre fil, il n'est pas dans l'historique.
            if (!monteRef.current) return
            poserReponse(t.id, d.response || "La tâche s'est terminée sans réponse.")
            await apiRequest(`/api/file/taches/${t.id}/vu`, { method: "POST", token })
          } catch {
            if (monteRef.current) pushAssistant("La tâche est terminée. Sa carte reste dans la colonne de droite.")
          }
        } else if (t.status === "echec" || t.status === "interrompue") {
          tachesSuiviesRef.current.delete(t.id)
          poserReponse(t.id,
                       `La tâche n'a pas abouti${t.error ? ` : ${t.error}` : "."}`)
          if (monteRef.current) {
            try { await apiRequest(`/api/file/taches/${t.id}/vu`, { method: "POST", token }) } catch { /* no-op */ }
          }
        } else if (t.status === "attente_validation") {
          // Suspendue, pas finie : la decision se prend dans la colonne de
          // droite, aujourd'hui ou dans trois jours. Le chat redevient libre.
          // CE QU'ON APPROUVE DOIT SE VOIR.
          //
          // Le backend construit, AVANT de demander l'accord, un aperçu de ce
          // qui sera fait : pour une retouche, la photo de départ et la liste
          // des changements. Il arrive ici dans `response`. On ne l'affichait pas,
          // et la personne lisait « une action attend votre accord » sans rien
          // voir — puis approuvait un tirage facturé à l'aveugle. Relevé le
          // 27/08 sur « génère une simulation avant/après ».
          //
          // L'aperçu remplace la phrase générique quand il existe ; il porte
          // déjà l'invitation à trancher. La bulle reste « vivante » : le tour
          // n'est pas fini, il attend une décision.
          const apercu = (t.response || "").trim()
          const texte = apercu
            ? `${apercu}\n\n⏳ Votre accord est nécessaire : approuvez-la pour continuer.`
            : "⏳ Une action attend votre accord : approuvez-la pour continuer."
          // LA BULLE RESTE ATTACHEE A SA TACHE. Elle etait posee par
          // `pushAssistant`, donc SANS `tacheId` : apres l'accord, la reprise
          // ne la retrouvait pas et sa reponse atterrissait tout en bas, la
          // bulle d'origine battant pour toujours au-dessus. Une tache deja
          // suivie remplit la sienne ; l'active, qui n'en a pas, en ouvre une.
          if (!suivie) marquerEnAttente(idDerniereQuestionRef.current, t.id)
          majBulle(t.id, texte)
        }
      }
    } catch { /* un sondage rate n'affiche rien : le suivant corrigera */ }
    finally {
      // LE VERROU SE REND. Il était posé et jamais relâché : le tout premier
      // sondage le prenait, et tous les suivants repartaient aussitôt sans
      // rien faire. Plus aucun rafraîchissement, donc une bannière figée sur
      // son texte de départ et des cartes qui ne partaient jamais — y compris
      // après une décision. Un verrou sans `finally` ne protège pas, il ferme.
      pollEnCoursRef.current = false
      // Un rafraîchissement demandé pendant celui-ci était PERDU : on le
      // rejoue, pour que l'appel qui suit une décision aboutisse vraiment.
      if (rappelDemandeRef.current && monteRef.current) {
        rappelDemandeRef.current = false
        rafraichirEtat()
      }
    }
  }

  useEffect(() => {
    if (!token) return
    rafraichirEtat()
    // Deux cadences : vive quand une tache differee pilote la banniere (son
    // texte doit se renouveler comme celui d'une tache du chat), tranquille
    // sinon — dix onglets ouverts ne doivent rien couter.
    const id = setInterval(rafraichirEtat, tacheActive ? POLL_ACTIF_MS : POLL_MS)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, tacheActive])

  // ── Les accords : decider ici, aujourd'hui ou dans trois jours ───────
  // Le tour est suspendu au `human_gate`, son etat vit dans le checkpointer
  // Postgres : la reprise fonctionne apres n'importe quel delai. La reponse de
  // cet appel est la SUITE du tour — elle se pousse comme un message.
  const resoudreAccord = async (id: string, accorde: boolean) => {
    // GARDE SYNCHRONE. `accordEnCours` est un etat React : entre le clic et le
    // rendu suivant, il vaut encore null — deux clics rapproches passaient donc
    // tous les deux. Le premier tranchait, le second recevait un 409 « deja
    // resolue », et c'est CE message que l'utilisateur lisait sur une carte qui
    // ne partait plus. Une ref se lit et s'ecrit dans le meme tour.
    if (accordEnCoursRef.current) return
    accordEnCoursRef.current = id
    setAccordEnCours(id)
    setErreurAccord(null)
    // Le chat aussi montre qu'il travaille : la décision est prise dans le
    // panneau latéral, mais le résultat arrive dans le fil. Entre les deux,
    // l'indicateur d'activité du chat s'allume comme pendant un tour ordinaire.
    if (accorde) { principalOccupeRef.current = true; setPrincipalOccupe(true) }
    // LA REPRISE SE VOIT (31/08) : sitôt le clic, le journal parle, puis la
    // progression réelle est sondée pendant que le serveur déroule le plan.
    // La sonde s'arrête seule dès que l'accord n'est plus en cours.
    if (accorde) {
      setActivite("j'exécute ce que vous venez d'approuver")
      setThinkingNode("execute_action")
      const sondeId = setInterval(async () => {
        if (accordEnCoursRef.current !== id) {
          clearInterval(sondeId)
          setThinkingNode(null)
          setActivite("")
          return
        }
        try {
          const p = await apiRequest<{ node?: string | null; libelle?: string }>(
            `/api/validations/${id}/reprise`, { token })
          if (p?.node) {
            setThinkingNode(p.node)
            setThinkingSteps((prev) => (prev[prev.length - 1] === p.node ? prev : [...prev, p.node!]))
            if (p.libelle) setActivite(p.libelle)
          }
        } catch { /* la sonde est un confort, jamais une erreur d'écran */ }
      }, 1200)
    }
    try {
      const res = await apiRequest<{ status?: string; response?: string; validation_id?: string | null }>(
        `/api/validations/${id}/resolve`,
        { method: "POST", token, body: JSON.stringify({ approved: accorde }) }
      )
      // La tache liee a cet accord vient d'etre refermee cote backend : sa
      // reponse appartient a l'echange qui attend, elle remplit SA bulle.
      // Sans ce lien, elle atterrissait tout en bas, loin de sa question, et
      // la bulle d'attente battait indefiniment au-dessus.
      const liee = tachesFile.find((t) => t.validationId === id)
        || tachesLocales.find((t) => t.validationId === id)
      const texte = res.response
        || (accorde ? "Action approuvée." : "Action refusée : rien n'a été fait.")
      if (liee) poserReponse(liee.id, texte)
      else pushAssistant(texte)
      if (liee && liee.source === "file") {
        try { await apiRequest(`/api/file/taches/${liee.id}/vu`, { method: "POST", token }) } catch { /* no-op */ }
      }
      // Une carte LOCALE suspendue sur ce meme accord n'a plus rien a attendre :
      // sans ca elle restait « en attente de votre accord » jusqu'au
      // rechargement de la page, alors que la decision venait d'etre prise.
      setTachesLocales((prev) => prev.filter((t) => t.validationId !== id))
      // Le fil principal etait suspendu sur CET accord : il redevient libre.
      if (filSuspenduRef.current === id) filSuspenduRef.current = null
      principalOccupeRef.current = false
      setPrincipalOccupe(false)
      await rafraichirEtat()
    } catch (e: any) {
      if (e?.status === 409) {
        // 409 = la decision EXISTE deja (double clic, ou un collegue a tranche
        // avant). Ce n'est pas une erreur a montrer : la carte n'a plus lieu
        // d'etre, le rafraichissement ci-dessous la retire. L'afficher comme un
        // echec laissait au contraire une carte morte a l'ecran, portant un
        // message d'erreur pour une action pourtant bien tranchee.
        setTachesLocales((prev) => prev.filter((t) => t.validationId !== id))
        if (filSuspenduRef.current === id) {
          filSuspenduRef.current = null
          principalOccupeRef.current = false
          setPrincipalOccupe(false)
        }
      } else {
        // 403 : la personne n'a pas le droit de valider. Le dire, plutot que de
        // laisser un bouton qui echoue sans expliquer pourquoi.
        setErreurAccord({
          id,
          message: e?.status === 403
            ? "Vous n'avez pas le droit d'approuver cette action. Une personne de la direction doit le faire."
            : e?.message || "La décision n'a pas pu être enregistrée.",
        })
      }
    } finally {
      accordEnCoursRef.current = null
      setAccordEnCours(null)
      // TOUJOURS rafraichir, y compris apres un echec : le seul chemin qui le
      // faisait etait celui du succes, donc une carte deja tranchee cote
      // serveur restait affichee avec son message d'erreur.
      if (monteRef.current) await rafraichirEtat()
    }
  }

  // Clic sur une carte terminee : le rendu complet s'affiche dans le chat,
  // question comprise — comme si l'echange s'y etait deroule.
  const afficherTache = async (t: TacheFond) => {
    // La question est deja dans le fil si l'echange y a laisse sa bulle
    // d'attente : la reposer ferait doublon. On ne la remet que pour une
    // tache dont le fil a perdu la trace (page rechargee).
    const dejaLa = messages.some((m) => m.tacheId === t.id)
    if (!dejaLa) {
      setMessages((prev) => [...prev, { id: newId(), role: "user", content: t.question }])
    }
    if (t.source === "ws") {
      poserReponse(t.id, t.reponse || "La tâche s'est terminée sans réponse.")
      setTachesLocales((prev) => prev.filter((x) => x.id !== t.id))
      return
    }
    try {
      const d = await apiRequest<{ response: string | null }>(`/api/file/taches/${t.id}`, { token })
      if (!monteRef.current) return
      poserReponse(t.id, d.response || "La tâche s'est terminée sans réponse.")
      await apiRequest(`/api/file/taches/${t.id}/vu`, { method: "POST", token })
      await rafraichirEtat()
    } catch {
      pushAssistant("Le résultat n'a pas pu être relu. Réessayez depuis la carte.")
    }
  }

  const fermerTache = async (t: TacheFond) => {
    // Fermer la carte, c'est renoncer a voir le resultat : la bulle d'attente
    // le dit, au lieu de battre indefiniment pour une reponse qui ne viendra
    // plus a cet endroit.
    poserReponse(t.id, t.etat === "echec" || t.etat === "interrompue"
      ? `La tâche n'a pas abouti${t.erreur ? ` : ${t.erreur}` : "."}`
      : "Résultat mis de côté. La tâche reste consultable dans l'historique.")
    if (t.source === "ws") {
      setTachesLocales((prev) => prev.filter((x) => x.id !== t.id))
      return
    }
    setTachesFile((prev) => prev.filter((x) => x.id !== t.id))
    try { await apiRequest(`/api/file/taches/${t.id}/vu`, { method: "POST", token }) } catch { /* no-op */ }
  }

  /** Arrête une tâche de fond. Sa carte reste : c'est le sondage d'état qui la
   *  fera passer en « interrompue », comme pour tout autre aboutissement.
   *
   *  Une tâche affichée en carte mais pilotée par le WebSocket (`source: "ws"`)
   *  n'a pas de ligne en base : c'est le tour principal déplacé, on l'arrête
   *  par la socket.
   */
  const arreterTache = async (t: TacheFond) => {
    if (t.source === "ws") { stopper(); return }
    try {
      await apiRequest(`/api/file/taches/${t.id}/arreter`, { method: "POST", token })
    } catch {
      majCarteLocale(t.id, { activite: "l'arrêt n'a pas pu être demandé" })
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

  const chargerHistorique = (tid: string) =>
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

  // ── Re-brancher un tour détaché (retour de Paramètres ou d'ailleurs) ──
  // Le démontage de ce composant ne tue plus un tour en vol : sa connexion et
  // ses closures survivent dans le runtime, et le module `tourDetache` garde de
  // quoi remettre l'écran exactement dans l'état qu'il aurait eu sans partir.
  const adopterTourDetache = (tid: string) => {
    const t = reprendreTour(tid)
    if (!t) return
    if (t.fini) {
      // Terminé pendant l'absence : l'historique rechargé juste avant contient
      // déjà l'échange (le serveur écrit AVANT d'annoncer). Rien à rejouer.
      terminerTourDetache()
      return
    }
    if (t.suspendu !== undefined) {
      // Une action attend un accord. L'échange est déjà persisté (le tour
      // s'est posé au human_gate), la carte vit dans la colonne de droite :
      // on remet la bannière et le fil reste pris jusqu'à la décision.
      if (t.suspendu) filSuspenduRef.current = t.suspendu
      principalOccupeRef.current = true
      setPrincipalOccupe(true)
      terminerTourDetache()
      pushAssistant("⏳ Une action attend votre accord : approuvez-la pour continuer.", true)
      rafraichirEtat()
      return
    }
    // Le tour est encore en vol : question affichée, bannière d'activité, fil
    // occupé, et la socket rendue au bouton d'arrêt. `cibleWsRef` est re-armé
    // pour que ce composant-ci sache À SON TOUR qu'un tour vole — sans quoi une
    // seconde navigation fermerait la socket adoptée au lieu de re-détacher.
    const idQuestion = newId()
    idDerniereQuestionRef.current = idQuestion
    queryEnCoursRef.current = t.question
    wsRef.current = t.ws ?? null
    cibleWsRef.current = { carte: null }
    principalOccupeRef.current = true
    setPrincipalOccupe(true)
    setLoading(true)
    if (t.activite) setActivite(t.activite)
    setMessages((prev) => [...prev, { id: idQuestion, role: "user", content: t.question }])
    const desabonner = abonnerTour((tour) => {
      if (!monteRef.current) { desabonner(); return }
      if (tour.fini) {
        desabonner()
        terminerTourDetache()
        cibleWsRef.current = null
        principalOccupeRef.current = false
        setPrincipalOccupe(false)
        setLoading(false)
        setThinkingNode(null)
        // La réponse est déjà en base : on recharge le fil plutôt que de
        // reconstruire l'échange à la main — une seule source de vérité.
        chargerHistorique(tid).catch(() => {})
      } else if (tour.suspendu !== undefined) {
        desabonner()
        terminerTourDetache()
        cibleWsRef.current = null
        if (tour.suspendu) filSuspenduRef.current = tour.suspendu
        setLoading(false)
        setThinkingNode(null)
        pushAssistant("⏳ Une action attend votre accord : approuvez-la pour continuer.", true)
        rafraichirEtat()
      } else if (tour.activite) {
        setActivite(tour.activite)
        setTraceReflexion((prev) =>
          prev[prev.length - 1] === tour.activite ? prev : [...prev, tour.activite])
      }
    })
    // Le tour a pu s'achever entre la lecture et l'abonnement : on revérifie.
    if (t.fini) {
      desabonner()
      terminerTourDetache()
      cibleWsRef.current = null
      principalOccupeRef.current = false
      setPrincipalOccupe(false)
      setLoading(false)
      chargerHistorique(tid).catch(() => {})
    }
  }

  useEffect(() => {
    if (!token) return
    const tid = initialThreadId || lireThreadMemorise()
    if (!tid) return
    setThreadId(tid)
    threadIdRef.current = tid
    chargerHistorique(tid)
      .catch(() => {})
      .finally(() => { if (monteRef.current) adopterTourDetache(tid) })
  }, [initialThreadId, token, userKey])

  useEffect(() => () => {
    // LA NAVIGATION NE TUE PLUS LE TOUR. Fermer la socket ici faisait annuler
    // le tour par le serveur (il lit la fermeture comme un abandon) — et le
    // garde-fou anti-blocage relançait même la demande en double par POST, en
    // aveugle. Constaté : « aller dans Paramètres stoppe la demande en cours ».
    // Un tour en vol est désormais DÉTACHÉ : sa connexion et ses closures
    // survivent dans le runtime de la SPA, le module `tourDetache` garde de
    // quoi re-brancher l'écran au retour. Sans tour en vol, on ferme comme avant.
    const enVol = cibleWsRef.current && cibleWsRef.current.carte === null
    if (enVol && threadIdRef.current) {
      detacherTour({
        threadId: threadIdRef.current,
        question: queryEnCoursRef.current,
        activite: activiteRef.current,
        ws: wsRef.current,
      })
      return
    }
    try { wsRef.current?.close() } catch { /* no-op */ }
  }, [])

  // ── Ceder l'ecran du chat a une nouvelle demande ─────────────────────
  // La tache en cours glisse en carte dans la colonne de droite ; sa connexion
  // et son execution ne bougent pas. Seul l'AFFICHAGE change de place.
  const basculerActifVersCarte = () => {
    // LA PROVENANCE PART AVEC SON TOUR (02/09). Elle s'accumule dans une ref
    // unique, videe par le seul `instantane()` — c'est-a-dire au moment ou une
    // reponse se pose dans le chat. Un tour qui glisse en carte n'en pose pas :
    // les documents et les jetons qu'il avait deja rassembles restaient donc
    // dans la ref, et s'affichaient sous la reponse SUIVANTE, sans rapport.
    // Six sources sous un « bonjour ». Le tour s'en va, son compte aussi.
    instantane()
    if (tacheActiveRef.current) {
      // Tache differee : elle apparait deja dans la liste sondee — la
      // « detacher » du chat suffit, sa carte prend le relais au prochain tick.
      // Son echange passe en creux : sa reponse arrivera plus tard, a sa place.
      marquerEnAttente(idDerniereQuestionRef.current, tacheActiveRef.current)
      tacheActiveRef.current = null
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
      marquerEnAttente(idDerniereQuestionRef.current, carteId)
    }
  }
  const queryEnCoursRef = useRef<string>("")
  // L'identifiant du dernier message d'utilisateur envoye : c'est LUI qu'on
  // marque en creux quand son echange part en arriere-plan.
  const idDerniereQuestionRef = useRef<string | null>(null)
  const activiteRef = useRef<string>("")
  activiteRef.current = activite

  // ── Mettre une demande en file (le fil principal est occupe) ─────────
  // `afficherDemande` : faux quand le message est DEJA dans le fil — cas du
  // basculement en file apres un refus « fil occupe », ou la demande a ete
  // affichee avant qu'on sache qu'elle ne pourrait pas partir par le chat.
  const lancerEnFile = async (text: string, afficherDemande = true) => {
    if (afficherDemande) {
      const idQuestion = newId()
      idDerniereQuestionRef.current = idQuestion
      setMessages((prev) => [...prev, { id: idQuestion, role: "user", content: text }])
    }
    try {
      const res = await apiRequest<{ tache_id: string }>(
        "/api/file/taches",
        { method: "POST", token, body: JSON.stringify({ query: text }) })
      tacheActiveRef.current = res.tache_id
      setTacheActive(res.tache_id)
      setLoading(true)
      setThinkingNode(null)
      setThinkingSteps([]); setTraceReflexion([])
      setActivite("je prends la demande")
      // Sondage RAPPROCHE le temps qu'elle demarre : la cadence de croisiere
      // (4 s) laissait la banniere sur son texte d'attente plusieurs secondes,
      // alors que la tache avait deja commence a travailler.
      await rafraichirEtat()
      for (const delai of [400, 900, 1600]) {
        setTimeout(() => { if (monteRef.current) rafraichirEtat() }, delai)
      }
    } catch (e: any) {
      pushAssistant(`Erreur : ${e?.message ?? "la mise en file a échoué"}`)
    }
  }

  /** Arrête le tour en cours. Le serveur confirme par un événement `arrete`.
   *
   * On ne coupe RIEN à l'écran d'ici : c'est la confirmation du serveur qui
   * clôt le tour. Nettoyer localement d'abord donnerait un chat rendu à
   * l'utilisateur pendant qu'un graphe continue de tourner derrière — et
   * d'appeler des modèles payants.
   */
  const stopper = () => {
    if (sendStop(wsRef.current)) {
      setActivite("arrêt demandé…")
      return
    }
    // Pas de socket : le tour est parti par le repli POST, qu'on ne sait pas
    // interrompre côté serveur. On le dit plutôt que de laisser croire à un
    // arrêt qui n'aura pas lieu.
    pushAssistant("Ce traitement ne peut plus être interrompu (il ne passe pas "
                  + "par la connexion temps réel). Il se terminera de lui-même.")
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
    const idQuestion = newId()
    idDerniereQuestionRef.current = idQuestion
    setMessages((prev) => [
      ...prev,
      { id: idQuestion, role: "user", content: piece ? `📎 ${piece.name}\n${text}` : text },
    ])
    setLoading(true)
    setThinkingNode(null)
    setThinkingSteps([]); setTraceReflexion([])
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
      if (!monteRef.current) {
        // L'écran est parti (Paramètres…) pendant le tour. La réponse est déjà
        // dans l'historique (le serveur écrit avant d'annoncer) : on signale
        // seulement la fin au module de détachement, l'écran rechargera le fil
        // à son retour.
        majTourDetache({ fini: true })
        closeWs()
        return
      }
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
      if (!monteRef.current) {
        // L'écran est absent : l'attente d'accord est notée au module de
        // détachement, la bannière se remettra au retour. La carte, elle, vit
        // déjà côté serveur (sondage des validations).
        if (validationId) filSuspenduRef.current = validationId
        majTourDetache({ suspendu: validationId ?? null })
        return
      }
      if (cible.carte) {
        majCarteLocale(cible.carte, { etat: "attente_validation",
                                      activite: "en attente de votre accord",
                                      validationId })
      } else {
        setThinkingNode(null)
        setLoading(false)
        pushAssistant("⏳ Une action attend votre accord : approuvez-la pour continuer.", true)
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
        if (!monteRef.current) {
          // Le repli POST a abouti pendant l'absence : même contrat que le
          // WebSocket — la fin (ou l'attente d'accord) va au module de
          // détachement, la réponse est déjà dans l'historique.
          if (attend) majTourDetache({ suspendu: res.validation_id ? String(res.validation_id) : null })
          else majTourDetache({ fini: true })
        } else if (cible.carte) {
          majCarteLocale(cible.carte, attend
            ? { etat: "attente_validation", activite: "en attente de votre accord",
                validationId: res.validation_id ? String(res.validation_id) : undefined }
            : { etat: "terminee", reponse: res.response ?? "", activite: "terminée" })
          if (attend) rafraichirEtat()
        } else if (attend) {
          pushAssistant("⏳ Une action attend votre accord : approuvez-la pour continuer.", true)
          rafraichirEtat()
        } else {
          pushAssistant(res.response ?? "")
        }
      } catch (err: any) {
        if (err?.status === 409) {
          // Fil occupe : la demande part en file plutot que d'echouer.
          libérer()
          lancerEnFile(text, false)
          if (!monteRef.current) majTourDetache({ fini: true })
          return
        }
        if (err?.status === 401) {
          // La session a expiré (le JWT vit 24 h) alors que l'onglet est resté
          // ouvert : rien d'autre ne marchera d'ici la reconnexion. On le dit
          // en français et on y renvoie — « Erreur : Token invalide » (31/08)
          // laissait la personne devant un chat mort.
          if (!monteRef.current) majTourDetache({ fini: true })
          else pushAssistant("Erreur : session expirée, veuillez vous reconnecter.")
          setTimeout(() => window.location.assign("/login"), 2500)
          return
        }
        if (!monteRef.current) majTourDetache({ fini: true })
        else if (cible.carte) majCarteLocale(cible.carte, { etat: "echec", erreur: err?.message ?? "requête impossible" })
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
          } else if (t === "arrete") {
            // ARRÊT CONFIRMÉ PAR LE SERVEUR. `finish` pose `settled`, ce qui
            // est essentiel : sans lui, la fermeture de la socket qui suit
            // déclencherait le repli POST, et la demande qu'on vient
            // d'interrompre repartirait de zéro.
            finish(String(event.detail ?? "Traitement interrompu."))
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
            if (!monteRef.current) majTourDetache({ fini: true })
          } else if (t === "error") {
            fallbackPost()
          } else if (t === "node" || event.node !== undefined) {
            const n = String(event.node ?? (event.data && event.data.node) ?? "")
            const libelle = typeof event.libelle === "string" ? event.libelle.trim() : ""
            if (!monteRef.current) {
              // L'écran est absent : la progression va au module de
              // détachement, qui la resservira à l'écran remonté.
              if (libelle) majTourDetache({ activite: libelle })
              return
            }
            if (cible.carte) {
              // La tache vit dans sa carte : c'est ELLE qui recoit le texte
              // vivant. La banniere du chat appartient a la tache suivante.
              if (libelle) majCarteLocale(cible.carte, { activite: libelle })
              return
            }
            // « anonymize » sans libellé = l'anonymisation est COUPÉE : le
            // journal se tait (31/08), la frise ne coche donc pas non plus
            // « Je protège les noms » — cocher une protection qui n'a pas eu
            // lieu serait un mensonge d'écran.
            if (n && (n !== "anonymize" || libelle)) {
              setThinkingNode(n)
              setThinkingSteps((prev) => (prev[prev.length - 1] === n ? prev : [...prev, n]))
            }
            // L'étape RÉELLE du travail : le skill émis par le serveur allume
            // l'étape mémoire ou web de la frise, en DERNIER — c'est lui que
            // la frise montre comme étape active, en accord avec la ligne
            // d'activité qui décrit la même action.
            const pseudo = etapeDuSkill(
              typeof (event as any).skill === "string" ? (event as any).skill : "")
            if (pseudo) {
              setThinkingSteps((prev) =>
                prev[prev.length - 1] === pseudo ? prev : [...prev, pseudo])
            }
            // Un noeud sans libelle laisse la ligne PRECEDENTE en place :
            // l'effacer ferait clignoter le bandeau a chaque etape muette.
            // LA PROVENANCE S'ACCUMULE AU FIL DES NOEUDS. Chaque valeur est
            // deja dans `data` : le serveur les produisait et l'ecran les
            // jetait. Rien n'est demande au modele, rien n'est calcule ici.
            const d: any = (event as any).data || {}
            const p = provenanceRef.current
            for (const nom of (d.sources_memoire || [])) {
              if (!p.documents.includes(nom)) p.documents.push(nom)
            }
            for (const u of (d.browser_sources || [])) {
              if (!p.web.includes(u)) p.web.push(u)
            }
            if (d.browser_was_filtered) p.webFiltre = true
            if (typeof d.tokens_in === "number") p.entree += d.tokens_in
            if (typeof d.tokens_out === "number") p.sortie += d.tokens_out
            if (d.model_used) p.modele = d.model_used

            if (libelle) {
              setActivite(libelle)
              // On empile, en ecartant la repetition immediate : un meme noeud
              // traverse deux fois de suite n'apprend rien, et allongerait la
              // trace sans rien y ajouter.
              setTraceReflexion((prev) =>
                prev[prev.length - 1] === libelle ? prev : [...prev, libelle])
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

  // La colonne de droite montre toutes les taches SAUF celle qui pilote le
  // chat : elle, on la regarde deja dans la banniere.
  const cartesTaches = [
    ...tachesLocales,
    ...tachesFile.filter((t) => t.id !== tacheActive),
  ]

  return (
    <div style={{ display: "flex", height: "calc(100vh - 64px)" }}>
      {/* LE FIL A SON PROPRE FOND, plus profond que celui des cartes : c'est ce
          creux qui fait remonter la barre de saisie et les documents posés
          dessus. Sans lui, trois surfaces se superposaient à quatre pour cent
          d'écart et l'écran paraissait plat. */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0,
                    background: "var(--marque-chat-fond)" }}>
        <MessageList messages={messages} onAction={sendMessage}
                     apiUrl={process.env.NEXT_PUBLIC_API_URL || ""} backendToken={token} />

        <style>{`
          @keyframes symPoint { 0%,68%,100%{opacity:.22;transform:scale(.68)} 34%{opacity:1;transform:scale(1)} }
          @keyframes symStepIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
          .sym-think{display:flex;gap:12px;align-items:center;padding:10px 32px}
          /* GRILLE 3x3, la forme d'attente de la bibliotheque d'icones.
             Neuf points plutot qu'une icone figee : une icone ne peut pas
             animer ses points un par un, or c'est la vague en diagonale qui
             fait lire « ca travaille » plutot que « c'est decoratif ».
             La couleur vient de la charte : verte ici, bleue chez l'autre
             client, sans toucher a ce fichier. */
          .sym-grille{display:grid;grid-template-columns:repeat(3,3.5px);gap:2.5px;
            flex-shrink:0;align-content:center}
          .sym-grille i{width:3.5px;height:3.5px;border-radius:1px;
            background:var(--marque-primary-mid);
            animation:symPoint 1.45s ease-in-out infinite}
          /* Vague en diagonale : le retard croit avec la somme ligne + colonne. */
          .sym-grille i:nth-child(1){animation-delay:0s}
          .sym-grille i:nth-child(2),.sym-grille i:nth-child(4){animation-delay:.1s}
          .sym-grille i:nth-child(3),.sym-grille i:nth-child(5),
          .sym-grille i:nth-child(7){animation-delay:.2s}
          .sym-grille i:nth-child(6),.sym-grille i:nth-child(8){animation-delay:.3s}
          .sym-grille i:nth-child(9){animation-delay:.4s}
          .sym-step{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:600;
            color:var(--marque-text-primary);animation:symStepIn .35s ease}
          @media (prefers-reduced-motion: reduce){
            .sym-grille i,.sym-step{animation:none}
            .sym-grille i{opacity:.75;transform:none} }
        `}</style>

        {/* LE RAISONNEMENT, PAS SEULEMENT L'ETAPE EN COURS.
            L'etape du moment reste en tete, et les precedentes s'empilent en
            dessous : au bout de quarante secondes, on peut enfin dire par ou
            l'assistant est passe, et surtout ou il a coince. Le repli se
            referme seul une seconde apres la fin, pour ne pas encombrer le
            fil une fois la reponse arrivee. Aucun jeton depense : chaque
            phrase vient d'un evenement que le serveur emettait deja. */}
        <ReflexionEnCours
          activite={activite || stepLabel(thinkingNode)}
          trace={traceReflexion}
          enCours={loading}
        />

        {/* LES ACCORDS EN ATTENTE, AU TÉLÉPHONE (01/09).
            Sur PC, `FileAttente` vit dans la colonne de droite, montée par
            `ReasoningPath`. Or cette colonne est masquée sous 900 px — et elle
            emportait avec elle les boutons Approuver / Refuser. Conséquence
            mesurée : sur un téléphone, AUCUNE action à effet externe ne pouvait
            aboutir. Envoyer un mail, déposer sur le NAS, produire un document :
            le tour restait suspendu, sans rien à l'écran pour le débloquer, et
            le chat renvoyait même vers une colonne invisible.
            La même file est donc montée ici, juste au-dessus de la saisie —
            là où le regard est déjà — et n'apparaît QUE sous 900 px. Elle rend
            `null` quand il n'y a ni tâche ni accord : la doubler ne coûte rien
            le reste du temps. */}
        <div className="sym-file-tel">
          <FileAttente
            taches={cartesTaches}
            accords={accords}
            accordEnCours={accordEnCours}
            erreurAccord={erreurAccord}
            peutDecider={peutDecider}
            onAfficher={afficherTache}
            onFermer={fermerTache}
            onArreter={arreterTache}
            onResoudre={resoudreAccord}
          />
        </div>

        <InputBar onSend={sendMessage} disabled={false}
                  modeFile={loading || principalOccupe}
                  enCours={loading} onStop={stopper} />
      </div>

      <ReasoningPath
        steps={thinkingSteps}
        // La frise s'anime aussi pendant la reprise d'un accord approuvé.
        loading={loading || accordEnCours !== null}
        rail={
          <FileAttente
            taches={cartesTaches}
            accords={accords}
            accordEnCours={accordEnCours}
            erreurAccord={erreurAccord}
            peutDecider={peutDecider}
            onAfficher={afficherTache}
            onFermer={fermerTache}
            onArreter={arreterTache}
            onResoudre={resoudreAccord}
          />
        }
      />
    </div>
  )
}
