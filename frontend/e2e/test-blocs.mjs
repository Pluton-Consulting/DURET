/**
 * Banc des BLOCS D'ÉCRAN — un JSON abîmé ne doit JAMAIS s'afficher en clair.
 *
 * Relevé en recette le 27/08, question 1 : le modèle avait écrit une virgule
 * de trop au milieu d'un `keyvalue` de devis. La réparation de `lire()` a
 * renoncé, le bloc est reparti au rendu markdown, et l'utilisateur a lu ceci
 * dans le chat, à la place de sa fiche devis :
 *
 *   {"type":"keyvalue","rows":[["Référence","DV0001054"], … ,","Montant", …]]}
 *
 * La cause n'était pas la corruption elle-même — la réparation sait retirer ce
 * qui est incomplet — mais une boucle qui ne progressait plus : `slice(0,
 * ouvre + 1)` garde le crochet ouvrant, or quand ce crochet est le DERNIER
 * caractère, la coupe ne retire rien. La chaîne restait identique, les essais
 * s'épuisaient sur place, et `lire()` rendait null.
 *
 * Les fonctions sont extraites du composant livré et exécutées ici : pas de
 * build, pas de navigateur, pas de React. Elles sont pures, c'est tout ce
 * qu'il faut.
 *
 *   node e2e/test-blocs.mjs [chemin/du/frontend]
 */
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"

const BASE = process.argv[2] || fileURLToPath(new URL("..", import.meta.url))
const SRC = readFileSync(`${BASE}/components/chat/MessageRenderer.tsx`, "utf8")

// On prend les deux fonctions pures, et on retire les annotations de type.
function extraire(nom) {
  const i = SRC.indexOf(`function ${nom}(`)
  if (i < 0) throw new Error(`fonction absente du composant livré : ${nom}`)
  // On borne sur l'accolade fermante EN DÉBUT DE LIGNE : compter les accolades
  // ne marche pas ici, le corps de ces fonctions en contient dans ses propres
  // littéraux (`c === "{"`), et le compteur se déséquilibre aussitôt.
  const fin = SRC.indexOf("\n}", i)
  if (fin < 0) throw new Error(`fonction non fermée : ${nom}`)
  return SRC.slice(i, fin + 2)
}
const sansTypes = (s) => s
  .replace(/function (\w+)\(([^)]*)\)\s*:\s*[\w\[\]|<> ]+/g, (m, n, a) =>
    `function ${n}(${a.replace(/\s*:\s*[\w\[\]|<> ]+/g, "")})`)
  // `const parts: Part[] = []`, mais aussi `let m: RegExpExecArray | null`,
  // qui n'a pas d'affectation : la déclaration seule doit perdre son type.
  .replace(/\b(const|let) (\w+)\s*:\s*[\w\[\]|<> ]+/g, "$1 $2")
  // les lambdas typées : `(l: any) => …`
  .replace(/\((\w+)\s*:\s*[\w\[\]|<> ]+\)\s*=>/g, "($1) =>")

// `parse` a besoin du motif du bloc, qui vit hors des fonctions.
const RE_BLOC_SRC = SRC.match(/^const RE_BLOC = .*$/m)
if (!RE_BLOC_SRC) throw new Error("motif RE_BLOC absent du composant livré")

// JOUÉ CONTRE LA VERSION D'AVANT, ce banc doit dire NON, pas planter. Sans
// `decouper`, on remet le comportement d'alors — le bloc entier lu d'un coup —
// et les contrôles tombent en nommant ce qu'on n'a pas vu : une carte sur quatre.
const DECOUPER_AVANT = "function decouper(brut) { return [brut] }"
let decouperSrc
try { decouperSrc = sansTypes(extraire("decouper")) } catch { decouperSrc = DECOUPER_AVANT }

