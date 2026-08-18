"""
LES DEUX GESTES RAPIDES : CHERCHER, ET OUVRIR UNE PAGE.

Ils pilotent le CHROMIUM SYSTÈME de l'image (`/usr/bin/chromium`), en
sous-processus : `--headless --dump-dom` charge la page, exécute son
JavaScript, et rend le document sérialisé sur la sortie standard.

POURQUOI PAS PLAYWRIGHT : parce qu'il n'est PAS LÀ, et la première version de
ce fichier est morte de l'avoir supposé. browser-use pilote Chromium par sa
propre couche CDP depuis la 0.4 ; l'image `browseruse` n'embarque donc ni
playwright ni patchright. `from playwright.async_api import ...` levait
ModuleNotFoundError, le serveur rendait 500, et le backend traduisait en
« navigateur indisponible » — dès le premier appel, pour toujours. Vérifié
dans l'image : `find_spec('playwright') → None`, mais un Chromium système
bien présent. Un import se vérifie DANS L'IMAGE CIBLE, pas dans le souvenir
qu'on a de la bibliothèque.

CE QUE LE SOUS-PROCESSUS ACHÈTE. Pas de bibliothèque, pas de protocole, pas de
version à marier : un processus par page, qui naît, rend son document et
meurt. Il se borne (`--timeout`), se tue (kill après grâce), et ne laisse
rien derrière lui — le profil jetable part avec son répertoire temporaire.

CE QU'ILS NE SONT PAS. Pas des tâches de l'agent autonome : aucun modèle ne
décide de rien, le parcours est écrit, figé, sans boucle. L'agent autonome
garde son endpoint `/run` et la couche CDP de browser-use.

L'ISOLEMENT VIENT DU CONTENEUR, pas de ce fichier : ces fonctions exécutent le
JavaScript de pages inconnues, et ne tournent que dans le conteneur
navigateur, seul à parler à l'internet et seul contraint pour cela.
"""
from __future__ import annotations

import asyncio
import html as html_
import logging
import re
import shutil
import tempfile
import time
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

logger = logging.getLogger("symbiose.navigateur.rapide")

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or "/usr/bin/chromium"

AGENT = "Mozilla/5.0 (compatible; Symbiose-Agent/1.0)"


def _args(delai_ms: int, profil: str) -> list[str]:
    return [
        # `--headless` nu : depuis Chromium 132 c'est le « nouveau » headless,
        # avant c'est l'ancien — et les DEUX savent `--dump-dom`. `=new`
        # casserait sur les versions récentes qui ne le reconnaissent plus.
        "--headless",
        "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
        "--disable-extensions", "--mute-audio", "--no-first-run",
        "--disable-background-networking",
        # Un profil JETABLE par appel : deux pages qui partageraient un profil
        # partageraient aussi ses cookies. Et Chromium refuse de démarrer sans
        # répertoire inscriptible — le répertoire temporaire est le seul
        # garanti ici (utilisateur non-root).
        f"--user-data-dir={profil}",
        # Ni images ni polices : rien de tout cela ne porte de texte, et chaque
        # octet évité est du temps gagné sur une page lourde.
        "--blink-settings=imagesEnabled=false",
        "--disable-remote-fonts",
        f"--user-agent={AGENT}",
        # Le budget de temps VIRTUEL avance les minuteurs JavaScript : une page
        # qui se dessine après coup se dessine tout de suite. `--timeout` coupe
        # le chargement réel ; la grâce du `wait_for` coupe le processus.
        f"--virtual-time-budget={min(delai_ms, 10000)}",
        f"--timeout={delai_ms}",
        "--dump-dom",
    ]


