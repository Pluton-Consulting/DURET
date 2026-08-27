"use client"
import { useRef, useState, type ReactNode } from "react"
import { md } from "@/components/blocks/text/inline"
import { CheckIcon, CopyIcon } from "lucide-react"
import { MessageActions, MessageAction, MessageResponse } from "@/components/ai-elements/message"
import { Suggestions, Suggestion } from "@/components/ai-elements/suggestion"
import { ApercuDocument, formatDepuisNom, type FormatApercu } from "./ApercuDocument"
import {
  QuoteCard, InvoiceCard, EmailCard, DocCard, DocApercu, SiteApercu, VisuelPaysager, FileCard, ContactCard, ProjectCard,
  SimpleTable, StatusTable, KeyValueTable,
  BarChart, HBarChart, ProgressBars, DonutChart, LineChart, Gauge,
  Callout, StatTile, Badge, BulletList, PlanEtapes,
} from "@/components/blocks"

// Une réponse de l'IA = du texte, avec éventuellement des composants intercalés
// sous forme de blocs ```ui {json}```. On parse, on rend le composant du registre.
// L'IA n'émet JAMAIS de HTML/CSS : uniquement de la donnée (JSON) → sûr + thémé par tokens.

type Part = { kind: "text"; text: string } | { kind: "ui"; block: any }

// ON ACCEPTE AUSSI ```json ET UN BLOC NU. Relevé en production : le modèle a
// balisé son composant ```json au lieu de ```ui. Le bloc n'était donc pas
// reconnu, et l'utilisateur a vu du JSON brut au milieu de la réponse — la
// pire des sorties, celle qui ressemble à une fuite technique.
//
// La consigne du prompt reste ```ui, mais on ne peut pas exiger d'un modèle
// modeste qu'il ne se trompe jamais de balise sur un contenu que sa forme
// suffit à identifier. Le filtre de sûreté n'est pas la BALISE, c'est le
// registre des types plus bas : un objet dont le `type` est inconnu, ou dont
// un champ requis manque, n'est pas rendu. Élargir la balise n'ouvre donc
// aucune porte — ça évite seulement d'afficher du JSON à un humain.
// La clôture est FACULTATIVE. Un bloc coupé net par le plafond de sortie
// n'avait pas ses trois accents finaux, donc ne correspondait à rien, donc
// restait dans le texte — et le markdown l'affichait en bloc de code. Relevé
// en production : un cahier des charges entier rendu sous forme de
// `{"type":"list","items":["1. Description sommaire du projet","2. Pres…` sur
// une seule ligne à faire défiler. On capture donc jusqu'à la clôture OU la
// fin du message, et c'est `lire()` qui juge si le contenu est exploitable.
const RE_BLOC = /```(?:ui|json)?[ \t]*\n?[ \t]*(\{[\s\S]*?)(?:```|$)/g

/** Ferme ce qui est resté ouvert : chaîne, tableaux, objets. */
function fermer(s: string): string {
  const pile: string[] = []
  let chaine = false, echap = false
  for (const c of s) {
    if (echap) { echap = false; continue }
    if (c === "\\") { echap = true; continue }
    if (chaine) { if (c === '"') chaine = false; continue }
    if (c === '"') { chaine = true; continue }
    if (c === "{" || c === "[") pile.push(c)
    else if (c === "}" || c === "]") pile.pop()
  }
  let out = s + (chaine ? '"' : "")
  out = out.replace(/,\s*$/, "")
  while (pile.length) out += pile.pop() === "{" ? "}" : "]"
  return out
}

/** JSON D'UN MODÈLE : souvent juste, parfois coupé, jamais garanti.
 *
 *  On tente la lecture stricte, puis la refermeture, puis on recule d'un
 *  séparateur à la fois — un élément perdu en fin de liste vaut mieux que la
 *  liste entière affichée en JSON brut à un humain. Rien n'est inventé : on
 *  ne fait que RETIRER ce qui est incomplet. Si rien ne parse, on renonce et
 *  le texte d'origine est laissé intact.
 */
