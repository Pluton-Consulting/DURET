"""
LES DEUX GESTES RAPIDES : CHERCHER, ET OUVRIR UNE PAGE.

Ils vivaient dans un bac à sable Daytona — un service tiers, dans le nuage,
créé et détruit à chaque appel. Trois raisons de les ramener ici :

  1. LA CLÉ MANQUAIT EN PRODUCTION. `DAYTONA_API_KEY` est absente de
     `prod.env` : sur le VPS, la recherche web échouait en silence, et les
     agents dégradaient sans que rien ne le dise.
  2. LE CONTENU SORTAIT DE LA MAISON. Chaque page lue transitait par
     l'infrastructure d'un tiers, y compris les requêtes qui portaient le nom
     d'un client.
  3. LE SCRIPT SE RÉINSTALLAIT À CHAUD. Faute de Playwright dans l'image
     `python:3.12-slim`, le script commençait par un `pip install` et un
     téléchargement de Chromium — à chaque appel. Ici, Chromium est déjà là :
     c'est l'image `browseruse`.

CE QU'ILS NE SONT PAS. Ce ne sont pas des tâches de l'agent autonome. Aucun
modèle ne décide de rien : le parcours est écrit, figé, sans boucle. C'est
précisément ce qui les rend rapides — et vérifiables. L'agent autonome, lui,
garde son endpoint `/run`.

L'ISOLEMENT VIENT DU CONTENEUR, pas de ce fichier. Ces fonctions ouvrent des
pages inconnues et exécutent leur JavaScript : elles tournent dans le conteneur
navigateur, qui est le seul du montage à parler à l'internet, et le seul à être
contraint pour cela.
"""
from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import quote_plus

logger = logging.getLogger("symbiose.navigateur.rapide")

# Ce qu'on refuse de télécharger : rien de tout cela ne porte de texte, et
# chaque octet évité est du temps gagné sur une page lourde.
INUTILES = "**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,mp4,mp3,avi,pdf}"

AGENT = "Mozilla/5.0 (compatible; Symbiose-Agent/1.0)"

# Un navigateur qui n'affiche rien n'a besoin ni de GPU ni de son. `--no-sandbox`
# est imposé par l'exécution en conteneur (browser-use le pose déjà de son côté).
ARGS = [
    "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    "--disable-extensions", "--mute-audio", "--no-first-run",
]

# LE TEXTE D'UNE PAGE, SANS SON DÉCOR. On retire ce qui se répète d'une page à
# l'autre — menus, pieds, encarts — parce que ces morceaux consomment le budget
# du modèle sans jamais porter la réponse.
EXTRAIRE = """
    () => {
        ["script","style","nav","footer","header","aside","iframe","noscript"]
            .forEach(t => document.querySelectorAll(t).forEach(e => e.remove()));
        return (document.body.innerText || "")
            .replace(/\\n{3,}/g, "\\n\\n")
            .replace(/[ \\t]{2,}/g, " ")
            .trim()
            .slice(0, 6000);
    }
"""


async def _lire(navigateur, url: str, delai_ms: int) -> dict:
    """Ouvre une page dans un contexte NEUF et en rend le texte.

    Un contexte par page, jamais réutilisé : deux pages qui partageraient le
    même contexte partageraient aussi ses cookies. Une page malveillante
    lirait alors ce qu'une autre a déposé.
    """
    ctx = await navigateur.new_context(user_agent=AGENT, accept_downloads=False)
    try:
        page = await ctx.new_page()
        await page.route(INUTILES, lambda r: r.abort())
        await page.goto(url, timeout=delai_ms, wait_until="domcontentloaded")
        return {"url": page.url, "titre": await page.title(),
                "contenu": await page.evaluate(EXTRAIRE)}
    finally:
        await ctx.close()


async def chercher(requete: str, max_resultats: int = 3,
                   delai_ms: int = 15000) -> dict:
    """Cherche sur DuckDuckGo, puis lit les premiers résultats."""
    from playwright.async_api import async_playwright

    debut = time.monotonic()
    resultats: list[dict] = []
    async with async_playwright() as p:
        navigateur = await p.chromium.launch(headless=True, args=ARGS)
        try:
            # La version « html » de DuckDuckGo ne dépend d'aucun JavaScript :
            # elle rend un document complet, donc lisible sans attendre.
            adresse = "https://html.duckduckgo.com/html/?q=" + quote_plus(requete)
            ctx = await navigateur.new_context(user_agent=AGENT, accept_downloads=False)
            try:
                page = await ctx.new_page()
                await page.route(INUTILES, lambda r: r.abort())
                await page.goto(adresse, timeout=delai_ms, wait_until="domcontentloaded")
                liens = await page.evaluate("""
                    () => {
                        const out = [];
                        document.querySelectorAll("a.result__url").forEach(el => {
                            const h = el.getAttribute("href") || "";
                            if (h.startsWith("http")) out.push(h);
                        });
                        return out;
                    }
                """)
            finally:
                await ctx.close()

            # LES PAGES SE LISENT DE FRONT. Trois pages à la suite, c'est trois
            # fois l'attente réseau ; ensemble, c'est celle de la plus lente.
            # `return_exceptions` : une page qui refuse ne doit pas emporter
            # les autres — c'est fréquent, et ce n'est pas une panne.
            lots = await asyncio.gather(
                *[_lire(navigateur, u, 10000) for u in liens[:max_resultats]],
                return_exceptions=True)
            for url, r in zip(liens[:max_resultats], lots):
                if isinstance(r, BaseException):
                    logger.info("Page ignorée (%s) : %s", url, type(r).__name__)
                    resultats.append({"url": url, "titre": None, "contenu": None})
                else:
                    resultats.append(r)
        finally:
            await navigateur.close()

    return {
        "success": any(r.get("contenu") for r in resultats),
        "results": resultats,
        "error": None,
        "execution_time_ms": int((time.monotonic() - debut) * 1000),
    }


async def ouvrir(url: str, delai_ms: int = 15000) -> dict:
    """Ouvre UNE page et en rend le texte."""
    from playwright.async_api import async_playwright

    debut = time.monotonic()
    async with async_playwright() as p:
        navigateur = await p.chromium.launch(headless=True, args=ARGS)
        try:
            page = await _lire(navigateur, url, delai_ms)
        except Exception as e:  # noqa: BLE001
            # LE MESSAGE RESTE GÉNÉRIQUE. Le détail d'une erreur réseau porte
            # souvent l'adresse visée et parfois l'hôte interne : il n'a rien
            # à faire dans une réponse rendue au modèle.
            logger.warning("Ouverture de page échouée : %s", type(e).__name__)
            return {"success": False, "results": [], "error": type(e).__name__,
                    "execution_time_ms": int((time.monotonic() - debut) * 1000)}
        finally:
            await navigateur.close()

    return {
        "success": bool(page.get("contenu")),
        "results": [page],
        "error": None,
        "execution_time_ms": int((time.monotonic() - debut) * 1000),
    }
