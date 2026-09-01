/**
 * Banc « le palier téléphone tient » — 01/09 nuit.
 *
 * Demande de Noa : « revoir le responsive mobile. Bloquer les pages pour éviter
 * qu'elles se zooment et se dézooment toutes seules. Revoir la disposition des
 * éléments. Et dans le chat, le bas : il y a des démarcations pas optimisées. »
 *
 * CE QUE LA CARTOGRAPHIE A TROUVÉ, et que ce banc empêche de revenir :
 *
 *  1. LA MOITIÉ DE `mobile.css` ÉTAIT MORTE. `theme.css` faisait
 *     `@import "./mobile.css"` — or un `@import` s'insère À LA PLACE de sa
 *     ligne, donc en TÊTE du fichier. Le bloc `@media (max-width: 900px)` de la
 *     FIN de theme.css passait après et gagnait, à spécificité et `!important`
 *     égaux. Trois règles du palier téléphone ne s'appliquaient jamais.
 *
 *  2. SUR TÉLÉPHONE, ON NE POUVAIT PAS APPROUVER. `FileAttente` — les boutons
 *     Approuver / Refuser — n'était montée que dans la colonne de droite, et
 *     cette colonne est masquée sous 900 px. Tout effet `externe` (envoyer un
 *     mail, déposer sur le Drive, tirer un visuel) restait suspendu, sans
 *     surface pour être débloqué. Trois des quatre lecteurs l'ont trouvé
 *     séparément.
 *
 *  3. LES CHAMPS QUI ZOOMENT vivaient hors des deux zones que la règle visait :
 *     la page de connexion (le premier écran d'un salarié), les cartes de
 *     réponses aux mails éditables, les visionneuses, et tout ce qui est monté
 *     en portail sur `document.body`.
 *
 * Ce banc lit les SOURCES : il ne demande ni serveur ni navigateur, et tourne
 * donc partout. Le rendu, lui, a été regardé à part.
 *
 *     node frontend/e2e/test-mobile.mjs [racine-du-frontend]
 */
import { readFileSync } from "node:fs"
import { join } from "node:path"

const RACINE = process.argv[2] || "frontend"
const echecs = []

function verifier(nom, cond, detail = "") {
  console.log(`  ${cond ? "✓" : "✗"} ${nom}${!cond && detail ? `  → ${detail}` : ""}`)
  if (!cond) echecs.push(nom)
}

const lire = (p) => readFileSync(join(RACINE, p), "utf8")

console.log("\n═══ LE PALIER TÉLÉPHONE\n")

// ── 1. L'ORDRE DE CASCADE, la cause qui rendait la moitié du fichier morte ──
const theme = lire("app/theme.css")
const layout = lire("app/layout.tsx")
verifier(
  "`theme.css` n'importe plus `mobile.css` (un @import se place en TÊTE)",
  !theme.includes('@import "./mobile.css"'))
verifier(
  "`layout.tsx` importe `mobile.css` APRÈS `theme.css` — c'est ce qui le rend vivant",
  layout.indexOf('import "./mobile.css"') > layout.indexOf('import "./theme.css"')
    && layout.includes('import "./mobile.css"'))
// Un commentaire s'étale sur plusieurs lignes, chacune préfixée de `//` : on
// cherche donc des fragments, pas une phrase entière — sinon le contrôle
// tombe sur une simple mise en forme.
verifier(
  "le pourquoi est écrit là où quelqu'un le relira",
  theme.includes("N'EST PLUS IMPORTÉ ICI")
    && layout.includes("il passait AVANT")
    && layout.includes("ne s'appliquait jamais"))

// ── 2. LE ZOOM ─────────────────────────────────────────────────────────
const mobile = lire("app/mobile.css")
verifier("le zoom est bridé au viewport",
  layout.includes("maximumScale: 1") && layout.includes("userScalable: false"))
verifier("la décision est datée et justifiée, pas subie",
  layout.includes("décision de Noa"))