function lire(brut: string): any {
  const t = brut.trim()
  try { return JSON.parse(t) } catch { /* on répare */ }
  let s = t
  for (let essai = 0; essai < 200 && s.length > 2; essai++) {
    try { return JSON.parse(fermer(s)) } catch { /* on recule */ }
    const virgule = s.lastIndexOf(",")
    const ouvre = Math.max(s.lastIndexOf("["), s.lastIndexOf("{"))
    if (virgule <= 0 && ouvre <= 0) break
    const suivant = virgule > ouvre ? s.slice(0, virgule) : s.slice(0, ouvre + 1)
    // LE RECUL DOIT RECULER.
    //
    // `slice(0, ouvre + 1)` GARDE le crochet ouvrant — c'est voulu, on referme
    // ensuite. Mais quand ce crochet est le DERNIER caractère, la coupe ne
    // retire rien : `s` est identique au tour suivant, `lastIndexOf` retrouve
    // le même crochet, et les essais s'épuisent sur une chaîne qui ne bouge
    // plus. La réparation renonçait alors, et le bloc partait au rendu
    // markdown : le JSON s'affichait EN CLAIR dans le chat, ce qu'aucun
    // utilisateur ne devrait voir. Relevé le 27/08 sur un `keyvalue` de devis
    // dont le modèle avait écrit une virgule de trop au milieu.
    //
    // Un caractère de moins suffit à débloquer : la boucle progresse toujours,
    // donc elle se termine toujours.
    s = suivant.length < s.length ? suivant : s.slice(0, -1)
  }
  return null
}

/** Retire des lignes ce que la réparation n'a pas pu sauver.
 *
 *  `lire()` promet de ne faire que RETIRER ce qui est incomplet ; elle le fait
 *  au caractère près, donc il lui arrive de laisser un résidu à la place d'une
 *  ligne — une chaîne vide, ou une ligne à une seule cellule là où il en faut
 *  deux. Le composant l'affichait alors comme une ligne vide au milieu d'une
 *  fiche devis. On enlève ces restes ici, une fois le type connu : c'est le
 *  seul endroit où l'on sait combien de cellules une ligne doit porter.
 *
 *  Si plus rien ne tient debout, `rows` devient vide — `present()` refuse
 *  alors le composant, et rien ne s'affiche. C'est le bon résultat : le JSON,
 *  lui, a déjà quitté le texte.
 */
function nettoyer(bloc: any): any {
  const lignes = bloc?.rows
  if (!Array.isArray(lignes)) return bloc
  const largeur = Array.isArray(bloc.columns) && bloc.columns.length
    ? bloc.columns.length
    : 2                              // keyvalue : une étiquette et une valeur
  bloc.rows = lignes.filter((l: any) => Array.isArray(l) && l.length >= largeur)
  return bloc
}

function parse(content: string): Part[] {
  const parts: Part[] = []
  const re = new RegExp(RE_BLOC)
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(content)) !== null) {
    const bloc: any = lire(m[1])
    // Un objet SANS `type` n'est pas un composant : c'est du JSON que le
    // modèle montre volontairement. On le laisse tel quel dans le texte.
    if (!bloc || typeof bloc.type !== "string") continue
    if (m.index > last) parts.push({ kind: "text", text: content.slice(last, m.index) })
    parts.push({ kind: "ui", block: nettoyer(bloc) })
    last = re.lastIndex
  }
  if (last < content.length) parts.push({ kind: "text", text: content.slice(last) })
  return parts
}

// Champs requis par type : si l'un manque, le composant n'est PAS rendu (on garde le texte).
const REQUIRED: Record<string, string[]> = {
  // `total` n'est plus exigé : la forme document porte ses montants dans
  // `totals`, et un devis complet se retrouvait rejeté pour un champ que sa
  // propre écriture rendait inutile.
  quote: ["client", "lines"],
  invoice: ["number", "client", "amount"],
  email: ["subject", "from"],
  doc: ["name"],
  // L'aperçu vit ou meurt avec son extrait : sans contenu réel à montrer, la
  // carte `doc` classique suffit — un cadre d'aperçu vide serait pire que rien.
  doc_apercu: ["extrait"],
  // Une page web se montre avec son adresse ; l'aperçu, lui, est facultatif.
  site: ["url"],
  // Une planche de rendus générés : au moins une image, sinon rien à montrer.
  visuel: ["images"],
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
  plan: ["etapes"],
}

