/**
 * Banc d'interface — pilote un vrai navigateur sur le chat.
 *
 * Il ne teste QUE ce que l'API ne peut pas prouver : le rendu. La pertinence
 * des réponses, le RAG et les actions se testent bien mieux par
 * `backend/scripts/bench/campagne.py` — dix fois plus vite et sans instabilité.
 * Ici on vérifie qu'un composant s'affiche vraiment au lieu d'un bloc de texte
 * brut, que le markdown devient des éléments, que la vue suit les messages, et
 * que le chemin de réflexion progresse.
 *
 * DEUX MODES.
 *
 * 1. ATTACHÉ (recommandé) — tu ouvres l'application toi-même, tu te connectes,
 *    et le banc reprend CETTE session. Cela résout d'un coup les deux obstacles :
 *    l'accès réseau (ton navigateur sait joindre l'application) et le lien
 *    magique (tu es déjà authentifié). Rien n'est saisi ni stocké côté banc.
 *
 *      npm i --no-save playwright-core
 *      # puis, dans un profil SÉPARÉ — obligatoire depuis Chrome 136, et de
 *      # toute façon souhaitable : le banc ne voit que ce profil-là.
 *      chrome.exe --remote-debugging-port=9222 \
 *                 --user-data-dir="%LOCALAPPDATA%\Temp\chrome-bench" <url-app>
 *      BENCH_CDP=http://localhost:9222 node e2e/interface.mjs
 *
 * 2. AUTONOME — le banc lance son propre navigateur et se connecte via un lien
 *    magique fourni par l'environnement (l'application n'a pas de mot de passe).
 *    Le lien n'est jamais journalisé.
 *
 *      BENCH_URL=http://localhost:3000 \
 *      BENCH_LIEN_MAGIQUE='http://.../verify?token=...&email=...' \
 *      node e2e/interface.mjs
 *
 * Options communes :
 *     BENCH_VISIBLE=1     mode autonome : ouvre une fenêtre visible
 *     BENCH_CAPTURES=1    enregistre une capture par cas dans e2e/captures/
 *     BENCH_LECTURE=1     n'envoie AUCUN message ; vérifie seulement ce qui est
 *                         déjà affiché. Utile pour un premier contact prudent
 *                         sur une instance de production.
 */
import { mkdirSync } from "node:fs"

// playwright-core suffit et ne télécharge aucun navigateur : en mode attaché,
// c'est le navigateur DÉJÀ ouvert qui est piloté.
let chromium
try { ({ chromium } = await import("playwright-core")) }
catch { ({ chromium } = await import("playwright")) }

const CDP = process.env.BENCH_CDP
const LIEN = process.env.BENCH_LIEN_MAGIQUE
const VISIBLE = process.env.BENCH_VISIBLE === "1"
const CAPTURES = process.env.BENCH_CAPTURES === "1"
const LECTURE_SEULE = process.env.BENCH_LECTURE === "1"
const DELAI_REPONSE = 120_000
// Pas `URL` : ce nom masquerait le constructeur global du même nom, dont on se
// sert pour lire l'origine de l'onglet attaché.
let BASE = process.env.BENCH_URL || "http://localhost:3000"

const VERT = "\x1b[92m", ROUGE = "\x1b[91m", GRIS = "\x1b[90m", RAZ = "\x1b[0m"
let ok = 0, ko = 0
const echecs = []

function verdict(libelle, condition, detail = "") {
  if (condition) { ok++; console.log(`  ${VERT}OK${RAZ}   ${libelle}`) }
  else {
    ko++; echecs.push(libelle)
    console.log(`  ${ROUGE}KO${RAZ}   ${libelle}`)
    if (detail) console.log(`       ${GRIS}${String(detail).slice(0, 300)}${RAZ}`)
  }
}

// ── Sélecteurs, avec repli ───────────────────────────────────────────
//
// Les `data-testid` sont récents : une instance pas encore redéployée ne les a
// pas. Chaque accès retombe donc sur un repère STRUCTUREL de l'interface. Le
// repli s'appuie sur l'alignement (les bulles utilisateur sont alignées à
// droite, celles de l'assistant à gauche) plutôt que sur des classes de style,
// qui changent au premier ajustement visuel.

function saisie(page) {
  return page.getByTestId("saisie-message")
    .or(page.locator('textarea[placeholder*="Posez votre question"]')).first()
}

