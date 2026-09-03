"use client"
import { useEffect, useLayoutEffect, useRef, useState } from "react"
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputHeader,
  PromptInputButton,
  PromptInputSubmit,
  usePromptInputAttachments,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input"
import { MicIcon, PaperclipIcon, SquareIcon, XIcon, ZapIcon } from "lucide-react"
// La dictée : le navigateur ENREGISTRE, l'application TRANSCRIT
// (lib/dictee.ts → POST /api/chat/transcrire). Une première version s'en
// remettait à la reconnaissance vocale du navigateur, absente sur la moitié
// des postes — Noa : « le transcripteur doit être intégré à l'app ».
import { creerDictee, raisonIndisponible, type Dictee } from "@/lib/dictee"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
// La liste des process fréquents est une donnée PAR CLIENT (lib/raccourcis.ts,
// déclarée dans la dérive) : le menu, lui, est du socle.
import { RACCOURCIS } from "@/lib/raccourcis"

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
  // Le jeton de session, pour envoyer l'enregistrement du micro au serveur.
  token?: string
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

export default function InputBar({ onSend, disabled, modeFile, enCours, onStop, token }: InputBarProps) {
  // LE TEXTE RESTE À NOUS. `PromptInput` vide son formulaire dès la soumission,
  // AVANT même que l'envoi ait abouti : une question perdue en cas d'échec est
  // une question à retaper. En le gardant ici, on ne l'efface qu'une fois
  // l'envoi réellement passé.
  const [texte, setTexte] = useState("")
  const [erreur, setErreur] = useState("")
  const [raccourcisOuverts, setRaccourcisOuverts] = useState(false)

  // ── LA DICTÉE (03/09) ─────────────────────────────────────────────────
  // `avantDictee` garde ce qui était déjà tapé : la voix s'AJOUTE à la fin, on
  // ne remplace jamais ce que la personne avait écrit. Sans ce repère, chaque
  // correction du moteur (il se reprend en cours de phrase) réécrirait tout le
  // champ, en emportant le texte tapé avant.
  const [ecoute, setEcoute] = useState(false)
  const [transcrit, setTranscrit] = useState(false)   // un envoi au serveur est en cours
  const dicteeRef = useRef<Dictee | null>(null)
  const avantDictee = useRef("")

  // Une dictée oubliée continuerait d'écouter après un changement de page :
  // le micro resterait allumé, et l'onglet le montrerait — pas nous.
  useEffect(() => () => { dicteeRef.current?.arreter() }, [])

  // ── LA SAISIE GRANDIT JUSQU'À QUATRE LIGNES, PUIS DÉFILE ──────────────
  //
  // Relevé de Noa (03/09, deux fois) : un texte de plusieurs lignes dans le
  // champ, et l'on ne voit qu'une ligne — ni agrandissement, ni ascenseur. On
  // tape dans un texte qu'on ne voit pas. Quatre lignes visibles, puis un
  // ascenseur.
  //
  // DEUX CHEMINS, PAS UN SEUL. Une première version ne comptait que sur une
  // mesure JavaScript ; Noa a revu le même défaut. Désormais :
  //   · là où le navigateur sait faire grandir un champ tout seul
  //     (`field-sizing: content`, Chrome 123+), on le LAISSE FAIRE et on ne
  //     pose que le plafond (max-height + ascenseur) — aucune mesure, rien à
  //     rater ;
  //   · ailleurs, la hauteur est mesurée à chaque frappe et bornée.
  // Le plafond est calculé sur la hauteur de ligne RÉELLE du champ, pas sur
  // un nombre de pixels supposé.
  const champRef = useRef<HTMLTextAreaElement | null>(null)
  const LIGNES_VISIBLES = 4
  useLayoutEffect(() => {
    const champ = champRef.current
    if (!champ) return
    const style = window.getComputedStyle(champ)
    const ligne = parseFloat(style.lineHeight) || 20
    const marges = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0)
    const plafond = ligne * LIGNES_VISIBLES + marges
    const natif = typeof CSS !== "undefined" && CSS.supports?.("field-sizing", "content")
    if (natif) {
      champ.style.setProperty("field-sizing", "content")
      champ.style.height = ""
      champ.style.maxHeight = `${plafond}px`
      champ.style.overflowY = "auto"
      return
    }
    champ.style.setProperty("field-sizing", "auto")
    // Remise à zéro d'abord : sans elle, `scrollHeight` ne redescend jamais et
    // le champ resterait grand après un effacement.
    champ.style.height = "auto"
    champ.style.height = `${Math.min(champ.scrollHeight, plafond)}px`
    champ.style.overflowY = champ.scrollHeight > plafond ? "auto" : "hidden"
  }, [texte])

  const basculerDictee = () => {
    if (ecoute) {
      dicteeRef.current?.arreter()
      return
    }
    setErreur("")
    // LE BOUTON EXISTE TOUJOURS, ET C'EST LE CLIC QUI EXPLIQUE (03/09).
    // Le cacher quand le navigateur ne sait pas écouter paraissait propre, mais
    // relevé de Noa : « le bouton vocal ne s'affiche pas » — sans bouton, il
    // n'y a rien à comprendre, et l'on ne sait pas si c'est le navigateur,
    // l'adresse (http au lieu d'https) ou l'application qui est en retard.
    const empeche = raisonIndisponible()
    if (empeche) {
      setErreur(empeche)
      return
    }
    if (!token) {
      setErreur("Session absente : rechargez la page, puis réessayez la dictée.")
      return
    }
    avantDictee.current = texte ? texte.replace(/\s+$/, "") + " " : ""
    const dictee = creerDictee({
      apiUrl: API_URL,
      token,
      // Le texte rendu couvre TOUTE la dictée depuis le début : il remplace
      // ce qui avait été transcrit, jamais ce qui était tapé avant.
      surTexte: (dit) => setTexte(avantDictee.current + dit),
      surFin: () => { setEcoute(false); setTranscrit(false) },
      surErreur: (message) => setErreur(message),
      surTravail: (enCoursDeTranscription) => setTranscrit(enCoursDeTranscription),
    })
    if (!dictee) {
      setErreur("La dictée n'a pas pu démarrer. Réessayez.")
      return
    }
    dicteeRef.current = dictee
    setEcoute(true)
    void dictee.demarrer()
  }

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
    // La dictée s'arrête à l'envoi : sans cela, la phrase suivante s'écrirait
    // dans un champ qu'on vient de vider, à la suite d'un message déjà parti.
    dicteeRef.current?.arreter()
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
    <div className="sym-zone-saisie"
         style={{ padding: "12px clamp(12px, 4vw, 32px) calc(16px + env(safe-area-inset-bottom))", background: "var(--marque-chat-fond)" }}>
      {erreur && (
        <div role="alert" style={{ fontSize: 13, color: "var(--marque-error-text)", marginBottom: 10 }}>
          {erreur}
        </div>
      )}

      {raccourcisOuverts && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
          {RACCOURCIS.map((r) => (
            <button
              key={r.libelle}
              type="button"
              onClick={() => {
                setTexte(r.prompt)
                setRaccourcisOuverts(false)
                // Le curseur À LA FIN, et le champ déroulé jusqu'en bas : une
                // demande préremplie se complète par le bas (on y colle sa
                // transcription, on y précise son dossier). Sans cela, on
                // atterrit au début d'un texte de trente lignes.
                requestAnimationFrame(() => {
                  const champ = champRef.current
                  if (!champ) return
                  champ.focus()
                  champ.setSelectionRange(r.prompt.length, r.prompt.length)
                  champ.scrollTop = champ.scrollHeight
                })
              }}
              style={{ border: "1px solid var(--marque-border, #d8d8d8)", borderRadius: 999,
                       padding: "5px 12px", fontSize: 13, cursor: "pointer",
                       background: "var(--marque-surface, transparent)" }}
            >
              {r.libelle}
            </button>
          ))}
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
          <PromptInputButton
            type="button"
            data-testid="raccourcis"
            onClick={() => setRaccourcisOuverts((v) => !v)}
            title="Processus fréquents"
            aria-label="Processus fréquents"
            className="shrink-0"
          >
            <ZapIcon className="size-4" />
          </PromptInputButton>

          {/* LE MICRO EST TOUJOURS LÀ. Il l'a été conditionnel une journée, et
              c'était une erreur : quand le navigateur ne sait pas écouter, un
              bouton absent ne dit RIEN, et l'on cherche du côté de
              l'application. Désormais le clic explique — navigateur trop
              ancien, ou adresse en http alors que la voix exige https. */}
          <PromptInputButton
            type="button"
            data-testid="dictee"
            onClick={basculerDictee}
            disabled={disabled}
            title={ecoute ? "Arrêter la dictée" : "Dicter le message"}
            aria-label={ecoute ? "Arrêter la dictée" : "Dicter le message"}
            aria-pressed={ecoute}
            className="shrink-0"
            style={ecoute ? {
              border: "1px solid var(--marque-error-text)",
              color: "var(--marque-error-text)",
            } : undefined}
          >
            <MicIcon className="size-4" />
          </PromptInputButton>

          <PromptInputTextarea
            ref={champRef}
            rows={1}
            data-testid="saisie-message"
            className="min-h-9 py-2"
            value={texte}
            onChange={(e) => setTexte(e.target.value)}
            disabled={disabled}
            placeholder={ecoute
              ? (transcrit ? "Je vous écoute… (je transcris)" : "Je vous écoute…")
              : modeFile
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
