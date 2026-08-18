"""
Ce que le worker RACONTE au backend — il n'écrit plus lui-même.

AVANT, ce module ouvrait un pool asyncpg vers Postgres. Le conteneur qui ouvre
des pages inconnues et exécute leur JavaScript détenait donc les identifiants de
la base et une route vers elle : en pratique, la clé de toute la mémoire de
l'entreprise, confiée au composant le plus exposé du montage.

Il passe maintenant par un guichet du backend. Ce conteneur n'a plus de mot de
passe de base, plus de route vers Postgres, et ne peut plus toucher qu'aux deux
tables que ces gestes désignent — parce que ce sont les seuls gestes qui
existent.

LES SIGNATURES N'ONT PAS BOUGÉ D'UN CARACTÈRE. `worker.py` et
`browser_agent.py` appellent exactement les mêmes fonctions qu'avant, avec les
mêmes arguments et les mêmes retours. Seule l'implémentation change : c'est ce
qui contient le risque de cette bascule à un seul fichier.

UNE ÉCRITURE PERDUE NE DOIT PAS TUER UNE TÂCHE. Si le backend ne répond pas,
on journalise et on continue : l'avancement affiché sera en retard, ce qui est
gênant, mais la navigation elle-même aboutira. L'inverse — interrompre un
travail de plusieurs minutes parce qu'un compteur n'a pas pu s'écrire — serait
absurde. Les deux LECTURES, elles, rendent None : leurs appelants savent déjà
traiter l'absence.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger("browser-worker.guichet")

BASE = os.environ.get("BACKEND_URL", "http://backend:8000").rstrip("/") + "/api/interne/navigateur"
SECRET = os.environ.get("BROWSER_WORKER_SECRET", "")
DELAI_S = 10.0


async def init_pool() -> None:
    """Plus de pool à ouvrir. Conservée : `worker.py` l'appelle au démarrage.

    On en profite pour dire tout de suite si le secret manque, plutôt que de
    laisser chaque écriture échouer en silence pendant des heures.
    """
    if not SECRET:
        logger.error("BROWSER_WORKER_SECRET absent : le backend refusera toute "
                     "remontée, et l'avancement des tâches restera figé.")
    else:
        logger.info("Remontée par le guichet du backend (%s)", BASE)


async def close_pool() -> None:
    """Plus de pool à fermer. Conservée pour l'arrêt propre de `worker.py`."""
    return None


async def _dire(methode: str, chemin: str, charge: dict | None = None) -> Any:
    """Un appel au guichet. Ne lève jamais : rend None en cas d'échec."""
    try:
        async with httpx.AsyncClient(timeout=DELAI_S) as client:
            r = await client.request(
                methode, BASE + chemin, json=charge,
                headers={"X-Navigateur-Secret": SECRET})
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        # 403 mérite d'être criant : c'est une erreur de configuration, pas un
        # aléa réseau, et elle rendrait TOUTES les tâches muettes.
        niveau = logger.error if e.response.status_code in (403, 503) else logger.warning
        niveau("Guichet navigateur : %s sur %s", e.response.status_code, chemin)
    except httpx.HTTPError as e:
        logger.warning("Guichet navigateur injoignable (%s) sur %s",
                       type(e).__name__, chemin)
    return None


# ── browser_tasks ────────────────────────────────────────────────────────
async def update_status(job_id: str, status: str) -> None:
    await _dire("POST", "/tache/statut", {"job_id": job_id, "status": status})


async def set_steps(job_id: str, steps: int) -> None:
    await _dire("POST", "/tache/etapes", {"job_id": job_id, "steps": steps})


async def set_result(job_id: str, status: str, result: dict | None = None,
                     structured: dict | None = None, steps: int | None = None) -> None:
    await _dire("POST", "/tache/resultat", {
        "job_id": job_id, "status": status, "result": result,
        "structured": structured, "steps": steps})


async def set_error(job_id: str, error: str) -> None:
    await _dire("POST", "/tache/erreur",
                {"job_id": job_id, "error": (error or "")[:1000]})


async def log_audit(action: str, user_id: str | None = None,
                    success: bool = True, metadata: dict | None = None) -> None:
    """La fonction que la reecriture avait PERDUE, appelee en premier par
    chaque tache : son absence tuait toute navigation autonome en
    AttributeError avant la premiere page. Comme ses voisines, elle ne leve
    jamais — l'audit ne doit pas emporter la tache qu'il raconte."""
    await _dire("POST", "/audit", {
        "action": action, "user_id": user_id,
        "success": success, "metadata": metadata,
    })


async def get_task(job_id: str) -> dict | None:
    d = await _dire("GET", "/tache/" + job_id)
    return (d or {}).get("tache")


# ── validations (accord humain, agent='browser') ─────────────────────────
async def insert_validation(thread_id: str, user_id: str, reason: str,
                            payload: dict, draft: str | None = None) -> str:
    d = await _dire("POST", "/validation", {
        "thread_id": thread_id, "user_id": user_id, "reason": reason,
        "payload": payload, "draft": draft})
    # UNE CHAÎNE VIDE PLUTÔT QU'UNE EXCEPTION : l'appelant sondera ensuite ce
    # dossier, et un identifiant vide le fera simplement conclure que l'accord
    # n'a pas été obtenu. Aucune action à effet externe ne passe sans accord —
    # échouer ici ferme la porte, ce qui est le bon sens de l'échec.
    return str((d or {}).get("validation_id") or "")


async def poll_validation_status(validation_id: str) -> str | None:
    if not validation_id:
        return None
    d = await _dire("GET", "/validation/" + validation_id)
    return (d or {}).get("status")


async def purge_validation_screenshot(validation_id: str) -> None:
    if not validation_id:
        return
    await _dire("DELETE", "/validation/" + validation_id + "/capture")
