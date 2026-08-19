/**
 * Banc de RECETTE — joue le cahier des charges dans un vrai navigateur.
 *
 * Différence avec les deux bancs existants, et raison d'être de celui-ci :
 *   * `backend/scripts/bench/campagne.py` appelle le graphe DANS le conteneur.
 *     Rapide et stable, mais il ne prouve rien de la chaîne réelle : ni nginx,
 *     ni l'authentification, ni le rendu, ni le cloisonnement appliqué à un
 *     utilisateur connecté.
 *   * `e2e/interface.mjs` pilote le navigateur mais ne juge que le RENDU.
 *
 * Ici on juge le FOND, vu par l'utilisateur, à travers toute la chaîne. C'est
 * le seul niveau où « l'application répond-elle au cahier des charges » a un
 * sens vérifiable. Le brief est dans `BRIEF.md` ; chaque question cite sa
 * section (`reference`).
 *
 * MODE ATTACHÉ UNIQUEMENT. On reprend une session déjà ouverte : c'est ce qui
 * évite d'avoir à manipuler un lien magique, et ce qui garantit qu'on teste
 * exactement les droits d'un vrai compte. Rien n'est saisi ni stocké ici.
 *
 *   chrome.exe --remote-debugging-port=9222 \
 *              --user-data-dir="%LOCALAPPDATA%\Temp\chrome-bench" <url-app>
 *   BENCH_CDP=http://localhost:9222 node e2e/recette.mjs [--serie X] [--limite N] [--id X]
 *
 * CE QUI EST NOTÉ. Chaque question porte des contrôles DURS, écrits à l'avance
 * et sans modèle : présence ou absence de termes, longueur plancher, jetons de
 * masquage qui ne doivent pas fuir, aveu d'ignorance attendu, éléments HTML
 * attendus dans le rendu. Un contrôle dur qui tombe est un fait, pas une
 * opinion — c'est sur eux seuls que repose le verdict. Ce qu'aucune règle ne
 * sait voir est signalé « à lire », jamais compté comme réussite.
 *
 * TROIS FORMES D'ENTRÉE, parce que le brief ne se joue pas qu'en questions :
 *   * une QUESTION posée dans le chat (le cas général) ;
 *   * une PAGE à ouvrir (`page`), pour les tableaux de bord et la gouvernance
 *     du §15 — on juge ce que l'écran montre, pas ce que le modèle dit ;
 *   * une question avec PIÈCE JOINTE (`piece_jointe`), pour l'agent 2 du §6.
 * `nouvelle_conversation` repart d'un fil vierge : c'est ce qui permet de
 * juger la mémoire d'une conversation (§5) sans que la précédente déteigne.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { chromium } from "playwright-core"

const CDP = process.env.BENCH_CDP || "http://localhost:9222"
const DELAI_REPONSE = Number(process.env.BENCH_DELAI || 240_000)
const PAUSE = Number(process.env.BENCH_PAUSE || 2500)

const args = process.argv.slice(2)
const opt = (nom) => { const i = args.indexOf(nom); return i >= 0 ? args[i + 1] : null }
const SERIE = opt("--serie")
const ID = opt("--id")
const LIMITE = Number(opt("--limite") || 0)
const DEPUIS = opt("--depuis")

const VERT = "\x1b[92m", ROUGE = "\x1b[91m", JAUNE = "\x1b[93m", GRIS = "\x1b[90m", RAZ = "\x1b[0m"

// ── Interaction avec le chat (sélecteurs éprouvés par interface.mjs) ──
function saisie(page) {
  return page.getByTestId("saisie-message")
    .or(page.locator('textarea[placeholder*="Posez votre question"]')).first()
}
function boutonEnvoyer(page) {
  return page.getByTestId("envoyer-message")
    .or(page.locator("button").filter({ hasText: /^Envoyer$/ })).first()
}

const SONDE = () => {
  const zone = document.querySelector('[data-testid="liste-messages"]')
    || [...document.querySelectorAll("div")].find((d) => {
      const s = getComputedStyle(d)
      return s.overflowY === "auto" && d.scrollHeight > 0
        && d.querySelector("div") && d.clientHeight > 200
    })
  if (!zone) return null
  const marques = [...zone.querySelectorAll('[data-testid="message-assistant"]')]
  const bulles = marques.length ? marques : [...zone.children].filter(
    (e) => getComputedStyle(e).alignSelf === "flex-start" && e.innerText.trim())
  const dernier = bulles.length ? bulles[bulles.length - 1] : null
  return {
    nb: bulles.length,
    dernier: dernier ? dernier.innerText : "",
    // « en attente » : la bulle tient la place d'une réponse qui n'est pas là.
    enAttente: !!(dernier && dernier.getAttribute("data-en-attente") === "oui"),
    html: dernier ? dernier.innerHTML : "",
  }
}

async function sonder(page) {
  return page.evaluate(`(${SONDE.toString()})()`)
}

/** Envoie une question et rend la réponse, une fois le flux stabilisé. */
async function demander(page, texte, pieceJointe) {
  const avant = (await sonder(page))?.nb ?? 0
  if (pieceJointe) {
    const chemin = fileURLToPath(new URL(`./${pieceJointe}`, import.meta.url))
    if (!existsSync(chemin)) throw new Error(`pièce jointe introuvable : ${pieceJointe}`)
    await page.locator('input[type="file"]').first().setInputFiles(chemin)
    await page.waitForTimeout(600)
  }
  await saisie(page).fill(texte)
  await boutonEnvoyer(page).click()
  const debut = Date.now()
  const limite = debut + DELAI_REPONSE
  let precedent = -1, stable = 0
  while (Date.now() < limite) {
    await page.waitForTimeout(700)
    const etat = await sonder(page)
    if (!etat || etat.nb <= avant) continue
    // La bulle d'attente n'est pas une réponse : on attend qu'elle se remplisse.
    if (etat.enAttente) { precedent = -1; stable = 0; continue }
    const taille = (etat.dernier || "").length
    if (taille > 0 && taille === precedent) {
      if (++stable >= 2) return { texte: etat.dernier, html: etat.html, ms: Date.now() - debut }
    } else stable = 0
    precedent = taille
  }
  throw new Error(`aucune réponse stabilisée en ${DELAI_REPONSE / 1000} s`)
}

