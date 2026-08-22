"use client"
import { useState } from "react"
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputHeader,
  PromptInputButton,
  PromptInputSubmit,
  usePromptInputAttachments,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input"
import { PaperclipIcon, SquareIcon, XIcon } from "lucide-react"

export interface PieceJointe {
  name: string
  mime: string
  b64: string
}

interface InputBarProps {
  onSend: (text: string, piece?: PieceJointe) => void
  disabled?: boolean
  // Une tache tourne deja : ecrire reste possible, l'envoi MET EN FILE au lieu
  // d'interrompre. Le champ et le bouton le disent, sinon l'utilisateur croit
  // interrompre la tache en cours.
  modeFile?: boolean
  // Un tour tourne EN CE MOMENT sur cette conversation : le bouton d'arret
  // apparait. Sans lui, la seule sortie d'un tour parti de travers etait
  // d'attendre, ou de fermer l'onglet.
  enCours?: boolean
  onStop?: () => void
}

/** Trois barres indentées : la file d'attente, dessinée plutôt que dite. */
function IconeFile() {
  return (
    <svg width="18" height="14" viewBox="0 0 18 14" fill="none" aria-hidden="true">
      <rect x="0" y="0" width="14" height="2.6" rx="1.3" fill="currentColor" />
      <rect x="2.5" y="5.7" width="14" height="2.6" rx="1.3" fill="currentColor" opacity="0.75" />
      <rect x="5" y="11.4" width="13" height="2.6" rx="1.3" fill="currentColor" opacity="0.5" />
    </svg>
  )
}

// Limite alignée sur MAX_BODY_MB côté backend : mieux vaut refuser tout de suite
// avec un message clair que de laisser partir un envoi qui sera rejeté.
const TAILLE_MAX_MO = 10

/** LA PIÈCE JOINTE, ET LE BOUTON QUI L'AJOUTE.
 *
 *  `PromptInput` tient la liste des fichiers dans son contexte, mais n'en
 *  dessine aucun : sans ce composant, on choisit un fichier et RIEN
 *  n'apparaît — on ne sait plus s'il est joint. Il doit vivre à l'intérieur
 *  du formulaire, seul endroit d'où le contexte est lisible. */
function PieceJointeJointe({ desactive }: { desactive?: boolean }) {
  const fichiers = usePromptInputAttachments()
  // L'ENTETE N'EXISTE QUE S'IL Y A QUELQUE CHOSE DEDANS.
  //
  // Un encart « en bloc » fait basculer toute la barre en colonne et lui donne
  // une hauteur libre. Le rendre en permanence, meme vide, suffisait a doubler
  // la hauteur du champ de saisie alors qu'aucun fichier n'etait joint. Il
  // n'apparait donc qu'avec une piece, exactement comme avant.
  if (!fichiers.files.length) return null
  return (
    <PromptInputHeader>
      {fichiers.files.map((f) => (
        <span key={f.id} data-testid="piece-jointe" style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          background: "var(--marque-primary-subtle)", border: "1px solid var(--marque-primary-light)",
          borderRadius: "var(--marque-radius-pill)", padding: "5px 6px 5px 13px", maxWidth: "100%",
        }}>
          <span style={{
            fontSize: 13, fontWeight: 600, color: "var(--marque-primary)",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {f.filename || "fichier"}
          </span>
          <button type="button" onClick={() => fichiers.remove(f.id)} disabled={desactive}
                  aria-label={`Retirer ${f.filename || "le fichier"}`} style={{
            border: "none", background: "transparent", cursor: "pointer",
            color: "var(--marque-primary)", display: "flex", padding: "0 2px",
          }}>
            <XIcon className="size-3.5" />
          </button>
        </span>
      ))}
    </PromptInputHeader>
  )
}

/** LE BOUTON D'ENVOI, INERTE QUAND IL N'Y A RIEN À ENVOYER.
 *
 *  L'état dépend de DEUX choses : le texte saisi, et la présence d'une pièce
 *  jointe — un document seul suffit à partir. Or la liste des pièces n'est
 *  lisible que depuis l'intérieur du formulaire, d'où ce composant.
 *
 *  Le `status` reste sur « prêt » en toutes circonstances : passé à
 *  « streaming », le bouton se changerait en bouton d'arrêt et cesserait de
 *  soumettre, alors qu'ici envoyer PENDANT un tour est justement ce qui met
 *  la demande en file. */