// Un champ est « fourni » s'il n'est ni vide, ni une chaîne blanche, ni un tableau vide.
function present(v: any): boolean {
  if (v === undefined || v === null) return false
  if (typeof v === "string") return v.trim().length > 0
  if (Array.isArray(v)) return v.length > 0
  return true
}

/** LE FICHIER ANNONCÉ, ET LE DOCUMENT LUI-MÊME.
 *
 *  Jusqu'ici un document déposé n'était qu'une ligne à télécharger : pour
 *  vérifier que le contenu était le bon, il fallait quitter le chat, ouvrir
 *  le fichier, revenir. Le rendu est maintenant SOUS la carte.
 *
 *  Rien de nouveau n'est demandé au modèle : il émet déjà des blocs
 *  `fichier` avec une URL et un nom. C'est l'extension du nom qui décide de
 *  la visionneuse — et un format inconnu ne fait rien apparaître, la carte
 *  reste seule.
 *
 *  L'aperçu se monte à l'ouverture, jamais avant : c'est lui qui déclenche
 *  la récupération du fichier, et pour un PDF le moteur de 4,5 Mo. Une
 *  conversation qui cite dix fichiers n'en télécharge donc aucun tant que
 *  personne ne regarde. Il est ouvert par défaut, parce qu'on veut voir le
 *  document qu'on vient de produire — mais refermable, et l'état ne se
 *  perd pas au rendu suivant. */