async def _dump(url: str, delai_ms: int) -> str:
    """Une page → son HTML, JavaScript exécuté. Lève en cas d'échec."""
    with tempfile.TemporaryDirectory(prefix="rapide-") as profil:
        proc = await asyncio.create_subprocess_exec(
            CHROMIUM, *_args(delai_ms, profil), url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            brut, _ = await asyncio.wait_for(
                proc.communicate(), timeout=delai_ms / 1000 + 20)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
    return brut.decode("utf-8", errors="replace")


# ── HTML → texte, sans dépendance ──────────────────────────────────────────
# On retire ce qui se répète d'une page à l'autre — scripts, styles, menus,
# pieds, encarts — parce que ces morceaux consomment le budget du modèle sans
# jamais porter la réponse.
_SANS = re.compile(
    r"<(script|style|nav|footer|header|aside|noscript|iframe|svg|template)\b"
    r".*?</\1\s*>", re.I | re.S)
_BALISES = re.compile(r"<[^>]+>")
_TITRE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
# `(?:https?:)?//` et pas seulement `https?://` : DuckDuckGo écrit ses liens
# de résultats SANS protocole (`//duckduckgo.com/l/?uddg=...`). Le motif
# strict les ignorait tous — le moteur rendait de vrais résultats, et la
# cascade concluait « aucun lien » avant de glisser vers un moteur bloqué.
_LIENS = re.compile(r"""href=["']((?:https?:)?//[^"']+)["']""", re.I)


def _texte(page_html: str) -> str:
    corps = _SANS.sub(" ", page_html)
    texte = html_.unescape(_BALISES.sub(" ", corps))
    texte = re.sub(r"[ \t]{2,}", " ", texte)
    texte = re.sub(r"\s*\n\s*", "\n", texte)
    return texte.strip()[:6000]


# UNE PAGE D'ERREUR N'EST PAS UNE PAGE. Quand l'adresse ne répond pas,
# Chromium dessine sa propre page — « This site can't be reached »,
# DNS_PROBE_..., ERR_... — et `--dump-dom` la sérialise comme n'importe
# quelle autre. Attrapé au premier essai : un domaine introuvable rendait
# `success: true` avec le texte de l'erreur en guise de contenu, que le
# modèle aurait cité comme s'il venait du site. On ne teste le motif que sur
# un texte court : un vrai article qui MENTIONNE un code ERR_ dépasse
# largement cette taille.
_PAGE_ERREUR = re.compile(r"\b(?:ERR_[A-Z_]{3,}|DNS_PROBE_[A-Z_]{3,})\b")


def _est_page_erreur(texte: str) -> bool:
    return len(texte) < 600 and bool(_PAGE_ERREUR.search(texte))


def _titre(page_html: str) -> str | None:
    m = _TITRE.search(page_html)
    return html_.unescape(m.group(1)).strip() if m else None


async def _lire(url: str, delai_ms: int) -> dict:
    page_html = await _dump(url, delai_ms)
    texte = _texte(page_html)
    if _est_page_erreur(texte):
        # Le site n'a pas répondu : contenu vide, pas le texte de l'erreur.
        return {"url": url, "titre": None, "contenu": None}
    return {"url": url, "titre": _titre(page_html), "contenu": texte}


# PLUSIEURS MOTEURS, PARCE QU'UN SEUL NE TIENT PAS DEPUIS UN SERVEUR.
#
# DuckDuckGo répond très bien depuis un poste de travail ; depuis l'adresse IP
# d'un hébergeur, il sert souvent une page de vérification à la place des
# résultats. La recherche rendait alors zéro lien SANS erreur — le pire des
# échecs, celui qui ressemble à « rien à trouver ».
#
# Google n'est pas dans la liste, et c'est un choix : détection d'automatisation
# agressive, page de consentement en Europe, structure mouvante. On essaie dans
# l'ordre, on s'arrête au premier qui rend des liens. Chaque moteur a sa page
# « sans JavaScript », qui rend un document complet et se lit sans attendre.
MOTEURS = [
    ("duckduckgo", "https://html.duckduckgo.com/html/?q="),
    ("bing",       "https://www.bing.com/search?q="),
    ("mojeek",     "https://www.mojeek.com/search?q="),
    ("brave",      "https://search.brave.com/search?q="),
]

# Les adresses des moteurs eux-mêmes ne sont pas des résultats : sans ce
# filtre, la première « page trouvée » est la page de recherche suivante.
# S'y ajoutent les hôtes de leur décor — comptes sociaux, fournisseur de
# captcha — ramassés à l'essai dans de fausses « pages trouvées ».
_MOTEUR_HOTES = ("duckduckgo.com", "bing.com", "mojeek.com", "brave.com",
                 "google.com", "microsoft.com", "msn.com", "qwant.com",
                 "w3.org", "mastodon.social", "altcha.org")

# UN DÉFI ANTI-ROBOT N'EST PAS UNE PAGE DE RÉSULTATS. Depuis une adresse de
# serveur, un moteur sert parfois sa page de vérification à la place des
# résultats ; ses liens à elle (fournisseur du captcha, aide) passaient pour
# des pages trouvées — attrapé à l'essai avec le défi ALTCHA de Mojeek. Un
# moteur qui défie est un moteur qui n'a rien rendu : on passe au suivant.
_PAGE_DEFI = re.compile(
    r"(?i)captcha|altcha|are you (?:a )?human|unusual traffic|"
    r"verify (?:that )?you|êtes[- ]vous un robot")


def _decoder_ddg(h: str) -> str:
    """DuckDuckGo enveloppe ses résultats (`/l/?uddg=<url>`) : on déballe.

    Sans ce déballage, tous ses liens portent l'hôte duckduckgo.com, le filtre
    des moteurs les écarte, et DuckDuckGo rend « aucun lien » à tort — la
    cascade glisse alors vers Bing pour une mauvaise raison.
    """
    if "duckduckgo.com/l/" not in h:
        return h
    try:
        vraie = parse_qs(urlparse(h).query).get("uddg", [""])[0]
        return unquote(vraie) if vraie else h
    except Exception:  # noqa: BLE001
        return h


def _liens(page_html: str) -> list[str]:
    """Les adresses de résultats d'une page de moteur, SANS sélecteur CSS :
    tous les liens sortants, moins les moteurs eux-mêmes. Générique, donc
    robuste au changement de classe qui casserait un sélecteur.

    LE DÉCOR PART D'ABORD. Les résultats ne vivent jamais dans nav, header ou
    footer — mais les comptes sociaux du moteur, si. Attrapé à l'essai : une
    requête sans résultat sur Mojeek rendait son pied de page, et les
    « pages trouvées » étaient ses profils Mastodon et Buttondown.
    """
    propres: list[str] = []
    vus: set[str] = set()
    for h in _LIENS.findall(_SANS.sub(" ", page_html)):
        h = html_.unescape(h)
        if h.startswith("//"):
            h = "https:" + h
        h = _decoder_ddg(h)
        try:
            hote = urlparse(h).netloc.lower()
        except Exception:  # noqa: BLE001
            continue
        if not hote or any(m in hote for m in _MOTEUR_HOTES) or h in vus:
            continue
        vus.add(h)
        propres.append(h)
    return propres


async def chercher(requete: str, max_resultats: int = 3,
                   delai_ms: int = 15000) -> dict:
    """Cherche sur le web, puis lit les premiers résultats."""
    debut = time.monotonic()
    liens: list[str] = []
    moteur_retenu = None
    for nom, base in MOTEURS:
        try:
            page_html = await _dump(base + quote_plus(requete), delai_ms)
        except Exception as e:  # noqa: BLE001 — un moteur qui refuse n'est pas une panne
            logger.info("Moteur écarté (%s) : %s", nom, type(e).__name__)
            continue
        if _PAGE_DEFI.search(page_html):
            logger.info("Moteur %s : page de vérification, on passe au suivant", nom)
            continue
        liens = _liens(page_html)
        if liens:
            moteur_retenu = nom
            logger.info("Moteur retenu : %s (%d liens)", nom, len(liens))
            break
        logger.info("Moteur %s : aucun lien, on passe au suivant", nom)

    # DEUX PAGES DE FRONT, PAS PLUS. Chaque lecture est un Chromium entier ;
    # sous la limite mémoire du conteneur (1500 Mo), trois processus complets
    # risquent le tueur du noyau — et l'échec ressemblerait à une panne.
    porte = asyncio.Semaphore(2)

    async def _une(u: str) -> dict:
        async with porte:
            try:
                return await _lire(u, min(delai_ms, 10000))
            except Exception as e:  # noqa: BLE001
                logger.info("Page ignorée (%s) : %s", u, type(e).__name__)
                return {"url": u, "titre": None, "contenu": None}

    resultats = list(await asyncio.gather(
        *[_une(u) for u in liens[:max_resultats]]))

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
    debut = time.monotonic()
    try:
        page = await _lire(url, delai_ms)
    except Exception as e:  # noqa: BLE001
        # LE MESSAGE RESTE GÉNÉRIQUE. Le détail d'une erreur réseau porte
        # souvent l'adresse visée et parfois l'hôte interne : il n'a rien
        # à faire dans une réponse rendue au modèle.
        logger.warning("Ouverture de page échouée : %s", type(e).__name__)
        return {"success": False, "results": [], "error": type(e).__name__,
                "execution_time_ms": int((time.monotonic() - debut) * 1000)}

    return {
        "success": bool(page.get("contenu")),
        "results": [page],
        "error": None,
        "execution_time_ms": int((time.monotonic() - debut) * 1000),
    }