const { fermer, lire, nettoyer, decouper, parse } = (new Function(
  RE_BLOC_SRC[0] + "\n" +
  sansTypes(extraire("fermer")) + "\n" + sansTypes(extraire("lire")) + "\n" +
  sansTypes(extraire("nettoyer")) + "\n" + decouperSrc + "\n" +
  sansTypes(extraire("parse")) +
  "\nreturn { fermer, lire, nettoyer, decouper, parse }"))()

// Le composant appelle `nettoyer` juste après `lire` : on juge la paire.
const rendu = (brut) => { const b = lire(brut); return b ? nettoyer(b) : null }

const VERT = "\x1b[92m", ROUGE = "\x1b[91m", GRIS = "\x1b[90m", RAZ = "\x1b[0m"
let echecs = 0
const controle = (titre, ok, detail = "") => {
  if (ok) console.log(`  ${VERT}✓${RAZ} ${titre}`)
  else { echecs++; console.log(`  ${ROUGE}✗${RAZ} ${titre}${detail ? `${GRIS} — ${detail}${RAZ}` : ""}`) }
}

console.log("\n\x1b[1mUN BLOC ABÎMÉ NE S'AFFICHE PAS EN CLAIR\x1b[0m\n")

// LE CAS RÉEL, copié de la production le 27/08.
const REEL = '{"type":"keyvalue","rows":[["Référence","DV0001054"],["Date","06/11/2025"],' +
             '","Montant","2 092,80 €"],["Statut","Transformé"]]}'
const r = rendu(REEL)
controle("le keyvalue de devis relevé en prod est réparé, pas abandonné",
         r !== null, "lire() rend null : le JSON partirait au rendu markdown")
controle("le bloc réparé garde son type", r && r.type === "keyvalue")
controle("il garde les lignes lisibles d'avant la corruption",
         !!(r && Array.isArray(r.rows) && r.rows.length >= 2 &&
            r.rows[0][1] === "DV0001054"))
controle("rien n'est inventé : aucune ligne au-delà de ce qui était lisible",
         !!(r && r.rows.every((l) => Array.isArray(l) && l.length === 2)))

// LE PIÈGE EXACT : une chaîne qui se termine par un crochet ouvrant.
controle("une chaîne finissant par « [ » ne bloque plus la boucle",
         lire('{"type":"list","items":["a","b"],[') !== null)
controle("une chaîne finissant par « { » non plus",
         lire('{"type":"list","items":["a"],{') !== null)

// Ce qui marchait doit continuer de marcher.
controle("un JSON valide passe tel quel",
         JSON.stringify(lire('{"type":"badge","text":"ok"}')) === '{"type":"badge","text":"ok"}')
const tronque = rendu('{"type":"table","columns":["A","B"],"rows":[["1","2"],["3"')
controle("un JSON coupé net est refermé", tronque !== null && tronque.type === "table")
controle("la ligne incomplète est retirée, pas complétée",
         !!(tronque && tronque.rows.every((l) => l.length === 2)))

// Et ce qui n'est pas réparable doit renoncer, sans boucler.
const debut = Date.now()
controle("un texte qui n'est pas du JSON rend null", lire("{ceci n'est pas du json") === null)
controle("la boucle se termine toujours (pas d'emballement)", Date.now() - debut < 2000,
         `${Date.now() - debut} ms`)

console.log("\n\x1b[1mUN BLOC PEUT PORTER PLUSIEURS COMPOSANTS\x1b[0m\n")

