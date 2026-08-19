"""
Le client du CONTENEUR NAVIGATEUR, pour les deux gestes rapides.

Il remplace `daytona_browser`, qui déléguait la navigation à un bac à sable
d'un service tiers. Trois raisons de l'avoir retiré :

  1. LA CLÉ MANQUAIT EN PRODUCTION. `DAYTONA_API_KEY` était absente de
     `prod.env` : sur le VPS, toute recherche web échouait en silence, et les
     trois agents dégradaient sans que rien ne le signale.
  2. LE CONTENU SORTAIT DE LA MAISON. Chaque page lue transitait par
     l'infrastructure d'un tiers, requêtes comprises.
  3. LE SCRIPT SE RÉINSTALLAIT À CHAUD. Le bac à sable partait d'une image
     Python nue : chaque appel commençait par installer Playwright et
     télécharger Chromium.

CE QUE LE BACKEND NE FAIT PLUS. Il n'ouvre aucune page, n'exécute aucun
JavaScript, ne touche à aucun navigateur. Il envoie une requête HTTP au
conteneur navigateur, sur le réseau interne, et lit une réponse. Tout ce qui
vient d'un site inconnu est manipulé là-bas, dans le seul conteneur du montage
qui soit contraint pour cela.

L'INTERRUPTEUR EST RESPECTÉ ICI. `browser_enabled` à false, et rien ne part :
inutile d'attendre le refus du conteneur, ni de le déranger.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from config import settings

logger = logging.getLogger("symbiose.navigateur")


@dataclass
class BrowserResult:
    """La forme que `browser/tools.py` attend. TOUS les champs, pas seulement
    ceux dont je me servais.

    `was_filtered` MANQUAIT, et l'oubli a tout emporté. `fetch_url` le lit à
    deux endroits : l'attribut absent levait un AttributeError, l'exécuteur le
    transformait en « ERREUR : object has no attribute was_filtered », et le
    modèle, qui ne pouvait pas savoir, annonçait un « incident technique » puis
    « le navigateur est indisponible ». Le conteneur, lui, allait très bien.

    Relevé en production : quatre tentatives d'affilée sur la même page, toutes
    tombées au même endroit. Un contrat de données réécrit à la main doit être
    comparé À CELUI QU'ON REMPLACE, champ par champ — pas à l'usage qu'on croit
    en connaître.
    """
    success: bool
    results: list[dict] = field(default_factory=list)
    error: str | None = None
    execution_time_ms: int = 0
    sandbox_type: str = "conteneur-navigateur"
    # Une adresse a-t-elle été écartée par le garde de sécurité ? Remonte
    # jusqu'à l'écran, qui le dit à l'utilisateur : sans cela, une réponse
    # incomplète passe pour une réponse vide.
    was_filtered: bool = False


class ClientNavigateur:
    """Parle au conteneur navigateur. Ne lève jamais : rend un échec propre."""

    async def _appeler(self, chemin: str, charge: dict[str, Any],
                       delai_s: float) -> BrowserResult:
        if not settings.browser_enabled:
            # Refus NET, pas une panne : c'est une décision d'exploitation, et
            # le message doit permettre de la reconnaître comme telle.
            return BrowserResult(success=False,
                                 error="navigation désactivée sur ce déploiement")
        url = settings.browser_worker_url.rstrip("/") + chemin
        try:
            # LA MARGE COUVRE LE DÉMARRAGE DE CHROMIUM, pas seulement la page.
            # `delai_s` borne le chargement d'UNE page ; s'y ajoutent le
            # lancement du navigateur — dix à vingt secondes à froid, davantage
            # sous pression mémoire — et la fermeture. Une marge de quinze
            # secondes coupait donc la connexion pendant que le conteneur
            # travaillait encore, et l'échec ressemblait à une panne.
            async with httpx.AsyncClient(timeout=delai_s + 60) as client:
                r = await client.post(url, json=charge)
                r.raise_for_status()
                d = r.json()
        except httpx.HTTPStatusError as e:
            # LE CODE HTTP EST LA MOITIÉ DU DIAGNOSTIC, et il partait à la
            # poubelle : « navigateur indisponible » couvrait aussi bien un
            # conteneur arrêté qu'un 404 — c'est-à-dire un conteneur VIVANT
            # mais construit sur une image d'avant, qui n'a pas encore la
            # route qu'on appelle. Deux pannes, deux remèdes opposés (le
            # démarrer / le reconstruire), un seul message : introuvable.
            logger.warning("Conteneur navigateur : HTTP %s sur %s — s'il rend "
                           "404, son image date d'avant cette route : "
                           "reconstruire browser-worker",
                           e.response.status_code, chemin)
            return BrowserResult(success=False, error="navigateur indisponible")
        except httpx.HTTPError as e:
            # LE MESSAGE RESTE GÉNÉRIQUE : le détail porte l'adresse interne du
            # conteneur, qui n'a rien à faire dans un contexte rendu au modèle.
            logger.warning("Conteneur navigateur injoignable (%s sur %s)",
                           type(e).__name__, chemin)
            return BrowserResult(success=False, error="navigateur indisponible")
        except Exception as e:  # noqa: BLE001
            logger.warning("Réponse du navigateur illisible : %s", type(e).__name__)
            return BrowserResult(success=False, error="réponse illisible")

        # Le conteneur nomme ses champs en français ; les appelants attendent
        # la forme d'origine. La traduction se fait ICI, à la frontière, pour
        # qu'aucun des deux côtés n'ait à connaître le vocabulaire de l'autre.
        resultats = [
            {"url": r.get("url"), "title": r.get("titre"), "content": r.get("contenu")}
            for r in (d.get("results") or [])
        ]
        # L'APERÇU NE VA PAS AU MODÈLE. Il est rangé ici, côté backend, sous
        # une clé ; le résultat ne porte que cette clé. L'écran la rend en
        # image via `/api/browser/apercu/{cle}` ; le modèle, lui, reçoit une
        # ligne de texte — jamais des kilooctets de base64.
        for r in resultats:
            png = d.get("apercu_b64")
            if png and r.get("url"):
                from browser.apercus import deposer
                r["apercu"] = deposer(r["url"], png)
        return BrowserResult(
            success=bool(d.get("success")),
            results=resultats,
            error=d.get("error"),
            execution_time_ms=int(d.get("execution_time_ms") or 0),
        )

    async def run_search(self, query: str, max_results: int = 3) -> BrowserResult:
        delai = settings.browser_timeout_ms / 1000
        return await self._appeler(
            "/chercher",
            {"requete": query, "max_resultats": max_results,
             "delai_ms": settings.browser_timeout_ms},
            # Chercher, c'est ouvrir une page de résultats PUIS plusieurs pages.
            # Le délai unitaire ne suffit donc pas à borner l'ensemble.
            delai_s=delai * (max_results + 1),
        )

    async def run_fetch(self, url: str) -> BrowserResult:
        delai = settings.browser_timeout_ms / 1000
        return await self._appeler(
            "/ouvrir", {"url": url, "delai_ms": settings.browser_timeout_ms},
            delai_s=delai,
        )


navigateur = ClientNavigateur()