verifier(
  "LA RÈGLE DES 16 px VISE TOUS LES CHAMPS, pas deux zones nommées "
  + "(le champ de connexion et les cartes de mails vivaient hors de ces zones)",
  /(^|\s)input,\s*textarea,\s*select\s*\{\s*font-size:\s*16px\s*!important/m.test(mobile))
verifier("les cases à cocher ne sont pas grossies au passage",
  mobile.includes('input[type="checkbox"]'))

// ── 3. LE BLOQUANT : approuver depuis un téléphone ─────────────────────
const chat = lire("components/chat/ChatWindow.tsx")
const chemin = lire("components/chat/ReasoningPath.tsx")
verifier("la colonne de droite est toujours masquée sous 900 px (comportement voulu)",
  /@media\s*\(max-width:\s*900px\)\s*\{\s*\.sym-path\s*\{\s*display:\s*none/.test(chemin))
verifier(
  "MAIS la file d'accords est montée une seconde fois, au-dessus de la saisie",
  chat.includes('className="sym-file-tel"') && chat.includes("<FileAttente"))
verifier("elle est montée AVANT la barre de saisie, là où le regard est déjà",
  chat.indexOf('className="sym-file-tel"') < chat.indexOf("<InputBar"))
verifier(
  "et elle ne s'affiche QUE sous 900 px — même seuil que la colonne, "
  + "sinon elle disparaîtrait des deux côtés entre 640 et 900 px",
  /\.sym-file-tel\s*\{\s*display:\s*none/.test(mobile)
    && /@media\s*\(max-width:\s*900px\)\s*\{\s*\.sym-file-tel\s*\{\s*display:\s*block/.test(mobile))
verifier(
  "le chat ne renvoie plus vers une colonne qui n'existe pas sur téléphone",
  !chat.includes("à droite.") && chat.includes("approuvez-la pour continuer"))

// ── 4. LA HAUTEUR : la page ne doit pas rebondir sous le doigt ─────────
const appLayout = lire("app/(app)/layout.tsx")
verifier("l'enveloppe de l'application porte une classe pour passer en dvh",
  appLayout.includes('className="sym-hauteur-ecran"'))
verifier("et mobile.css la fait passer en 100dvh",
  /\.sym-hauteur-ecran\s*\{\s*min-height:\s*100dvh/.test(mobile))
verifier("`.v2-page` aussi — corriger la scène seule ne servait à rien",
  /\.v2-page\s*\{\s*min-height:\s*100dvh/.test(mobile))
verifier(
  "les pages classiques descendent sous l'encoche "
  + "(l'en-tête y descend déjà, elles pas : c'est le défaut du 27/08)",
  mobile.includes("padding-top: calc(var(--v2-entete-h) + 26px + env(safe-area-inset-top))"))

// ── 5. RIEN NE DOIT ÊTRE HORS D'ATTEINTE ───────────────────────────────
const params = lire("app/(app)/parametres/SettingsClient.tsx")
verifier("`overflow-x: hidden` est toujours posé sur la page (il est nécessaire)",
  mobile.includes("html, body { overflow-x: hidden"))
verifier(
  "MAIS les onglets défilent chez eux — sinon, sans barre de défilement, "
  + "les derniers sont définitivement inaccessibles",
  params.includes("sym-onglets") && mobile.includes(".sym-onglets"))
verifier("la table des utilisateurs a enfin son conteneur défilant",
  params.includes('className="sym-table-large"') && mobile.includes(".sym-table-large"))

// ── 6. LE BAS DU CHAT : une seule démarcation, pas quatre ──────────────
const reflexion = lire("components/chat/ReflexionEnCours.tsx")
const saisie = lire("components/chat/InputBar.tsx")
verifier("la boîte de « en ce moment » est nommée, donc désactivable",
  reflexion.includes("sym-reflexion-boite"))
verifier("la zone de saisie aussi", saisie.includes('className="sym-zone-saisie"'))
verifier(
  "sur téléphone, trois des quatre démarcations tombent : "
  + "la boîte, la bande de fond, l'ombre portée",
  mobile.includes("border: none !important")
    && /\.sym-zone-saisie\s*\{\s*background:\s*transparent/.test(mobile)
    && /\.sym-barre-saisie\s*\{\s*box-shadow:\s*none/.test(mobile))
verifier("la carte du contexte cesse d'ajouter ses marges latérales",
  /\.v2-contexte\s*\{\s*margin:\s*0 0 6px/.test(mobile))
verifier("celle qui reste est celle du champ : on doit voir où l'on écrit",
  !mobile.includes(".sym-barre-saisie { border: none"))

// ── 7. LA LARGEUR RENDUE AU TEXTE ──────────────────────────────────────
const fil = lire("components/chat/MessageList.tsx")
verifier("le fil est nommé, pour que ses marges de bureau se réduisent",
  fil.includes('className="sym-fil') && reflexion.includes('className="sym-fil'))
verifier("et elles passent de 32 à 14 px — 36 px rendus au contenu",
  /\.sym-fil \.px-8[^}]*padding-left:\s*14px/.test(mobile))

console.log(`\n${"═".repeat(70)}`)
console.log(echecs.length ? `✗ ${echecs.length} échec(s) : ${echecs.join(", ")}` : "✓ 0 échec")
console.log("")
process.exit(echecs.length ? 1 : 0)
