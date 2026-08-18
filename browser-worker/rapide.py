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


# PLUSIEURS MOTEURS, PARCE QU'UN SEUL NE TIENT PAS DEPUIS UN SERVEUR.
#
# DuckDuckGo était le seul essayé. Depuis un poste de travail il répond très
# bien ; depuis l'adresse IP d'un hébergeur, il sert très souvent une page de
# vérification à la place des résultats. La recherche rendait alors zéro lien
# SANS erreur — le pire des échecs, celui qui ressemble à « rien à trouver ».
#
# Google n'est pas dans la liste, et c'est un choix : il détecte l'automatisation
# plus agressivement que tous les autres, rend une page de consentement en
# Europe, et change sa structure sans prévenir. Le mettre en tête rendrait la
# recherche instable pour des raisons qu'on ne maîtriserait jamais.
#
# On essaie donc dans l'ordre, et on s'arrête au premier qui rend des liens.
# Chaque moteur a sa page « sans JavaScript », qui rend un document complet et
# se lit sans attendre.
MOTEURS = [
    ("duckduckgo", "https://html.duckduckgo.com/html/?q=", "a.result__url"),
    ("bing",       "https://www.bing.com/search?q=",       "li.b_algo h2 a"),
    ("mojeek",     "https://www.mojeek.com/search?q=",     "a.ob"),
    ("brave",      "https://search.brave.com/search?q=",   "a[href^='http']:has(.snippet-title)"),
]

# Les adresses des moteurs eux-mêmes ne sont pas des résultats : sans ce
# filtre, la première « page trouvée » est la page de recherche suivante.
_MOTEUR_HOTES = ("duckduckgo.com", "bing.com", "mojeek.com", "brave.com",
                 "google.com", "microsoft.com", "msn.com")


async def _liens(navigateur, url: str, selecteur: str, delai_ms: int) -> list[str]:
    """Les adresses de résultats rendues par UN moteur."""
    ctx = await navigateur.new_context(user_agent=AGENT, accept_downloads=False)
    try:
        page = await ctx.new_page()
        await page.route(INUTILES, lambda r: r.abort())
        await page.goto(url, timeout=delai_ms, wait_until="domcontentloaded")
        bruts = await page.evaluate(
            "(sel) => Array.from(document.querySelectorAll(sel))"
            "  .map(e => e.getAttribute('href') || '')"
            "  .filter(h => h.startsWith('http'))", selecteur)
    except Exception as e:  # noqa: BLE001 — un moteur qui refuse n'est pas une panne
        logger.info("Moteur écarté (%s) : %s", url.split("/")[2], type(e).__name__)
        return []
    finally:
        await ctx.close()
    propres, vus = [], set()
    for h in bruts:
        hote = h.split("/")[2].lower() if "//" in h else ""
        if any(m in hote for m in _MOTEUR_HOTES) or h in vus:
            continue
        vus.add(h)
        propres.append(h)
    return propres


async def chercher(requete: str, max_resultats: int = 3,
                   delai_ms: int = 15000) -> dict:
    """Cherche sur le web, puis lit les premiers résultats."""
    from playwright.async_api import async_playwright

    debut = time.monotonic()
    resultats: list[dict] = []
    moteur_retenu = None
    async with async_playwright() as p:
        navigateur = await p.chromium.launch(headless=True, args=ARGS)
        try:
            liens: list[str] = []
            for nom, base, selecteur in MOTEURS:
                liens = await _liens(navigateur, base + quote_plus(requete),
                                     selecteur, delai_ms)
                if liens:
                    moteur_retenu = nom
                    logger.info("Moteur retenu : %s (%d liens)", nom, len(liens))
                    break
                logger.info("Moteur %s : aucun lien, on passe au suivant", nom)

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
        # LE MOTEUR EST DIT. Sans lui, « aucun résultat » ne distingue pas une
        # requête sans réponse d'un web entier qui nous a fermé la porte.
        "moteur": moteur_retenu,
        "error": None if moteur_retenu else "aucun moteur n'a rendu de résultat",
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
