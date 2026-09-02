/**
 * Banc « plusieurs tâches à la fois » — 02/09.
 *
 * Relevé de Noa : « quand on lance plusieurs tâches à la fois il a tendance à
 * se mélanger, à en masquer une ; quand on affiche le résultat elle peut ne
 * s'afficher qu'à moitié ».
 *
 * TROIS DÉFAUTS DISTINCTS, TROIS SYMPTÔMES, une seule racine de conception :
 * des emplacements UNIQUES là où plusieurs tours coexistent.
 *
 *  1. EN MASQUER UNE. Le sondage ne remplissait que la bulle de la tâche
 *     pointée par `tacheActiveRef` — une place unique que `basculerActifVersCarte`
 *     remet à null juste APRÈS avoir posé la bulle. Lancer trois demandes
 *     d'affilée n'en ramenait donc qu'une : les deux premières finissaient en
 *     carte, leur bulle « réponse en cours » battant pour toujours dans le fil.
 *
 *  2. À MOITIÉ. `dernier` valait `rang === messages.length - 1`, un critère de
 *     POSITION. Or la réponse d'une tâche remplace sa bulle AU MILIEU du fil :
 *     elle n'était jamais « la dernière », donc rendue sans sa rangée de
 *     suggestions et avec son aperçu de fichier replié. La même réponse arrivée
 *     en direct s'affichait entière.
 *
 *  3. SE MÉLANGER. La provenance (documents, pages web, jetons) s'accumule dans
 *     une ref unique, vidée seulement quand une réponse se pose dans le chat.
 *     Un tour qui glissait en carte n'en posait pas : son compte restait, et
 *     s'affichait sous la réponse SUIVANTE. Six sources sous un « bonjour ».
 *
 * Ce banc EXÉCUTE la règle du plus récent (défaut 2) et lit le source pour les
 * deux autres. Sans navigateur ni build.
 */
import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const FRONT = process.argv[2]
  || join(dirname(fileURLToPath(import.meta.url)), "..")
const echecs = []

const verifier = (nom, cond, detail = "") => {
  console.log(`  ${cond ? "✓" : "✗"} ${nom}${!cond && detail ? `  → ${detail}` : ""}`)
  if (!cond) echecs.push(nom)
}
const lire = (rel) => readFileSync(join(FRONT, rel), "utf8")

console.log(`\n═══ PLUSIEURS TÂCHES À LA FOIS — ${FRONT}\n`)

const liste = lire("components/chat/MessageList.tsx")
const chat = lire("components/chat/ChatWindow.tsx")

// ── 1. « À MOITIÉ » : la règle du plus récent, EXÉCUTÉE ──────────────────
const bloc = liste.match(
  /const dernierRang = [\s\S]*?rang === messages\.length - 1/)
verifier("la règle « la plus récente » existe et s'extrait", Boolean(bloc))

if (bloc) {
  // On retire les annotations de type pour évaluer le JavaScript sous-jacent :
  // c'est la LOGIQUE qu'on teste, pas la compilation (tsc s'en charge).
  const js = bloc[0].replace(/:\s*Message_/g, "").replace(/:\s*number/g, "")
  const estLaPlusRecente = new Function(
    "messages", `${js}\n return estLaPlusRecente`)

  // LE SCÉNARIO EXACT DE NOA : deux tâches lancées, la PREMIÈRE répond.
  // Sa réponse remplace sa bulle au rang 1 ; la bulle de la seconde, encore
  // en attente, occupe le rang 2. Elle n'est donc PAS la dernière du tableau.
  const fil = [
    { role: "user", content: "question 1" },
    { role: "assistant", content: "réponse de la tâche 1", arrivee: 1 },
    { role: "assistant", content: "réponse en cours", placeholder: true },
  ]
  const f = estLaPlusRecente(fil)
  verifier("EXÉCUTÉ — la réponse d'une tâche revenue au MILIEU du fil est "
           + "reconnue comme la plus récente (elle garde suggestions et aperçu)",
           f(fil[1], 1) === true)
  verifier("et la bulle d'attente qui la suit ne lui vole pas ce rang",
           f(fil[2], 2) === false)

  // La seconde répond à son tour : le relais se fait, il n'y a jamais DEUX
  // rangées de pastilles à l'écran (la demande du 01/09 tient toujours).
  const fil2 = [
    { role: "user", content: "q1" },
    { role: "assistant", content: "r1", arrivee: 1 },
    { role: "assistant", content: "r2", arrivee: 2 },
  ]
  const g = estLaPlusRecente(fil2)
  verifier("quand la seconde répond, elle prend le relais",
           g(fil2[2], 2) === true)
  verifier("et la première le rend : UNE seule rangée de suggestions à l'écran",
           g(fil2[1], 1) === false)

  // Un historique rechargé ne porte aucun rang d'arrivée : on retombe sur la
  // position, sinon plus AUCUN message ne serait « le dernier » et l'écran
  // perdrait ses suggestions partout.
  const vieux = [
    { role: "user", content: "q" },
    { role: "assistant", content: "r" },
  ]
  const h = estLaPlusRecente(vieux)
  verifier("un historique rechargé (aucun rang) retombe sur la position",
           h(vieux[1], 1) === true && h(vieux[0], 0) === false)
}

