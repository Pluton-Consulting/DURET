"""
Router skills — registre, exécution et gouvernance du catalogue de skills.

- GET  /api/skills                 : liste (filtre agent / statuts)
- GET  /api/skills/{name}          : détail (code + prompt_template)
- POST /api/skills/{name}/run      : exécute run(data) en sandbox isolé
- POST /api/skills/{name}/validate : change le statut (validation humaine — gouvernance §15)
- PATCH /api/skills/{name}         : édite (description, prompt, code, agent, category)

Gate RBAC : 'validate_skills' (direction / admin / super_admin).
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status as http
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import has_permission
from security.audit import log_action
from skills import executor

logger = logging.getLogger("duret.skills.api")
router = APIRouter()

_VALID_STATUSES = ("draft", "testing", "validated", "stable", "deprecated")


def _require(user: User, feature: str = "validate_skills") -> None:
    if not has_permission(user.role, feature):
        raise HTTPException(status_code=http.HTTP_403_FORBIDDEN,
                            detail=f"Permission '{feature}' requise")


@router.get("")
async def list_skills(agent: Optional[str] = None, status_filter: Optional[str] = None,
                      current_user: User = Depends(get_current_user)):
    _require(current_user)
    statuses = tuple(s.strip() for s in status_filter.split(",")) if status_filter else None
    return await executor.list_skills(agent=agent, statuses=statuses)


@router.get("/{name}")
async def get_skill(name: str, current_user: User = Depends(get_current_user)):
    _require(current_user)
    skill = await executor.get_skill(name)
    if not skill:
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="skill introuvable")
    return skill


class RunBody(BaseModel):
    data: dict = {}
    allow_draft: bool = False   # exécuter un skill non encore validé (test admin)


@router.post("/{name}/run")
async def run_skill(name: str, body: RunBody, current_user: User = Depends(get_current_user)):
    _require(current_user)
    try:
        return await executor.execute_skill(
            name, body.data, user_id=str(current_user.id), allow_draft=body.allow_draft
        )
    except executor.SkillError as e:
        raise HTTPException(status_code=http.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


class ValidateBody(BaseModel):
    status: str   # draft | testing | validated | stable | deprecated


@router.post("/{name}/validate")
async def validate_skill(name: str, body: ValidateBody, current_user: User = Depends(get_current_user)):
    _require(current_user)
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=http.HTTP_422_UNPROCESSABLE_ENTITY, detail="statut invalide")
    async with get_db() as conn:
        res = await conn.execute(
            "UPDATE skills SET status=$2, validated_by=$3::uuid, validated_at=NOW(), updated_at=NOW() "
            "WHERE name=$1",
            name, body.status, str(current_user.id),
        )
    if res.endswith(" 0"):
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="skill introuvable")
    await log_action(action="skill_validated", user_id=str(current_user.id),
                     metadata={"skill": name, "status": body.status})
    return {"skill": name, "status": body.status}


class EnableBody(BaseModel):
    enabled: bool


@router.post("/{name}/enabled")
async def set_enabled(name: str, body: EnableBody, current_user: User = Depends(get_current_user)):
    _require(current_user)
    async with get_db() as conn:
        res = await conn.execute(
            "UPDATE skills SET enabled=$2, updated_at=NOW() WHERE name=$1", name, body.enabled
        )
    if res.endswith(" 0"):
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="skill introuvable")
    await log_action(action="skill_enabled" if body.enabled else "skill_disabled",
                     user_id=str(current_user.id), metadata={"skill": name})
    return {"skill": name, "enabled": body.enabled}


class UpdateBody(BaseModel):
    description: Optional[str] = None
    prompt_template: Optional[str] = None
    code: Optional[str] = None
    agent: Optional[str] = None
    category: Optional[str] = None


@router.patch("/{name}")
async def update_skill(name: str, body: UpdateBody, current_user: User = Depends(get_current_user)):
    _require(current_user)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=http.HTTP_422_UNPROCESSABLE_ENTITY, detail="aucun champ à modifier")
    sets, args = [], []
    for k, v in fields.items():
        args.append(v)
        sets.append(f"{k} = ${len(args)}")
    # éditer un skill le repasse en 'draft' (re-validation nécessaire), sauf si on ne touche
    # qu'aux métadonnées d'organisation (agent/category).
    if any(k in fields for k in ("code", "prompt_template", "description")):
        sets.append("status = 'draft'")
        sets.append("version = version + 1")
    args.append(name)
    async with get_db() as conn:
        res = await conn.execute(
            f"UPDATE skills SET {', '.join(sets)}, updated_at = NOW() WHERE name = ${len(args)}", *args
        )
    if res.endswith(" 0"):
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="skill introuvable")
    await log_action(action="skill_updated", user_id=str(current_user.id),
                     metadata={"skill": name, "champs": list(fields.keys())})
    return {"skill": name, "modifie": list(fields.keys())}
