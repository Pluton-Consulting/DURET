"use client"
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation"
import { Message, MessageContent } from "@/components/ai-elements/message"
import { MessageRenderer } from "./MessageRenderer"
import { SourcesReponse } from "./SourcesReponse"

interface Message_ {
  id: string
  role: "user" | "assistant"
  content: string
  // La tache qui a produit ce message, quand elle tourne EN ARRIERE-PLAN.
  // Ces bulles-la se dessinent en creux : contour pointille, fond blanc,
  // opacite reduite — elles marquent la place d'un echange dont le detail
  // s'affiche a droite, et qui reviendra ici une fois abouti.
  tacheId?: string
  // Bulle d'attente de la reponse : elle tient le rang du message a venir.
  // Sans elle, la reponse d'une tache de fond apparaitrait bien plus bas,
  // apres les echanges qui l'ont doublee, detachee de sa question.
  placeholder?: boolean
  // D'OU vient la reponse, et ce qu'elle a coute. Attache au MESSAGE et non au
  // tour : la provenance doit rester lisible trois questions plus tard.
  provenance?: {
    documents: string[]
    web: string[]
    webFiltre?: boolean
    jetons?: { entree: number; sortie: number }
    modele?: string
  }
}

/** LE DÉFILEMENT EST DÉLÉGUÉ, PLUS BRICOLÉ.
 *
 *  On mesurait nous-mêmes l'intention de l'utilisateur (« suit-il le fil, ou
 *  est-il remonté pour relire ? ») au moment du défilement, parce que la
 *  mesurer après l'ajout d'un message donne une réponse fausse : le message
 *  qui vient d'arriver a déjà allongé le conteneur. `Conversation` fait
 *  exactement ce raisonnement, en mieux — il tient compte du contenu qui
 *  grandit pendant que la réponse s'écrit, ce que notre version ne faisait
 *  pas. Et il apporte le bouton « revenir en bas », qui manquait.
 *
 *  DEUX RÉGLAGES CONTRE LES DÉFAUTS PAR DÉFAUT :
 *
 *  `initial="instant"` — à la restauration d'une conversation, tout le fil
 *  arrive d'un seul coup ; avec la valeur d'origine (`smooth`), la vue
 *  traverserait lentement l'historique entier sous les yeux de
 *  l'utilisateur avant de s'arrêter.
 *
 *  `resize="instant"` — la bulle d'attente change de texte à chaque étape du
 *  raisonnement, donc de hauteur. En `smooth`, chacun de ces changements
 *  déclencherait sa propre animation, et le fil tremblerait en continu
 *  pendant toute la réflexion.
 */
export default function MessageList({ messages, onAction, apiUrl, backendToken }:
  { messages: Message_[]; onAction?: (v: string) => void; apiUrl?: string; backendToken?: string }) {
  return (
    <Conversation initial="instant" resize="instant" data-testid="liste-messages">
      {/* PLUS D'AIR ENTRE LES MESSAGES QU'AVANT.
          Seize pixels suffisaient tant que chaque réponse était une carte : le
          cadre faisait la séparation. Le texte de l'IA coulant désormais à
          même la page, c'est le blanc qui doit dire où finit une réponse et
          où commence la question suivante. */}
      <ConversationContent className="gap-7 px-8 py-6">
        {messages.length === 0 && (
          <ConversationEmptyState
            className="sym-in mt-20"
            title="Posez votre question pour démarrer."
            description=""
          />
        )}
        <style>{`
          /* Une bulle EN ATTENTE se dessine en creux : le fond plein revient
             quand la reponse arrive. Le pointille dit « ce n'est pas fini »
             sans rien ajouter a l'ecran, et l'opacite l'eloigne juste assez
             pour que la conversation en cours reste au premier plan. */
          .sym-attente{ opacity:.62; box-shadow:none!important; transition:opacity .3s ease; }
          .sym-attente:hover{ opacity:.85; }
          .sym-attente-moi{ background:var(--marque-surface)!important;
            color:var(--marque-primary)!important;
            border:1.5px dashed var(--marque-primary)!important; }
          .sym-attente-ia{ border:1.5px dashed var(--marque-border);
            border-radius:var(--marque-radius-card-sm); padding:12px 16px;
            color:var(--marque-text-muted); font-size:13.5px; font-style:italic;
            /* La direction est explicite : le conteneur de message pose
               flex-col, qui renverrait le fil animé SOUS son texte au lieu
               de le prolonger. */
            display:flex; flex-direction:row; align-items:center; gap:9px; }
          @keyframes symPointille { to { background-position: 22px 0 } }
          .sym-attente-fil{ flex:1; height:2px; border-radius:1px;
            background:repeating-linear-gradient(90deg,
              var(--marque-border) 0 6px, transparent 6px 11px);
            background-size:22px 2px; animation:symPointille 1.1s linear infinite; }
          @media (prefers-reduced-motion: reduce){ .sym-attente-fil{ animation:none } }
        `}</style>
        {messages.map((msg) =>
          msg.role === "user" ? (
            <Message key={msg.id} from="user" className="sym-in">
              <MessageContent
                // `whitespace-pre-wrap` porte le saut de ligne entre le nom
                // du fichier joint et le texte : sans lui les deux se collent.
                className={`sym-card sym-bulle whitespace-pre-wrap${msg.tacheId ? " sym-attente sym-attente-moi" : ""}`}
                data-testid="message-utilisateur"
                data-en-attente={msg.tacheId ? "oui" : undefined}
                style={{
                  maxWidth: "70%",
                  background: "linear-gradient(180deg, var(--marque-primary), var(--marque-primary-hover))",
                  color: "var(--marque-text-on-dark)",
                  padding: "12px 16px",
                  borderRadius: "var(--marque-radius-card-sm)",
                  boxShadow: "var(--marque-shadow-card)",
                  border: "none",
                  fontSize: 14,
                  lineHeight: 1.5,
                }}
              >
                {msg.content}
              </MessageContent>
            </Message>
          ) : msg.placeholder ? (
            // La reponse n'est pas encore la : on tient sa place. Le detail de
            // l'avancement vit dans la colonne de droite — le repeter ici ferait
            // deux endroits a suivre pour une seule chose.
            <Message key={msg.id} from="assistant">
              <MessageContent data-testid="message-assistant" data-en-attente="oui"
                   className="sym-in sym-attente sym-attente-ia"
                   style={{ maxWidth: "70%", minWidth: 260 }}>
                <span>{msg.content || "réponse en cours"}</span>
                <span className="sym-attente-fil" aria-hidden="true" />
              </MessageContent>
            </Message>
          ) : (
            <Message key={msg.id} from="assistant">
              <MessageContent data-testid="message-assistant" className="max-w-full">
                <MessageRenderer content={msg.content} onAction={onAction}
                                 apiUrl={apiUrl} backendToken={backendToken} />
                {/* D'ou vient cette reponse, sous elle et non ailleurs : une
                    provenance rangee dans un panneau lateral n'est jamais lue. */}
                {msg.provenance && (
                  <SourcesReponse
                    documents={msg.provenance.documents}
                    web={msg.provenance.web}
                    webFiltre={msg.provenance.webFiltre}
                    jetons={msg.provenance.jetons}
                    modele={msg.provenance.modele}
                  />
                )}
              </MessageContent>
            </Message>
          )
        )}
      </ConversationContent>
      <ConversationScrollButton />
    </Conversation>
  )
}
