/**
 * Banc « le contexte pré-inscrit » — 02/09.
 *
 * Trouvé en répondant à une question de Noa : « Duret, tout a aussi été
 * corrigé depuis le début ? » Le contrôle de parité a montré 38 lignes d'écart
 * dans ChatWindow.tsx, et l'écart était UN DÉFAUT DE CHAQUE CÔTÉ.
 *
 * CHEZ DURET, LE BOUTON NE FAISAIT RIEN. Le tableau de bord appelait bien
 * `preinscrire` (bouton « Historique » d'une conversation passée, et carte
 * d'accord en attente), qui écrit dans localStorage et émet un événement. Mais
 * `ChatWindow` n'écoutait ni l'un ni l'autre : le clic n'avait aucun effet
 * visible. La moitié émettrice existait depuis le portage de l'interface v2,
 * la moitié réceptrice n'avait jamais été portée. C'est la divergence notée le
 * 23/08 dans CLAUDE.md comme « infra à porter un jour ».
 *
 * CHEZ SYMBIOSE, LE CONTEXTE S'AFFICHAIT EN CLAIR. `sansContexte` existe
 * depuis le 23/08 et son commentaire annonce exactement le contraire de ce que
 * le code faisait : elle n'était appelée QUE dans `lancerEnFile`. Sur le
 * chemin nominal, la bulle de la question montrait donc son préfixe technique
 * (« [Contexte rappelé par l'utilisateur — tâche précédente avec ... ] »),
 * résumé de 600 caractères compris, avant la question elle-même.
 *
 * LA RÈGLE, ET ELLE TIENT EN UNE PHRASE : ce qui PART porte le contexte, ce
 * qui S'AFFICHE ne l'a pas. C'est ce que ce banc vérifie, sur les quatre
 * endroits où une bulle de question est posée.
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

console.log(`\n═══ CONTEXTE PRÉ-INSCRIT — ${FRONT}\n`)

const chat = lire("components/chat/ChatWindow.tsx")
const tableau = lire("components/tableau/TableauDeBord.tsx")
const css = lire("app/interface-v2.css")

// ── 1. LES DEUX MOITIÉS EXISTENT ─────────────────────────────────────────
verifier("le tableau de bord ÉMET le contexte (`preinscrire`)",
         tableau.includes("export function preinscrire"))
verifier("il l'écrit ET prévient, pour un chat déjà monté",
         tableau.includes("localStorage.setItem(CLE_CONTEXTE")
         && tableau.includes("dispatchEvent(new CustomEvent(EVENEMENT_CONTEXTE"))
verifier("au moins un bouton l'appelle (sinon la moitié émettrice est morte)",
         (tableau.match(/onClick=\{\(\) => preinscrire\(/g) || []).length >= 1)

verifier("LE CHAT L'ÉCOUTE — c'est ce qui manquait chez Duret",
         chat.includes("window.addEventListener(EVENEMENT_CONTEXTE"))
verifier("il le relit aussi au montage (le chat peut être ouvert APRÈS le clic)",
         chat.includes("localStorage.getItem(CLE_CONTEXTE)"))
verifier("et il se désabonne en partant",
         chat.includes("removeEventListener(EVENEMENT_CONTEXTE"))

// ── 2. CE QUI PART PORTE LE CONTEXTE ─────────────────────────────────────
verifier("le message envoyé est préfixé par le contexte",
         chat.includes("[Contexte rappelé par l'utilisateur"))
verifier("le préfixe nomme l'expert par son libellé d'écran, pas sa clé",
         chat.includes("EXPERTS.find((e) => e.cle === contexte.expert)?.nom"))
verifier("le résumé rappelé est borné (un fil entier ne part pas en préfixe)",
         chat.includes("contexte.resume.slice(0, 600)"))
verifier("LE CONTEXTE NE SERT QU'UNE FOIS : il s'efface à l'envoi",
         chat.includes("if (contexte) oublierContexte()"))

// ── 3. CE QUI S'AFFICHE NE L'A PAS ───────────────────────────────────────
// LE DÉFAUT DE SYMBIOSE. Les bulles de question posaient `text`, la version
// ENRICHIE. Elles posent maintenant `texteAffiche`, qui EST la question seule,
// et la seule bulle qui reçoit du texte déjà enrichi (celle de la file
// d'attente) le nettoie par `sansContexte`.
const bulles = [...chat.matchAll(/role: "user", content: ([^,\n]+)[,\n]/g)]
  .map((m) => m[1].trim())
verifier("toutes les bulles de question sont repérées", bulles.length >= 4,
         String(bulles.length))
const fautives = bulles.filter((b) => /(^|[^A-Za-z])text($|[^A-Za-zÀ-ÿ])/.test(b)
                                      && !b.includes("sansContexte"))
verifier("AUCUNE bulle n'affiche le texte enrichi du contexte",
         fautives.length === 0, fautives.join(" | "))
verifier("`sansContexte` existe et sait retirer le préfixe",
         chat.includes("function sansContexte")
         && chat.includes('s.startsWith("[Contexte rappelé")'))
verifier("elle est APPELÉE là où le texte arrive déjà enrichi (file d'attente)",
         chat.includes("content: sansContexte(text)"))
verifier("le suivi de la demande en cours retient la question, pas le préfixe",
         chat.includes("queryEnCoursRef.current = texteAffiche"))

// ── 4. LA CARTE, ET DE QUOI LA RETIRER ───────────────────────────────────
verifier("une carte montre ce qui a été rappelé",
         chat.includes('className="v2-contexte"'))
verifier("elle dit si c'est une tâche ou une conversation",
         chat.includes('contexte.source === "tache" ? "Tâche" : "Conversation"'))
verifier("on peut la retirer sans envoyer (le clic peut être une erreur)",
         chat.includes('aria-label="Retirer ce contexte"')
         && chat.includes("onClick={oublierContexte}"))
verifier("elle se dessine AU-DESSUS de la saisie",
         chat.indexOf('className="v2-contexte"') < chat.indexOf("<InputBar onSend={sendMessage}"))
verifier("et le style qui la porte existe", css.includes(".v2-contexte"))

console.log(`\n${"═".repeat(70)}\n${
  echecs.length ? `✗ ${echecs.length} échec(s) : ${echecs.join(", ")}` : "✓ 0 échec"}\n`)
process.exit(echecs.length ? 1 : 0)