/** Repart d'un fil vierge : on oublie le fil mémorisé et on recharge. */
async function nouvelleConversation(page, base) {
  await page.evaluate(() => {
    for (const k of Object.keys(localStorage))
      if (k.startsWith("symbiose_thread_id") || k.startsWith("duret_thread_id")) localStorage.removeItem(k)
  })
  await page.goto(`${base}/chat`, { waitUntil: "networkidle" })
  await page.waitForTimeout(1500)
}

/** Ouvre une page de l'application et rend ce qu'elle montre. */
async function ouvrirPage(page, base, chemin) {
  const debut = Date.now()
  await page.goto(`${base}${chemin}`, { waitUntil: "networkidle" })
  await page.waitForTimeout(2500)
  const etat = await page.evaluate(() => ({
    texte: document.body.innerText, html: document.body.innerHTML, url: location.href,
  }))
  return { ...etat, ms: Date.now() - debut }
}

// ── Contrôles durs ────────────────────────────────────────────────────
const sansAccent = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()

// Un aveu d'ignorance est une BONNE réponse quand la donnée manque : le cahier
// des charges l'exige (§5 « il ne doit pas inventer d'information »).
const AVEUX = ["je n'ai pas", "je ne trouve", "aucun", "aucune", "pas d'information",
  "pas trouve", "n'ai rien", "ne dispose pas", "a completer", "[a completer]",
  "n'existe pas", "pas de donnee", "introuvable", "ne figure pas", "pas dans"]