function boutonEnvoyer(page) {
  return page.getByTestId("envoyer-message")
    .or(page.locator("button").filter({ hasText: /^Envoyer$/ })).first()
}

/** Dans la page : retrouve le conteneur défilant et les bulles. */
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
  return {
    zone, bulles,
    nb: bulles.length,
    dernier: bulles.length ? bulles[bulles.length - 1].innerText : "",
    enBas: zone.scrollHeight - zone.scrollTop - zone.clientHeight < 150,
  }
}

async function sonder(page) {
  return page.evaluate(`(${SONDE.toString()})()`).then((r) => r && {
    nb: r.nb, dernier: r.dernier, enBas: r.enBas,
  })
}

/** HTML de la dernière bulle d'assistant — pour distinguer un composant rendu
 *  d'un bloc resté en texte brut. */
async function dernierHtml(page) {
  return page.evaluate(`(() => {
    const r = (${SONDE.toString()})()
    return r && r.bulles.length ? r.bulles[r.bulles.length - 1].innerHTML : ""
  })()`)
}

/** Envoie un message et attend qu'une réponse NOUVELLE soit stabilisée. */
async function demander(page, texte) {
  const avant = (await sonder(page))?.nb ?? 0
  await saisie(page).fill(texte)
  await boutonEnvoyer(page).click()

  const limite = Date.now() + DELAI_REPONSE
  let precedent = -1, stable = 0
  while (Date.now() < limite) {
    await page.waitForTimeout(700)
    const etat = await sonder(page)
    if (!etat || etat.nb <= avant) continue
    const taille = (etat.dernier || "").length
    // La réponse arrive en flux : on la considère finie quand sa longueur ne
    // bouge plus sur deux relevés consécutifs.
    if (taille > 0 && taille === precedent) { if (++stable >= 2) return etat }
    else stable = 0
    precedent = taille
  }
  throw new Error(`aucune réponse stabilisée en ${DELAI_REPONSE / 1000} s`)
}

async function capture(page, nom) {
  if (!CAPTURES) return
  mkdirSync("e2e/captures", { recursive: true })
  await page.screenshot({ path: `e2e/captures/${nom}.png`, fullPage: false })
}

/** Retrouve l'onglet de l'application parmi ceux déjà ouverts. */
async function ongletApplication(navigateur) {
  const pages = navigateur.contexts().flatMap((c) => c.pages())
  if (!pages.length) throw new Error("aucun onglet ouvert dans le navigateur attaché")
  // Priorité à un onglet qui montre déjà le chat, sinon le premier onglet
  // dont l'adresse n'est pas une page interne du navigateur.
  for (const p of pages) {
    if (await saisie(p).count()) return p
  }
  const utile = pages.find((p) => /^https?:/.test(p.url()))
  if (!utile) throw new Error("aucun onglet sur une page web — ouvre l'application d'abord")
  return utile
}

