"""
API des tâches d'agent : création, planification, historique.

Principe d'autorisation : une tâche s'exécute TOUJOURS au nom de son créateur.
`user_id` n'est jamais un paramètre d'entrée — sinon n'importe qui pourrait faire
agir l'assistant sous l'identité d'un autre, ce que tout le cloisonnement des
boîtes mail cherche justement à empêcher.
"""
from __future__ import annotations

import json
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import has_permission
from security.audit import log_action
from tasks.scheduler import heure_du_jour, prochaine_echeance, valider_planification

router = APIRouter()

DECLENCHEURS = ("manual", "schedule", "webhook")


class TacheEntrante(BaseModel):
    title: str
    task_prompt: str
    trigger_kind: str = "manual"
    schedule_kind: Optional[str] = None      # interval | daily | weekly
    interval_minutes: Optional[int] = None
    time_of_day: Optional[str] = None        # « 07:30 »
    days_of_week: Optional[list[int]] = None # 1 = lundi … 7 = dimanche
    params: dict = {}


def _superviseur(user: User) -> bool:
    """Peut voir les tâches de tout le monde (pas seulement les siennes)."""
    return has_permission(user.role, "validate_skills")


@router.get("")
async def lister(current_user: User = Depends(get_current_user)):
    """Ses tâches — toutes celles de l'équipe pour un superviseur."""
    async with get_db() as conn:
        if _superviseur(current_user):
            lignes = await conn.fetch(
                """SELECT t.*, u.email AS proprietaire
                   FROM agent_tasks t LEFT JOIN users u ON u.id = t.user_id
                   ORDER BY t.created_at DESC""")
        else:
            lignes = await conn.fetch(
                """SELECT t.*, u.email AS proprietaire
                   FROM agent_tasks t LEFT JOIN users u ON u.id = t.user_id
                   WHERE t.user_id = $1::uuid ORDER BY t.created_at DESC""",
                str(current_user.id))
    # `webhook_secret` n'est JAMAIS retourné ici : il n'est montré qu'une fois,
    # à la création. Une clé qu'on peut relire est une clé qui finit par fuiter.
    return {"taches": [{k: v for k, v in dict(l).items() if k != "webhook_secret"}
                       for l in lignes]}


@router.post("")
async def creer(body: TacheEntrante, current_user: User = Depends(get_current_user)):
    """Crée une tâche. Elle agira au nom de la personne connectée."""
    if not has_permission(current_user.role, "chat_agent1"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    if body.trigger_kind not in DECLENCHEURS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Déclencheur inconnu. Attendu : {', '.join(DECLENCHEURS)}")
    if not body.title.strip() or not body.task_prompt.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Titre et consigne sont obligatoires.")

    donnees = body.model_dump()
    erreur = valider_planification(donnees)
    if erreur:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=erreur)

    premiere = prochaine_echeance(donnees) if body.schedule_kind else None
    secret = secrets.token_hex(24) if body.trigger_kind == "webhook" else None

    async with get_db() as conn:
        ligne = await conn.fetchrow(
            """INSERT INTO agent_tasks
                   (user_id, title, task_prompt, params, trigger_kind, schedule_kind,
                    interval_minutes, time_of_day, days_of_week, next_run_at, webhook_secret)
               VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6, $7, $8::time, $9, $10, $11)
               RETURNING id, title, trigger_kind, schedule_kind, next_run_at, enabled""",
            str(current_user.id), body.title.strip(), body.task_prompt.strip(),
            json.dumps(body.params or {}), body.trigger_kind, body.schedule_kind,
            body.interval_minutes, heure_du_jour(body.time_of_day),
            body.days_of_week, premiere, secret,
        )

    await log_action(action="agent_task_created", user_id=str(current_user.id),
                     metadata={"task": str(ligne["id"]), "declencheur": body.trigger_kind})

    reponse = dict(ligne)
    if secret:
        # Montré UNE seule fois. L'endpoint de lecture ne le renverra jamais.
        reponse["webhook_secret"] = secret
        reponse["webhook_url"] = f"/api/hooks/{ligne['id']}"
        reponse["avertissement"] = ("Conservez ce secret : il ne sera plus jamais affiché. "
                                    "Il sert à signer les appels, il ne transite pas.")
    return reponse


