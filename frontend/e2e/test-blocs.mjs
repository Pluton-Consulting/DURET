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
  .replace(/const (\w+)\s*:\s*[\w\[\]|<> ]+\s*=/g, "const $1 =")
  // les lambdas typées : `(l: any) => …`
  .replace(/\((\w+)\s*:\s*[\w\[\]|<> ]+\)\s*=>/g, "($1) =>")

const { fermer, lire, nettoyer } = (new Function(
  sansTypes(extraire("fermer")) + "\n" + sansTypes(extraire("lire")) + "\n" +
  sansTypes(extraire("nettoyer")) +
  "\nreturn { fermer, lire, nettoyer }"))()

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

console.log()
if (echecs) { console.log(`${ROUGE}${echecs} contrôle(s) en échec.${RAZ}`); process.exit(1) }
console.log(`${VERT}Tous les contrôles passent.${RAZ}`)
