"""
Router skills — registre, exécution et gouvernance du catalogue de skills.

- GET  /api/skills                 : liste (filtre agent / statuts)
- GET  /api/skills/{name}          : détail (code + prompt_template)
- POST /api/skills/{name}/run      : exécute run(data) en sandbox isolé
- POST /api/skills/{name}/validate : change le statut (validation humaine — gouvernance §15)
- PATCH /api/skills/{name}         : édite (description, prompt, code, agent, category)
- GET  /api/skills/export          : tout le catalogue en Markdown
- GET  /api/skills/{name}/export   : un skill en Markdown
- POST /api/skills/import          : importe un ou plusieurs skills depuis un .md

Gate RBAC : 'validate_skills' (direction / admin / super_admin).
"""
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status as http
from fastapi.responses import PlainTextResponse
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


MAX_IMPORT_OCTETS = 512 * 1024   # un skill n'est pas un dépôt : 512 Ko suffisent


# Ces deux routes sont déclarées AVANT `/{name}` : sinon « export » serait
# capturé comme un nom de skill.
@router.get("/export", response_class=PlainTextResponse)
async def exporter_tout(agent: Optional[str] = None,
                        current_user: User = Depends(get_current_user)):
    """Tout le catalogue en un seul Markdown, skills séparés par une règle."""
    _require(current_user)
    from skills.markdown import vers_markdown
    lignes = await executor.list_skills(agent=agent, include_code=True)
    if not lignes:
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="catalogue vide")
    corps = "\n\n---\n\n".join(vers_markdown(dict(s)) for s in lignes)
    await log_action(action="skills_exportes", user_id=str(current_user.id),
                     metadata={"nombre": len(lignes), "agent": agent})
    return PlainTextResponse(corps, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition":
                                      'attachment; filename="skills.md"'})


@router.post("/import")
async def importer_skill(file: UploadFile = File(...),
                         current_user: User = Depends(get_current_user)):
    """Importe un ou plusieurs skills depuis un fichier Markdown.

    Le fichier peut en contenir plusieurs, séparés par une règle « --- »
    isolée, comme le produit l'export global.

    SÉCURITÉ : quoi qu'annonce le fichier, un skill importé arrive en `draft` et
    DÉSACTIVÉ. Son code sera exécuté un jour : il passe par une relecture
    humaine. Sans cette règle, déposer un fichier reviendrait à faire exécuter
    du code arbitraire sur le serveur.
    """
    _require(current_user)
    from skills.markdown import depuis_markdown, MarkdownInvalide

    brut = await file.read()
    if not brut:
        raise HTTPException(status_code=http.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Fichier vide")
    if len(brut) > MAX_IMPORT_OCTETS:
        raise HTTPException(status_code=http.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Fichier trop volumineux (max {MAX_IMPORT_OCTETS // 1024} Ko)")
    try:
        texte = brut.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=http.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Le fichier doit être encodé en UTF-8")

    # Découpe sur une règle isolée SUIVIE d'un nouvel en-tête : on ne coupe pas
    # sur n'importe quel « --- », qui délimite aussi l'en-tête lui-même.
    morceaux = [m for m in re.split(r"\n---\n(?=\s*---\s*\n)", texte) if m.strip()] or [texte]

    importes, echecs = [], []
    for morceau in morceaux:
        try:
            # Le nom du fichier sert de repli quand le document ne se nomme pas.
            skill = depuis_markdown(morceau, nom_fichier=file.filename)
        except MarkdownInvalide as e:
            echecs.append(str(e))
            continue
        try:
            async with get_db() as conn:
                await conn.execute(
                    """INSERT INTO skills (name, description, code, prompt_template,
                                           status, created_by, agent, category, effect, enabled)
                       VALUES ($1, $2, $3, $4, 'draft', 'import', $5, $6, $7, false)
                       ON CONFLICT (name) DO UPDATE
                           SET description = EXCLUDED.description,
                               code = EXCLUDED.code,
                               prompt_template = EXCLUDED.prompt_template,
                               agent = EXCLUDED.agent,
                               category = EXCLUDED.category,
                               effect = EXCLUDED.effect,
                               version = skills.version + 1,
                               status = 'draft',
                               enabled = false,
                               updated_at = NOW()""",
                    skill["name"], skill["description"], skill["code"],
                    skill["prompt_template"], skill["agent"], skill["category"],
                    skill["effect"])
            importes.append(skill["name"])
        except Exception as e:  # noqa: BLE001 - un skill fautif n'annule pas les autres
            logger.warning("Import du skill %s échoué : %s", skill["name"], e)
            echecs.append(f"{skill['name']} : {e}")

    if not importes and echecs:
        raise HTTPException(status_code=http.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=" | ".join(echecs[:3]))

    await log_action(action="skills_importes", user_id=str(current_user.id),
                     metadata={"fichier": file.filename, "importes": importes,
                               "echecs": len(echecs)})
    return {"importes": importes, "echecs": echecs,
            "note": "Importés en brouillon et désactivés : relisez le code, puis validez."}


@router.get("/{name}/export", response_class=PlainTextResponse)
async def exporter_skill(name: str, current_user: User = Depends(get_current_user)):
    """Un skill, en Markdown éditable puis réimportable."""
    _require(current_user)
    from skills.markdown import vers_markdown
    skill = await executor.get_skill(name)
    if not skill:
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail="skill introuvable")
    return PlainTextResponse(
        vers_markdown(dict(skill)), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


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
            name, body.data, user_id=str(current_user.id),
            allow_draft=body.allow_draft, user=current_user,
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

    # Valider un skill le rend invocable ET l'annonce au modèle. Un skill sans
    # code qui n'est pas natif n'a rien à exécuter : il serait proposé, choisi,
    # puis échouerait. On refuse la promotion plutôt que de livrer une capacité
    # creuse. Les natifs, eux, ont leur code dans le backend : colonne vide,
    # c'est normal.
    if body.status in ("validated", "stable"):
        from mail.skills import EFFETS_NATIFS
        skill = await executor.get_skill(name)
        if skill and name not in EFFETS_NATIFS and not (skill.get("code") or "").strip():
            raise HTTPException(
                status_code=http.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=("Ce skill n'a pas de code : il documente une manière de faire, "
                        "mais rien ne peut s'exécuter. Ajoutez une fonction "
                        "« def run(data: dict) -> dict » avant de le valider."))

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