verifier("l'écran ne juge plus « dernier » par la POSITION",
         !liste.includes("dernier={rang === messages.length - 1}"))
verifier("le rang d'arrivée est déclaré des deux côtés",
         liste.includes("arrivee?: number") && chat.includes("arrivee?: number"))
verifier("il est posé par un compteur monotone, pas par l'horloge",
         chat.includes("const prochaineArrivee = () => ++arriveeRef.current"))
verifier("une bulle d'ATTENTE n'en reçoit pas (elle ne porte pas de réponse)",
         /vivant \? \{ placeholder: true \} : \{ arrivee: prochaineArrivee\(\) \}/
           .test(chat))

// ── 2. « EN MASQUER UNE » : toutes les bulles sont tenues ────────────────
verifier("un registre tient TOUTES les tâches dont une bulle attend",
         chat.includes("tachesSuiviesRef"))
verifier("poser une bulle d'attente inscrit sa tâche au registre",
         /marquerEnAttente = \([^)]*\) => \{\s*\n\s*tachesSuiviesRef\.current\.add/
           .test(chat))
verifier("le sondage parcourt les tâches au lieu de n'en regarder qu'une",
         chat.includes("for (const t of toutes)")
         && chat.includes("const suivie = tachesSuiviesRef.current.has(t.id)"))
verifier("une tâche NON active mais suivie est soldée elle aussi",
         chat.includes("if (!suivie && !etaitActive) continue"))
verifier("la bannière, elle, reste au singulier — il n'y en a qu'une à l'écran",
         chat.includes('if (active && active.status === "en_cours")'))
verifier("une réponse posée libère sa place dans le registre",
         /poserReponse = \([^)]*\) => \{\s*\n(.*\n)*?\s*tachesSuiviesRef\.current\.delete\(tacheId\)/
           .test(chat))
verifier("une tâche suspendue sur un accord garde le lien avec sa bulle "
         + "(sans quoi sa reprise atterrit tout en bas)",
         chat.includes("if (!suivie) marquerEnAttente(idDerniereQuestionRef.current, t.id)")
         && chat.includes("majBulle(t.id, texte)"))
verifier("`majBulle` remplit sans refermer : le tour attend encore",
         /majBulle = [\s\S]{0,400}?m\.placeholder\) \? \{ \.\.\.m, content: contenu \}/
           .test(chat))

// ── 3. « SE MÉLANGER » : la provenance ne survit pas à son tour ──────────
verifier("un tour qui glisse en carte emporte sa provenance",
         /basculerActifVersCarte = \(\) => \{[\s\S]{0,900}?\n    instantane\(\)/
           .test(chat))
const apres = chat.split("basculerActifVersCarte = () => {")[1] || ""
verifier("le vidage précède la bascule, sinon il ne sert à rien",
         apres.indexOf("instantane()") < apres.indexOf("tacheActiveRef.current"))

// Ce qui NE devait PAS bouger : un tour déjà en carte n'écrivait déjà pas
// dans la provenance (il sort avant). Le contrôle fige cette propriété, qui
// est la moitié de la garantie.
verifier("un tour en carte n'écrit toujours pas la provenance du chat",
         /if \(cible\.carte\) \{[\s\S]{0,400}?return\n/.test(chat))

console.log(`\n${"═".repeat(70)}\n${
  echecs.length ? `✗ ${echecs.length} échec(s) : ${echecs.join(", ")}` : "✓ 0 échec"}\n`)
process.exit(echecs.length ? 1 : 0)