function controler(reponse, q) {
  const brut = reponse.texte || ""
  const html = reponse.html || ""
  const plat = sansAccent(brut)
  const echecs = []

  if (q.min_caracteres && brut.trim().length < q.min_caracteres)
    echecs.push(`réponse trop courte (${brut.trim().length} < ${q.min_caracteres})`)

  for (const t of q.doit_contenir || [])
    if (!plat.includes(sansAccent(t))) echecs.push(`manque « ${t} »`)

  for (const t of q.ne_doit_pas_contenir || [])
    if (plat.includes(sansAccent(t))) echecs.push(`contient « ${t} » (interdit)`)

  // Un de ces termes suffit : utile quand plusieurs formulations conviennent.
  if (q.au_moins_un && !q.au_moins_un.some((t) => plat.includes(sansAccent(t))))
    echecs.push(`aucun de : ${q.au_moins_un.join(", ")}`)
  // Un second lot indépendant, quand deux choses distinctes doivent chacune
  // apparaître sous une forme ou une autre (la source ET le sujet, par exemple).
  if (q.au_moins_un_2 && !q.au_moins_un_2.some((t) => plat.includes(sansAccent(t))))
    echecs.push(`aucun de : ${q.au_moins_un_2.join(", ")}`)

  if (q.doit_avouer && !AVEUX.some((a) => plat.includes(a)))
    echecs.push("devait admettre ne pas savoir, ne l'a pas fait")

  // Le RENDU, pas seulement le texte : un composant se reconnaît à ses
  // éléments, une délégation à sa mention, un markdown à ses balises.
  if (q.dom_regex && !new RegExp(q.dom_regex, "i").test(html))
    echecs.push(`rendu attendu absent (/${q.dom_regex}/)`)
  if (q.dom_interdit && new RegExp(q.dom_interdit, "i").test(html))
    echecs.push(`rendu interdit présent (/${q.dom_interdit}/)`)

  // Les jetons de masquage ne doivent JAMAIS atteindre l'écran : leur présence
  // signifie que la réhydratation a échoué et que l'utilisateur lit du balisage.
  const fuite = brut.match(/\[(PER|ORG|LOC|MAIL|TEL|MONTANT|IBAN|SIRET)_\d+\]/g)
  if (fuite) echecs.push(`jetons de masquage visibles : ${[...new Set(fuite)].join(" ")}`)

  if (/```(action|ui)\b/.test(brut)) echecs.push("bloc technique brut affiché")
  if (/<\/?(longcat_tool_call|tool_call|function_call)/i.test(brut))
    echecs.push("balisage d'outil visible")
  // Le markdown doit être RENDU : des astérisques doubles visibles à l'écran
  // signent un texte affiché brut, quel que soit l'endroit.
  if (!q.page && /\*\*[^*\n]{2,}\*\*/.test(brut)) echecs.push("astérisques de markdown visibles")
  // Une réponse qui commence par une excuse technique n'est pas une réponse.
  if (/traceback|exception|error:|internal server|attributeerror|typeerror/i.test(brut))
    echecs.push("trace technique visible")

  if (q.max_secondes && reponse.ms > q.max_secondes * 1000)
    echecs.push(`trop lent (${(reponse.ms / 1000).toFixed(0)} s > ${q.max_secondes} s)`)

  return echecs
}

// ── Exécution ─────────────────────────────────────────────────────────
async function ongletApplication(navigateur) {
  for (const ctx of navigateur.contexts())
    for (const page of ctx.pages()) {
      const u = page.url()
      if (u.startsWith("http") && !u.includes("/login")) return page
    }
  throw new Error("aucun onglet applicatif connecté trouvé")
}

async function main() {
  const series = JSON.parse(readFileSync(new URL("./recette.json", import.meta.url), "utf8"))
  let questions = series.questions
  if (SERIE) questions = questions.filter((q) => q.serie === SERIE)
  if (ID) questions = questions.filter((q) => q.id === ID)
  if (DEPUIS) { const i = questions.findIndex((q) => q.id === DEPUIS); if (i >= 0) questions = questions.slice(i) }
  if (LIMITE) questions = questions.slice(0, LIMITE)
  if (!questions.length) { console.error("aucune question à jouer"); process.exit(2) }

  const navigateur = await chromium.connectOverCDP(CDP)
  const page = await ongletApplication(navigateur)
  const base = new URL(page.url()).origin
  console.log(`${GRIS}Onglet : ${page.url()}${RAZ}`)
  console.log(`${GRIS}${questions.length} entrée(s)${RAZ}\n`)

  const resultats = []
  let reussi = 0, rate = 0

  for (const [i, q] of questions.entries()) {
    const rang = `${String(i + 1).padStart(3)}/${questions.length}`
    const libelle = q.page ? `page ${q.page}` : q.question
    process.stdout.write(`${GRIS}${rang} [${q.serie}] ${q.id} — ${libelle.slice(0, 60)}…${RAZ}\n`)
    let reponse, echecs
    try {
      if (q.page) {
        reponse = await ouvrirPage(page, base, q.page)
      } else {
        // On revient sur le chat si une page l'a quitté.
        if (!page.url().includes("/chat")) {
          await page.goto(`${base}/chat`, { waitUntil: "networkidle" })
          await page.waitForTimeout(1500)
        }
        if (q.nouvelle_conversation) await nouvelleConversation(page, base)
        reponse = await demander(page, q.question, q.piece_jointe)
      }
      echecs = controler(reponse, q)
    } catch (e) {
      reponse = { texte: "", html: "", ms: 0 }
      echecs = [`aucune réponse : ${e.message}`]
    }
    if (echecs.length) {
      rate++
      console.log(`     ${ROUGE}ÉCHEC${RAZ} ${echecs.join(" · ")}`)
      console.log(`     ${GRIS}${(reponse.texte || "").replace(/\s+/g, " ").slice(0, 240)}${RAZ}`)
    } else {
      reussi++
      console.log(`     ${VERT}ok${RAZ} ${GRIS}${(reponse.ms / 1000).toFixed(1)} s${RAZ}`)
      if (q.a_lire)
        console.log(`     ${JAUNE}à lire${RAZ} ${GRIS}${(reponse.texte || "").replace(/\s+/g, " ").slice(0, 200)}${RAZ}`)
    }
    resultats.push({ ...q, reponse: (reponse.texte || "").slice(0, 4000), ms: reponse.ms, echecs })
    await page.waitForTimeout(PAUSE)
  }

  mkdirSync(new URL("./resultats", import.meta.url), { recursive: true })
  const suffixe = SERIE ? `-${SERIE}` : ID ? `-${ID}` : ""
  const chemin = new URL(`./resultats/recette-${series.version}${suffixe}.json`, import.meta.url)
  writeFileSync(chemin, JSON.stringify({ questions: resultats }, null, 2), "utf8")

  console.log(`\n${reussi} réussi(s) / ${rate} échec(s) sur ${questions.length}`)
  console.log(`${GRIS}Détail : ${chemin.pathname}${RAZ}`)
  await navigateur.close().catch(() => {})
  process.exit(rate ? 1 : 0)
}

main().catch((e) => { console.error(`${ROUGE}${e.stack || e.message}${RAZ}`); process.exit(2) })