@router.post("/{task_id}/executer")
async def executer_maintenant(task_id: str, current_user: User = Depends(get_current_user)):
    """Déclenche une exécution immédiate."""
    async with get_db() as conn:
        tache = await conn.fetchrow("SELECT * FROM agent_tasks WHERE id = $1::uuid", task_id)
        if not tache:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tâche introuvable")
        if str(tache["user_id"]) != str(current_user.id) and not _superviseur(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Cette tâche ne vous appartient pas.")
        run = await conn.fetchrow(
            """INSERT INTO agent_task_runs (task_id, user_id, status, trigger_kind)
               VALUES ($1::uuid, $2, 'pending', 'manual') RETURNING id""",
            task_id, tache["user_id"])
    # L'exécution reste au nom du PROPRIÉTAIRE de la tâche, même déclenchée par un
    # superviseur : déclencher n'est pas prêter ses droits.
    return {"ok": True, "run_id": str(run["id"]),
            "message": "Exécution mise en file, elle démarre dans moins d'une minute."}


class Bascule(BaseModel):
    enabled: bool


@router.post("/{task_id}/actif")
async def basculer(task_id: str, body: Bascule, current_user: User = Depends(get_current_user)):
    """Active ou suspend une tâche."""
    async with get_db() as conn:
        tache = await conn.fetchrow("SELECT * FROM agent_tasks WHERE id = $1::uuid", task_id)
        if not tache:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tâche introuvable")
        if str(tache["user_id"]) != str(current_user.id) and not _superviseur(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
        # Réactiver recalcule l'échéance : sans ça, une tâche suspendue longtemps
        # se déclencherait immédiatement, avec une échéance périmée.
        suivante = prochaine_echeance(dict(tache)) if (body.enabled and tache["schedule_kind"]) else None
        await conn.execute(
            "UPDATE agent_tasks SET enabled = $1, next_run_at = $2, updated_at = NOW() "
            "WHERE id = $3::uuid", body.enabled, suivante, task_id)
    return {"ok": True, "enabled": body.enabled, "next_run_at": suivante}


@router.delete("/{task_id}")
async def supprimer(task_id: str, current_user: User = Depends(get_current_user)):
    async with get_db() as conn:
        tache = await conn.fetchrow("SELECT user_id FROM agent_tasks WHERE id = $1::uuid", task_id)
        if not tache:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tâche introuvable")
        if str(tache["user_id"]) != str(current_user.id) and not _superviseur(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
        await conn.execute("DELETE FROM agent_tasks WHERE id = $1::uuid", task_id)
    await log_action(action="agent_task_deleted", user_id=str(current_user.id),
                     metadata={"task": task_id})
    return {"ok": True}


@router.get("/{task_id}/executions")
async def executions(task_id: str, current_user: User = Depends(get_current_user)):
    """Historique des exécutions d'une tâche."""
    async with get_db() as conn:
        tache = await conn.fetchrow("SELECT user_id FROM agent_tasks WHERE id = $1::uuid", task_id)
        if not tache:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tâche introuvable")
        if str(tache["user_id"]) != str(current_user.id) and not _superviseur(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
        lignes = await conn.fetch(
            """SELECT id, status, trigger_kind, result, error, started_at, created_at
               FROM agent_task_runs WHERE task_id = $1::uuid
               ORDER BY created_at DESC LIMIT 50""", task_id)
    return {"executions": [dict(l) for l in lignes]}


@router.post("/executions/{run_id}/annuler")
async def annuler(run_id: str, current_user: User = Depends(get_current_user)):
    """Arrête une exécution en attente ou suspendue."""
    async with get_db() as conn:
        run = await conn.fetchrow("SELECT * FROM agent_task_runs WHERE id = $1::uuid", run_id)
        if not run:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exécution introuvable")
        if str(run["user_id"]) != str(current_user.id) and not _superviseur(current_user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
        if run["status"] not in ("pending", "awaiting_approval", "running"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"Exécution déjà « {run['status']} ».")
        await conn.execute(
            "UPDATE agent_task_runs SET status = 'cancelled', updated_at = NOW() "
            "WHERE id = $1::uuid", run_id)
    return {"ok": True}
