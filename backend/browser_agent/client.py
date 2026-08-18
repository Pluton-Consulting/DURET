"""
Client HTTP (non bloquant) vers le worker navigateur interne.

Le backend ne fait que déclencher/annuler des tâches ; le suivi se lit directement
en base (`browser_tasks`). Aucune dépendance à Playwright côté backend.
"""
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger("symbiose.browser.client")


class NavigateurCoupe(RuntimeError):
    """Le navigateur est hors service, volontairement ou non.

    UN TYPE À PART, et non une erreur HTTP brute : couper le navigateur est une
    décision d'exploitation parfaitement normale — un doute sur un site, une
    reprise en main pendant un incident. Ce n'est pas une panne, et l'écran ne
    doit pas l'annoncer comme telle. L'appelant peut ainsi le dire simplement.
    """


async def start_task(job_id: str, task_prompt: str, allowed_domains: list[str],
                     user_id: str, ingest: bool = False, readonly: bool = True,
                     output_schema: Optional[dict] = None) -> dict:
    # DEUX FAÇONS DE COUPER, ET LES DEUX SONT PRÉVUES ICI.
    #
    # L'INTERRUPTEUR : `browser_enabled` à false, et rien ne part. C'est le
    # geste doux, réversible, qui n'exige aucun accès au serveur.
    #
    # L'ARRÊT DU CONTENEUR : `docker compose stop browser-worker`. Le geste
    # franc, celui qui ne se contourne pas — plus rien n'écoute, et aucun
    # réglage applicatif ne peut le rattraper.
    #
    # Sans ce garde, le second se traduisait par une exception de connexion
    # remontée telle quelle : l'utilisateur lisait une trace réseau au lieu
    # d'apprendre que la navigation est coupée.
    if not settings.browser_enabled:
        raise NavigateurCoupe(
            "La navigation web est désactivée sur ce déploiement.")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{settings.browser_worker_url}/run",
            json={
                "job_id": job_id,
                "task_prompt": task_prompt,
                "allowed_domains": allowed_domains,
                "user_id": user_id,
                "ingest": ingest,
                "readonly": readonly,
                "output_schema": output_schema,
            },
        )
        r.raise_for_status()
        return r.json()


async def start_task_sur(job_id: str, task_prompt: str, allowed_domains: list[str],
                         user_id: str, ingest: bool = False, readonly: bool = True,
                         output_schema: Optional[dict] = None) -> dict:
    """`start_task`, mais qui traduit un conteneur arrêté en refus lisible."""
    try:
        return await start_task(job_id, task_prompt, allowed_domains, user_id,
                                ingest=ingest, readonly=readonly,
                                output_schema=output_schema)
    except httpx.HTTPError as e:
        # Le conteneur ne répond pas : arrêté, en cours de redémarrage, ou
        # tombé. Le détail porte son adresse interne — il reste au journal.
        logger.warning("Conteneur navigateur injoignable (%s)", type(e).__name__)
        raise NavigateurCoupe(
            "Le navigateur est actuellement arrêté. Réessayez plus tard, ou "
            "demandez à l'administration de le relancer.") from e


async def cancel_task(job_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{settings.browser_worker_url}/jobs/{job_id}/cancel")
        r.raise_for_status()
        return r.json()
