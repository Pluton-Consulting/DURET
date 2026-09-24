import { chromium } from "playwright-core"
const exe = process.env.CHROME || process.env.HOME + "/Library/Caches/ms-playwright/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
const D = process.argv[2]
const echecs = []
const ok = (nom, cond, detail = "") => { console.log(`  ${cond ? "✓" : "✗"} ${nom}${!cond && detail ? "  → " + detail : ""}`); if (!cond) echecs.push(nom) }
const nav = await chromium.launch({ executablePath: exe, headless: true })
const page = await nav.newPage({ viewport: { width: 1100, height: 900 } })
const erreurs = []
page.on("pageerror", (e) => erreurs.push(String(e)))
await page.goto("file://" + D + "/page.html")
await page.waitForSelector(".sym-bloc-redim")
console.log("── La poignée, sur un tableau de 40 lignes")

const mesure = () => page.evaluate(() => {
  const cadre = document.querySelector(".sym-bloc-redim")
  const table = cadre.querySelector(".sym-bloc-redim-contenu > *")
  const coin = cadre.querySelector(".sym-redim-coin")
  const c = cadre.getBoundingClientRect(), t = table.getBoundingClientRect(), k = coin.getBoundingClientRect()
  const sous = document.elementFromPoint(k.x + k.width / 2, k.y + k.height / 2)
  return { cadre: { w: c.width, h: c.height }, table: { w: t.width, h: t.height, scroll: table.scrollHeight },
           coin: { x: k.x + k.width / 2, y: k.y + k.height / 2, w: k.width, h: k.height, visible: getComputedStyle(coin).display !== "none" },
           coinTouchable: !!sous && sous.classList.contains("sym-redim-coin"),
           redim: cadre.getAttribute("data-redim"), styleW: cadre.style.width, styleH: cadre.style.height,
           curseur: getComputedStyle(coin).cursor }
})

const avant = await mesure()
ok("le tableau a sa largeur commune (620 px) et défile (plafond de hauteur)",
   Math.round(avant.cadre.w) === 620 && avant.table.h < avant.table.scroll, JSON.stringify(avant))
ok("la poignée est visible, au coin bas-droit du cadre, et c'est ELLE qu'on touche à cet endroit (pas le tableau)",
   avant.coin.visible && avant.coin.w >= 16 && avant.coinTouchable, JSON.stringify(avant.coin))
ok("le curseur dit qu'on peut tirer", avant.curseur === "nwse-resize", avant.curseur)
ok("tant qu'on n'a pas tiré : aucune taille en style", avant.redim === "0" && !avant.styleW && !avant.styleH)

// Tirer le coin de 200 px vers la droite et 250 px vers le bas.
await page.mouse.move(avant.coin.x, avant.coin.y)
await page.mouse.down()
await page.mouse.move(avant.coin.x + 200, avant.coin.y + 250, { steps: 10 })
await page.mouse.up()
const apres = await mesure()
ok("le cadre a grandi en largeur (+200) et en hauteur (+250)",
   Math.abs(apres.cadre.w - avant.cadre.w - 200) <= 2 && Math.abs(apres.cadre.h - avant.cadre.h - 250) <= 2,
   JSON.stringify({ avant: avant.cadre, apres: apres.cadre }))
ok("le tableau SUIT le cadre (sa hauteur maximale a cédé : on voit plus de lignes)",
   Math.abs(apres.table.h - apres.cadre.h) <= 2 && apres.table.h > avant.table.h + 200, JSON.stringify(apres.table))
ok("état « redimensionné » posé, la poignée reste au coin et touchable",
   apres.redim === "1" && apres.coinTouchable && Math.abs(apres.coin.x - (avant.coin.x + 200)) <= 2)

// Jamais plus large que la colonne (900 px de colonne, 12 px de marge de chaque côté).
await page.mouse.move(apres.coin.x, apres.coin.y)
await page.mouse.down()
await page.mouse.move(apres.coin.x + 900, apres.coin.y, { steps: 6 })
await page.mouse.up()
const large = await mesure()
const colonne = await page.evaluate(() => document.querySelector(".sym-in").getBoundingClientRect().width)
ok("tiré au-delà de l'écran : borné à la largeur de la colonne", Math.abs(large.cadre.w - colonne) <= 2, `${large.cadre.w} vs ${colonne}`)

// Trop petit : 220 × 48 au moins.
await page.mouse.move(large.coin.x, large.coin.y)
await page.mouse.down()
await page.mouse.move(large.coin.x - 2000, large.coin.y - 2000, { steps: 6 })
await page.mouse.up()
const petit = await mesure()
ok("tiré vers l'intérieur : jamais sous 220 × 48", Math.round(petit.cadre.w) === 220 && Math.round(petit.cadre.h) === 48, JSON.stringify(petit.cadre))

// Double-clic : taille d'origine.
await page.mouse.dblclick(petit.coin.x, petit.coin.y)
const retour = await mesure()
ok("double-clic sur le coin : taille d'origine, état remis",
   Math.round(retour.cadre.w) === 620 && retour.redim === "0" && !retour.styleW && !retour.styleH, JSON.stringify(retour))

console.log("── Au téléphone")
await page.setViewportSize({ width: 390, height: 800 })
await page.waitForTimeout(100)
const tel = await mesure()
ok("pas de poignée (display: none), le bloc prend toute la largeur", !tel.coin.visible && tel.cadre.w <= 390)
ok("aucune erreur JavaScript", erreurs.length === 0, erreurs.join(" | "))
await nav.close()
console.log(echecs.length ? `\n✗ ${echecs.length} échec(s)` : "\n✓ 0 échec")
process.exit(echecs.length ? 1 : 0)