function FichierAvecApercu({ bloc, acces }: {
  bloc: any
  acces?: { apiUrl?: string; backendToken?: string; dernier?: boolean }
}) {
  const { url, nom, format } = bloc
  // Trois sources, de la plus fiable à la plus approximative : le format
  // déclaré, le nom du fichier, puis l'URL.
  const detecte: FormatApercu | null =
    (format ? formatDepuisNom(`x.${String(format).replace(/^\./, "")}`) : null)
    ?? formatDepuisNom(nom)
    ?? formatDepuisNom(url)
  // L'APERÇU NE S'OUVRE TOUT SEUL QUE SUR LE DERNIER MESSAGE.
  //
  // Chaque carte va chercher son fichier dès qu'elle s'affiche. En rouvrant
  // une conversation, TOUTES les cartes de l'historique partaient donc en même
  // temps — et comme le modèle avait resservi les mêmes liens sur plusieurs
  // tours, la console se remplissait du même 404 répété sept fois pour deux
  // documents. On paie de la bande passante pour des documents que personne ne
  // regarde, et on transforme une expiration normale en avalanche d'erreurs.
  //
  // Le document qu'on vient de produire s'ouvre donc encore de lui-même —
  // c'est celui qu'on veut voir — et les précédents attendent qu'on le
  // demande. Le bouton reste là, au même endroit.
  const [ouvert, setOuvert] = useState(acces?.dernier !== false)
  // Une fois affiché, l'aperçu ne redescend plus : le replier le cache, il ne
  // le décharge pas. C'est ce qui évite le second trajet réseau qui échouait.
  const vuUneFois = useRef(false)
  if (ouvert) vuUneFois.current = true

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, maxWidth: 620, width: "100%" }}>
      <FileCard {...bloc} {...acces} />
      {detecte && (
        <>
          <button
            type="button"
            onClick={() => setOuvert((v) => !v)}
            className="sym-tap"
            data-testid="bascule-apercu"
            aria-expanded={ouvert}
            style={{
              alignSelf: "flex-start", border: "1px solid var(--marque-border)",
              background: "var(--marque-surface)", color: "var(--marque-text-muted)",
              borderRadius: "var(--marque-radius-pill)", padding: "4px 12px",
              fontSize: 12.5, cursor: "pointer",
            }}
          >
            {ouvert ? "Masquer l’aperçu" : "Afficher l’aperçu"}
          </button>
          {/* MASQUER N'EST PAS DÉCHARGER.
              Le repli démontait l'aperçu, donc libérait le fichier, donc le
              retéléchargeait au réaffichage — et ce second trajet échouait
              (« Aperçu indisponible (Failed to fetch) ») là où le premier
              avait parfaitement abouti. Relevé en production sur un document
              qui s'affichait très bien une seconde plus tôt.
              L'aperçu n'est donc monté qu'au PREMIER affichage — la
              visionneuse et le fichier restent différés jusque-là, c'est tout
              l'intérêt — puis il ne redescend plus : on le cache. Le fichier
              n'est récupéré qu'une fois, et il n'y a plus de second trajet
              pour échouer.
              L'aperçu s'ouvre par défaut : il est donc monté dès le premier
              rendu, et le masquer se borne à le cacher. */}
          {(ouvert || vuUneFois.current) && (
            <div hidden={!ouvert}>
              <ApercuDocument url={url} format={detecte} nom={nom}
                              apiUrl={acces?.apiUrl} backendToken={acces?.backendToken} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

function renderBlock(block: any, onAction?: (v: string) => void,
                     acces?: { apiUrl?: string; backendToken?: string; dernier?: boolean }): ReactNode {
  if (!block || typeof block !== "object") return null
  const { type, ...p } = block
  const req = REQUIRED[type]
  if (req && !req.every((k) => present(p[k]))) return null   // champ requis manquant → pas de composant
  switch (type) {
    case "quote":         return <QuoteCard {...p} />
    case "invoice":       return <InvoiceCard {...p} />
    case "email":         return <EmailCard {...p} />
    case "doc":           return <DocCard {...p} />
    case "doc_apercu":    return <DocApercu {...p} />
    case "site":          return <SiteApercu url={p.url} titre={p.titre} apercu={p.apercu} apiUrl={acces?.apiUrl} backendToken={acces?.backendToken} />
    case "visuel":        return <VisuelPaysager titre={p.titre} images={p.images} apiUrl={acces?.apiUrl} backendToken={acces?.backendToken} />
    // Le telechargement est controle cote serveur : le composant a besoin
    // du jeton, un lien nu partirait sans en-tete et serait refuse. La
    // visionneuse a le meme besoin — d'ou le detour par FichierAvecApercu,
    // qui va chercher le document authentifie avant de l'afficher.
    case "fichier":       return <FichierAvecApercu bloc={p} acces={acces} />
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
    case "plan":          return <PlanEtapes {...p} />
    case "badge":         return <Badge tone={p.tone}>{p.text}</Badge>
    case "callout":       return <Callout tone={p.tone} title={p.title}>{md(p.text)}</Callout>
    // LES PROPOSITIONS PASSENT PAR AI ELEMENTS. Le bouton maison faisait le
    // travail, mais la version du registre apporte ce qui manquait vraiment :
    // une rangee qui DEFILE horizontalement au lieu de se replier sur trois
    // lignes des que les libelles s'allongent, ce qui arrivait vite avec des
    // propositions ecrites par le modele.
    case "quick_replies": return (
      <Suggestions>
        {(p.options as string[]).map((o) => (
          <Suggestion key={o} suggestion={o} onClick={onAction} />
        ))}
      </Suggestions>
    )
    default:              return null
  }
}

/** LA RÉPONSE SE COPIE, MÊME SANS HTTPS.
 *
 *  `navigator.clipboard` n'existe QUE dans un contexte sécurisé. Cette
 *  application tourne en HTTP sur un VPN fermé : l'API est donc absente, et
 *  un bouton qui s'appuierait dessus ne ferait rien, sans erreur visible.
 *  D'où le repli par champ masqué, déprécié mais opérant partout. */
async function copier(texte: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texte)
      return true
    }
  } catch { /* on tente le repli */ }
  try {
    const zone = document.createElement("textarea")
    zone.value = texte
    zone.setAttribute("readonly", "")
    zone.style.position = "fixed"
    zone.style.opacity = "0"
    document.body.appendChild(zone)
    zone.select()
    const ok = document.execCommand("copy")
    zone.remove()
    return ok
  } catch {
    return false
  }
}

/** Les actions n'apparaissent qu'au survol du message : présentes quand on en
 *  a besoin, absentes le reste du temps. `focus-within` les révèle aussi au
 *  clavier, sans quoi elles seraient inatteignables sans souris. */
function ActionsReponse({ texte }: { texte: string }) {
  const [etat, setEtat] = useState<"" | "ok" | "ko">("")
  if (!texte.trim()) return null
  return (
    <MessageActions className="-ml-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100 focus-within:opacity-100">
      <MessageAction
        tooltip={etat === "ok" ? "Copié" : etat === "ko" ? "Copie impossible" : "Copier la réponse"}
        label="Copier la réponse"
        onClick={async () => {
          setEtat(await copier(texte) ? "ok" : "ko")
          setTimeout(() => setEtat(""), 1800)
        }}
      >
        {etat === "ok" ? <CheckIcon className="size-3.5" /> : <CopyIcon className="size-3.5" />}
      </MessageAction>
    </MessageActions>
  )
}

export function MessageRenderer({ content, onAction, apiUrl, backendToken, dernier = true }:
  { content: string; onAction?: (v: string) => void; apiUrl?: string
    backendToken?: string
    /** Dernier message du fil ? Seul lui ouvre ses aperçus tout seul. */
    dernier?: boolean }) {
  const parts = parse(content)
  // Ce qu'on copie : la réponse en toutes lettres, sans les blocs de données
  // qui ne veulent rien dire hors de l'écran.
  const texteSeul = parts.filter((p) => p.kind === "text").map((p) => p.text.trim()).join("\n\n").trim()

  return (
    // LE TEXTE DE L'IA NE VIT PLUS DANS UNE BOÎTE.
    //
    // Chaque paragraphe était enfermé dans une carte blanche à bordure et
    // ombre. Une réponse un peu longue devenait un empilement de rectangles
    // identiques, où rien ne se distinguait de rien : ni un titre, ni un
    // tableau, ni un document. Le cadre, répété, cessait de signifier.
    //
    // La réponse coule donc à même la page, comme un texte qu'on lit, et le
    // CADRE redevient un signal : ce qui est encadré est un objet — une
    // carte, un graphique, un document. C'est le contraste qui porte la
    // lecture, pas la décoration.
    //
    // La largeur du TEXTE est bornée en caractères et non en pixels : au-delà
    // d'une soixantaine, l'œil perd la ligne suivante en revenant à la marge.
    // Elle est posée par `sym-mesure` sur les éléments de texte eux-mêmes, et
    // non sur le conteneur : un tableau ou une carte a le droit d'être large,
    // une phrase non.
    <div className="group flex w-full flex-col items-stretch gap-3">
      {parts.map((part, i) => {
        if (part.kind === "text") {
          const t = part.text.trim()
          if (!t) return null
          return (
            <div key={i} className="sym-in sym-mesure w-full text-[var(--marque-text-body)]">
              {/* Streamdown remplace notre rendu maison : titres, listes,
                  tableaux, code coloré et formules, et surtout un rendu
                  correct du markdown ENCORE INCOMPLET pendant que la réponse
                  s'écrit : une phrase coupée au milieu d'un `**gras**` ne
                  fait plus clignoter les astérisques.

                  Il est placé APRÈS `parse()`, jamais avant : les blocs
                  ```ui / ```json ont déjà été retirés du texte à ce stade.
                  L'ordre inverse les afficherait comme de jolis blocs de
                  code au lieu de les transformer en composants. */}
              <MessageResponse className="text-[14.5px] leading-[1.65]">{t}</MessageResponse>
            </div>
          )
        }
        const node = renderBlock(part.block, onAction, { apiUrl, backendToken, dernier })
        return node ? <div key={i} className="sym-in">{node}</div> : null
      })}
      <ActionsReponse texte={texteSeul} />
    </div>
  )
}
