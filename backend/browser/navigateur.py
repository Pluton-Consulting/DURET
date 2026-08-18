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
    """Contrat inchangé : `browser/tools.py` lisait déjà cette forme."""
    success: bool
    results: list[dict] = field(default_factory=list)
    error: str | None = None
    execution_time_ms: int = 0
    sandbox_type: str = "conteneur-navigateur"


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
            # Le délai côté client dépasse celui demandé au conteneur : sans
            # cette marge, on couperait la connexion pendant qu'il rédige
            # exactement la réponse qu'on attend.
            async with httpx.AsyncClient(timeout=delai_s + 15) as client:
                r = await client.post(url, json=charge)
                r.raise_for_status()
                d = r.json()
        except httpx.HTTPError as e:
            # LE MESSAGE RESTE GÉNÉRIQUE : le détail porte l'adresse interne du
            # conteneur, qui n'a rien à faire dans un contexte rendu au modèle.
            logger.warning("Conteneur navigateur injoignable (%s)", type(e).__name__)
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