function BoutonEnvoyer({ texte, desactive, modeFile }: {
  texte: string
  desactive?: boolean
  modeFile?: boolean
}) {
  const fichiers = usePromptInputAttachments()
  const peutEnvoyer = !desactive && (Boolean(texte.trim()) || fichiers.files.length > 0)
  return (
    <PromptInputSubmit
      status="ready"
      data-testid="envoyer-message"
      disabled={!peutEnvoyer}
      size={modeFile ? "sm" : "icon-sm"}
      title={modeFile ? "Mettre en file d'attente" : "Envoyer"}
      aria-label={modeFile ? "Mettre en file d'attente" : "Envoyer"}
    >
      {modeFile ? <><IconeFile /> En file</> : undefined}
    </PromptInputSubmit>
  )
}

function BoutonJoindre({ desactive }: { desactive?: boolean }) {
  const fichiers = usePromptInputAttachments()
  return (
    <PromptInputButton
      type="button"
      variant="ghost"
      disabled={desactive}
      onClick={() => fichiers.openFileDialog()}
      title="Joindre un fichier (Excel, Word, PDF, image, texte…)"
      aria-label="Joindre un fichier"
    >
      <PaperclipIcon className="size-4" />
    </PromptInputButton>
  )
}

export default function InputBar({ onSend, disabled, modeFile, enCours, onStop }: InputBarProps) {
  // LE TEXTE RESTE À NOUS. `PromptInput` vide son formulaire dès la soumission,
  // AVANT même que l'envoi ait abouti : une question perdue en cas d'échec est
  // une question à retaper. En le gardant ici, on ne l'efface qu'une fois
  // l'envoi réellement passé.
  const [texte, setTexte] = useState("")
  const [erreur, setErreur] = useState("")

  const surEnvoi = (message: PromptInputMessage) => {
    if (disabled) return
    const contenu = texte.trim()
    const f = message.files?.[0]

    let piece: PieceJointe | undefined
    if (f) {
      // Le fichier n'est exploitable qu'une fois converti en « data: ». Si la
      // conversion a échoué, l'URL reste un « blob: » — en découper la fin
      // enverrait au backend un identifiant local en guise de contenu, et
      // produirait un fichier corrompu sans le moindre message d'erreur.
      const virgule = f.url?.indexOf(",") ?? -1
      if (!f.url?.startsWith("data:") || virgule < 0) {
        setErreur("Le fichier n'a pas pu être lu. Réessayez de le joindre.")
        return
      }
      piece = {
        name: f.filename || "fichier",
        // Certains navigateurs ne renseignent pas le type pour les formats rares :
        // le backend se rabat alors sur l'extension du nom.
        mime: f.mediaType || "application/octet-stream",
        b64: f.url.slice(virgule + 1),
      }
    }

    if (!contenu && !piece) return
    // Un fichier envoyé sans question : on formule l'intention par défaut.
    onSend(contenu || `Analyse ce fichier : ${piece?.name}`, piece)
    setTexte("")
    setErreur("")
  }

  return (
    // LA BARRE FLOTTE, ELLE NE SE COLLE PLUS.
    //
    // Elle était un bandeau blanc plein largeur, séparé du fil par un trait
    // d'un pixel — la mise en page des formulaires d'il y a dix ans. Un trait
    // dit « ceci finit ici » ; une carte posée dit « ceci est un objet, on
    // écrit dedans ». Le fond reste celui du fil, et c'est la carte qui porte
    // la surface claire, son arrondi et son ombre.
    // 32 px de chaque côté sur un écran de 390 px, c'était 16 % de la largeur
    // perdus. `clamp` garde les 32 px sur grand écran et descend à 12 px sur
    // téléphone ; `env(safe-area-inset-bottom)` laisse la place à la barre
    // d'accueil d'iOS, qui recouvrait le bouton d'envoi.
    <div style={{ padding: "12px clamp(12px, 4vw, 32px) calc(16px + env(safe-area-inset-bottom))", background: "var(--marque-chat-fond)" }}>
      {erreur && (
        <div role="alert" style={{ fontSize: 13, color: "var(--marque-error-text)", marginBottom: 10 }}>
          {erreur}
        </div>
      )}

      <PromptInput
        className="sym-in sym-barre-saisie"
        onSubmit={surEnvoi}
        // Une question porte UN document. Sans ces deux bornes, un dépôt
        // multiple est accepté en silence puis tronqué à l'envoi.
        multiple={false}
        maxFiles={1}
        maxFileSize={TAILLE_MAX_MO * 1024 * 1024}
        // Sans ce rappel, un fichier trop lourd est écarté sans un mot :
        // l'utilisateur voit son geste ne rien produire.
        onError={(e) =>
          setErreur(e.code === "max_file_size"
            ? `Fichier trop volumineux (maximum ${TAILLE_MAX_MO} Mo).`
            : e.code === "max_files"
            ? "Un seul fichier à la fois."
            : e.message)
        }
        // Le dépôt fonctionne sur toute la zone de conversation, pas seulement
        // sur le champ : c'est le geste naturel quand on vient de lire un
        // message et qu'on veut y répondre avec un document.
        globalDrop
      >
        {/* La pièce jointe, au-dessus, et SEULEMENT quand il y en a une. */}
        <PieceJointeJointe desactive={disabled} />

        {/* UNE SEULE RANGÉE, comme avant : trombone à gauche, champ au milieu,
            arrêt et envoi à droite.

            La disposition d'origine d'AI Elements empile le champ puis une
            barre d'outils en dessous, et impose au champ une hauteur minimale
            de 64 px : la saisie occupait plus du double de sa hauteur
            precedente pour écrire une seule ligne. Ici la rangée est explicite,
            et le champ retrouve sa hauteur d'avant tout en continuant de
            grandir quand le texte le demande. */}
        {/* LES BOUTONS SONT CENTRÉS, PLUS ALIGNÉS EN BAS.
            `items-end` les collait au bord inférieur de la carte : « Arrêter »
            et « En file », qui portent un libellé et sont donc hauts, venaient
            toucher le bord. Centrés, ils respirent, et le champ garde sa
            liberté de grandir — c'est lui qui pousse la carte, pas eux. */}
        <div className="flex w-full items-center gap-1.5 px-2 py-2">
          <BoutonJoindre desactive={disabled} />

          <PromptInputTextarea
            data-testid="saisie-message"
            className="min-h-9 py-2"
            value={texte}
            onChange={(e) => setTexte(e.target.value)}
            disabled={disabled}
            placeholder={modeFile
              ? "Écrivez pour mettre une autre tâche dans la file d'attente"
              : "Posez votre question... (Entrée pour envoyer, Maj+Entrée pour saut de ligne)"}
          />

          {/* L'ARRÊT VIT À CÔTÉ DE L'ENVOI, pas à sa place.
              `PromptInputSubmit` sait se changer en bouton d'arrêt quand on lui
              passe `onStop`, mais il devient alors `type="button"`, et le
              formulaire se retrouve SANS bouton de soumission : le clic
              n'envoie plus rien (la touche Entrée, elle, continue de marcher,
              ce qui rend la panne d'autant plus déroutante). Or ici l'envoi
              doit rester possible PENDANT un tour : il met en file. Deux
              boutons distincts, donc, et un `status` laissé sur « prêt » pour
              que la soumission ne bascule jamais. */}
          {enCours && onStop && (
            <PromptInputButton
              type="button"
              data-testid="stopper-ia"
              onClick={onStop}
              title="Arrêter le traitement en cours"
              aria-label="Arrêter le traitement en cours"
              className="shrink-0"
              style={{
                border: "1px solid var(--marque-error-text)",
                color: "var(--marque-error-text)",
              }}
            >
              <SquareIcon className="size-3.5 fill-current" /> Arrêter
            </PromptInputButton>
          )}

          <BoutonEnvoyer texte={texte} desactive={disabled} modeFile={modeFile} />
        </div>
      </PromptInput>
    </div>
  )
}
