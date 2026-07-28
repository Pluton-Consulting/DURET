"""
Skill natif : déléguer une tâche à un agent depuis le chat.

C'est le déclencheur (a) du dispositif : « à partir de demain, chaque matin à
7h30, trie les mails de contact@ ». L'assistant crée la tâche ; il ne l'exécute
pas dans la foulée.

Effet `ecriture_interne` : créer une ligne ne produit aucun effet hors du
système. Quand la tâche s'exécutera, elle repassera par TOUS les contrôles —
identité rechargée, cloisonnement des boîtes, validation humaine pour toute
action externe. Créer une tâche ne contourne donc rien.
"""
from __future__ import annotations

import json
import logging

from fastapi import HTTPException, status

from database.connection import get_db
from tasks.scheduler import prochaine_echeance, valider_planification

logger = logging.getLogger("duret.tasks.skills")


class TacheInvalide(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


async def creer_tache_agent(data: dict, user) -> dict:
    """Crée une tâche planifiée ou manuelle, au nom de la personne connectée."""
    titre = (data.get("titre") or "").strip()
    consigne = (data.get("consigne") or data.get("prompt") or "").strip()
    if not titre or not consigne:
        raise TacheInvalide("Il faut un titre et une consigne pour créer une tâche.")

    planification = {
        "schedule_kind": (data.get("recurrence") or data.get("schedule_kind") or None),
        "interval_minutes": data.get("interval_minutes"),
        "time_of_day": data.get("heure") or data.get("time_of_day"),
        "days_of_week": data.get("jours") or data.get("days_of_week"),
    }
    erreur = valider_planification(planification)
    if erreur:
        raise TacheInvalide(erreur)

    planifiee = bool(planification["schedule_kind"])
    premiere = prochaine_echeance(planification) if planifiee else None

    async with get_db() as conn:
        ligne = await conn.fetchrow(
            """INSERT INTO agent_tasks
                   (user_id, title, task_prompt, params, trigger_kind, schedule_kind,
                    interval_minutes, time_of_day, days_of_week, next_run_at)
               VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6, $7, $8::time, $9, $10)
               RETURNING id, title, next_run_at""",
            str(user.id), titre[:255], consigne, json.dumps({}),
            "schedule" if planifiee else "manual",
            planification["schedule_kind"], planification["interval_minutes"],
            planification["time_of_day"], planification["days_of_week"], premiere,
        )

    logger.info("Tâche « %s » créée par %s (planifiée=%s)", titre, user.id, planifiee)
    return {
        "tache_id": str(ligne["id"]),
        "titre": ligne["title"],
        "planifiee": planifiee,
        "prochaine_execution": ligne["next_run_at"].isoformat() if ligne["next_run_at"] else None,
        "message": (f"Tâche « {titre} » enregistrée."
                    + (f" Première exécution : {ligne['next_run_at']:%d/%m/%Y à %Hh%M}."
                       if ligne["next_run_at"] else
                       " Elle ne se déclenchera que sur demande.")),
    }