async function main() {
  let navigateur, contexte, page, attache = false

  if (CDP) {
    // Mode attaché : on reprend la session ouverte par l'utilisateur.
    navigateur = await chromium.connectOverCDP(CDP)
    attache = true
    page = await ongletApplication(navigateur)
    BASE = new URL(page.url()).origin
    console.log(`${GRIS}attaché à ${BASE} — onglet : ${page.url()}${RAZ}`)
  } else {
    if (!LIEN) {
      console.error("Ni BENCH_CDP ni BENCH_LIEN_MAGIQUE : aucun moyen de se connecter.")
      process.exit(2)
    }
    navigateur = await chromium.launch({ headless: !VISIBLE })
    contexte = await navigateur.newContext({ viewport: { width: 1440, height: 900 } })
    page = await contexte.newPage()
    await page.goto(LIEN, { waitUntil: "networkidle" })
  }

  try {
    if (!attache || !(await saisie(page).count())) {
      await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" })
    }
    const connecte = await saisie(page).count()
    verdict("session authentifiée sur le chat", connecte > 0,
            attache ? "connecte-toi dans le navigateur, puis relance"
                    : "lien magique expiré ou déjà consommé ?")
    if (!connecte) return

    const marques = await page.locator("[data-testid]").count()
    if (!marques) {
      console.log(`${GRIS}aucun data-testid : instance antérieure au commit qui les `
                  + `ajoute — repli sur les repères structurels.${RAZ}`)
    }

    if (LECTURE_SEULE) {
      const etapes = await page.getByTestId("etape-reflexion")
        .or(page.locator(".sym-node")).count()
      const etat = await sonder(page)
      verdict("chemin de réflexion présent", etapes > 0, `${etapes} étape(s)`)
      verdict("bulles de conversation localisées", !!etat,
              "conteneur de messages introuvable")
      console.log(`${GRIS}lecture seule : ${etat?.nb ?? 0} réponse(s) déjà affichée(s), `
                  + `aucun message envoyé.${RAZ}`)
      if (etat?.dernier) {
        console.log(`${GRIS}dernière réponse : ${etat.dernier.slice(0, 160)}${RAZ}`)
      }
      await capture(page, "00-lecture-seule")
      return
    }

    // ── 1. Conversation courante : pas de hors-sujet ─────────────────
    let etat = await demander(page, "saluut")
    let texte = etat.dernier
    verdict("salutation : réponse non vide", texte.trim().length > 0)
    verdict("salutation : pas de note technique",
            !texte.includes("Limite d'actions"), texte.slice(0, 200))
    verdict("salutation : ne parle pas des documents",
            !/aucun document|m[ée]moire d'entreprise/i.test(texte), texte.slice(0, 200))
    await capture(page, "01-salutation")

    // ── 2. Le chemin de réflexion progresse ──────────────────────────
    const etapes = await page.getByTestId("etape-reflexion")
      .or(page.locator(".sym-node")).count()
    verdict("chemin de réflexion affiché", etapes > 0, `${etapes} étape(s)`)

    // ── 3. Un composant s'affiche VRAIMENT ───────────────────────────
    etat = await demander(page,
      "Mets dans un tableau : Terrassement 1200 m2 a 18 EUR, Plantation 340 unites a 25 EUR.")
    texte = etat.dernier
    let html = await dernierHtml(page)
    verdict("aucun bloc ```ui laissé en texte brut", !/```ui/.test(texte), texte.slice(0, 200))
    // Un composant rendu produit des éléments ; un bloc non interprété n'en
    // produit aucun et laisse le JSON visible dans le texte.
    verdict("le tableau est rendu comme un composant",
            /<table|role="table"|class="[^"]*[Tt]able/.test(html) && !/"type"\s*:/.test(texte),
            texte.slice(0, 220))
    verdict("les chiffres traversent intacts",
            texte.includes("1200") || texte.includes("1 200"), texte.slice(0, 200))
    await capture(page, "02-composant")

    // ── 4. Le markdown devient des éléments, pas des astérisques ─────
    etat = await demander(page,
      "Explique en trois points structures comment preparer une reception de chantier.")
    texte = etat.dernier
    html = await dernierHtml(page)
    verdict("markdown rendu (gras ou liste)",
            /<(strong|b|li)[ >]/.test(html), html.slice(0, 200))
    verdict("pas d'astérisques visibles", !/\*\*/.test(texte), texte.slice(0, 200))
    verdict("pas de tiret cadratin", !/[—–]/.test(texte), texte.slice(0, 200))
    await capture(page, "03-markdown")

    // ── 5. La vue suit les messages ──────────────────────────────────
    verdict("défilement automatique jusqu'au dernier message", etat.enBas,
            "la liste n'est pas au bas après une réponse")

    // ── 6. La conversation survit à un changement d'onglet ───────────
    const avant = etat.nb
    await page.goto(`${BASE}/accueil`, { waitUntil: "networkidle" })
    await page.goto(`${BASE}/chat`, { waitUntil: "networkidle" })
    await page.waitForTimeout(3000)
    const apres = (await sonder(page))?.nb ?? 0
    verdict("la conversation est retrouvée après changement d'onglet",
            apres >= avant, `${avant} message(s) avant, ${apres} après`)
    await capture(page, "04-retour-onglet")

  } finally {
    // En mode attaché, on se contente de se DÉTACHER : le navigateur appartient
    // à l'utilisateur, le banc n'a pas à le fermer sous ses yeux.
    if (attache) await navigateur.close().catch(() => {})
    else await navigateur.close()
  }

  console.log(`\n  ${ok} contrôle(s) OK, ${ko} en échec`)
  if (echecs.length) console.log(`  ${ROUGE}${echecs.join("\n  ")}${RAZ}`)
  process.exit(ko ? 1 : 0)
}

main().catch((e) => { console.error(e); process.exit(2) })