// LE CAS RÉEL, relevé le 20/09 : « affiche-les tous » sur les mails du jour.
// Le modèle avait écrit QUATRE cartes `email` dans UN bloc, une par ligne.
// `lire()` répare en reculant : elle jetait tout sauf la première, et
// l'utilisateur voyait UNE carte sous un texte qui en annonçait quatre.
// Contenu neutralisé, forme exacte (accolades et guillemets dans les extraits).
const GROUPE = 'Les 4 mails reçus aujourd\'hui :\n\n```ui\n' +
  '{"type":"email","subject":"Re: attestations de conformité","from":"APP <contact@exemple-platrerie.fr>",' +
  '"date":"20/09/2026 20:01","preview":"Justificatifs manquants {étude carbone} ; il a écrit \\"bloquant\\" hier."}\n' +
  '{"type":"email","subject":"Nouvelle candidature","from":"candidatures@exemple-emploi.fr","date":"20/09/2026 14:35","preview":"CV joint."}\n' +
  '{"type":"email","subject":"Publicité","from":"contact@exemple-nettoyage.fr","date":"20/09/2026 07:05","preview":"Sans lien avec nos chantiers."}\n' +
  '{"type":"email","subject":"Liste de travail","from":"notification@exemple-portail.gouv.fr","date":"20/09/2026 06:02","preview":"Pour information."}\n' +
  '```\n\nÀ retenir : seul le premier appelle une action.\n\n```ui\n' +
  '{"type":"quick_replies","options":["Réponds à APP","Classe les 4 mails"]}\n```'

const parts = parse(GROUPE)
const ui = parts.filter((p) => p.kind === "ui").map((p) => p.block)
controle("les quatre cartes email s'affichent, pas seulement la première",
         ui.filter((b) => b.type === "email").length === 4,
         `${ui.filter((b) => b.type === "email").length} carte(s) rendue(s)`)
controle("les pastilles de suites restent rendues", ui.some((b) => b.type === "quick_replies"))
controle("l'ordre des cartes est celui du modèle",
         ui[0]?.subject === "Re: attestations de conformité" && ui[3]?.subject === "Liste de travail")
controle("un extrait portant une accolade et des guillemets est intact",
         !!ui[0]?.preview?.includes("{étude carbone}") && !!ui[0]?.preview?.includes('"bloquant"'))
controle("le texte rédigé autour reste à sa place",
         parts.some((p) => p.kind === "text" && p.text.includes("seul le premier appelle une action")))

// Le découpage lui-même.
controle("un objet seul rend un seul morceau",
         decouper('{"type":"badge","text":"ok"}').length === 1)
controle("une accolade DANS une chaîne ne coupe rien",
         decouper('{"t":"un {piège}"}{"u":2}').length === 2)
controle("un guillemet échappé ne ferme pas la chaîne",
         decouper('{"t":"il a dit \\"oui\\""}{"u":2}').length === 2)

// Ce qui marchait doit continuer de marcher.
const seul = 'Voici.\n\n```ui\n{"type":"table","columns":["A"],"rows":[["1"]]}\n```\n\nVoilà.'
const pSeul = parse(seul)
controle("un bloc à un seul objet rend un seul composant",
         pSeul.filter((p) => p.kind === "ui").length === 1)
controle("le texte avant et après est préservé",
         pSeul.filter((p) => p.kind === "text").length === 2)
// Un bloc tranché net par le plafond de sortie : les cartes entières restent,
// et la dernière est réparée comme avant.
const coupe = '```ui\n{"type":"email","subject":"a","from":"x@exemple-sols.fr"}\n' +
              '{"type":"email","subject":"b","from":"y@exemple-sols.fr"}\n' +
              '{"type":"email","subject":"c","fro'
const pCoupe = parse(coupe).filter((p) => p.kind === "ui").map((p) => p.block)
controle("un bloc tranché en plein vol garde les cartes entières",
         pCoupe.length >= 2 && pCoupe[0]?.subject === "a" && pCoupe[1]?.subject === "b",
         `${pCoupe.length} carte(s)`)
// Un objet sans `type` n'est pas un composant : le bloc reste au texte.
const nu = '```ui\n{"a":1}\n{"b":2}\n```'
controle("un bloc d'objets sans `type` reste au texte",
         parse(nu).every((p) => p.kind === "text"))

console.log()
if (echecs) { console.log(`${ROUGE}${echecs} contrôle(s) en échec.${RAZ}`); process.exit(1) }
console.log(`${VERT}Tous les contrôles passent.${RAZ}`)
