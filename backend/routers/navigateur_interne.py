"""
LE GUICHET DU CONTENEUR NAVIGATEUR.

Le worker écrivait DIRECTEMENT en base : avancement des tâches, résultats,
demandes de validation. Il lui fallait donc un accès réseau à Postgres et les
identifiants de la base — c'est-à-dire, en pratique, la clé de toute la mémoire
de l'entreprise, donnée au seul conteneur qui ouvre des pages inconnues et
exécute leur JavaScript.

Ce guichet renverse la charge : le worker RACONTE, le backend ÉCRIT. Le
conteneur n'a plus de mot de passe de base, plus de route vers Postgres, et ne
peut plus toucher qu'aux deux tables que ces gestes désignent — parce que ce
sont les seuls gestes qui existent.

CE QUI PROTÈGE, ET CE QUI NE PROTÈGE PAS.

Le secret partagé n'est pas le garde-fou principal : il empêche un tiers du
réseau interne d'appeler ce guichet, rien de plus. Si le conteneur navigateur
est compromis, l'attaquant a le secret — il l'a dans son environnement.

Le vrai garde-fou est la FORME de cette API. Il n'existe ici aucun geste
générique : pas de « exécute cette requête », pas de nom de table en paramètre,
pas de champ libre. Huit verbes, chacun écrivant une colonne connue d'une ligne
désignée par son identifiant. Le pire qu'un conteneur retourné puisse faire,
c'est mentir sur l'avancement de ses propres tâches.

CES ROUTES NE SONT PAS PUBLIQUES. Elles ne passent pas par nginx — aucun bloc
`location` ne les expose — et ne sont joignables que depuis le réseau interne.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from config import settings
from database.connection import get_db

logger = logging.getLogger("symbiose.navigateur.guichet")

router = APIRouter()


def _verifier(secret: Optional[str]) -> None:
    """Le secret partagé, comparé sans fuite de temps.

    Un secret vide en configuration REFUSE tout : c'est délibéré. Le laisser
    passer transformerait un oubli de déploiement en guichet ouvert, et
    personne ne s'en apercevrait puisque tout continuerait de fonctionner.
    """
    attendu = settings.browser_worker_secret
    if not attendu:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Guichet navigateur non configuré.")
    import hmac
    if not secret or not hmac.compare_digest(secret, attendu):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Refusé.")


class Statut(BaseModel):
    job_id: str
    status: str


class Etapes(BaseModel):
    job_id: str
    steps: int


class Resultat(BaseModel):
    job_id: str
    status: str
    result: Optional[dict] = None
    structured: Optional[dict] = None
    steps: Optional[int] = None


class Erreur(BaseModel):
    job_id: str
    error: str


class Validation(BaseModel):
    thread_id: str
    user_id: str
    reason: str
    payload: dict
    draft: Optional[str] = None


class Audit(BaseModel):
    action: str
    user_id: str | None = None
    success: bool = True
    metadata: dict | None = None


@router.post("/audit")
async def audit(c: Audit, x_navigateur_secret: str = Header(default="")):
    """Le journal d'audit du navigateur, par le guichet.

    `log_audit` etait la SEULE fonction oubliee en reecrivant `db.py` du worker
    en passerelle HTTP — et elle est appelee en PREMIER dans chaque tache.
    Toute navigation autonome mourait donc a sa premiere ligne, en
    AttributeError, avant meme d'ouvrir une page. Meme lecon que
    `was_filtered` : un contrat reecrit se compare A CELUI QU'ON REMPLACE,
    element par element — l'usage qu'on croit en connaitre ne suffit pas.
    """
    _verifier(x_navigateur_secret)
    from security.audit import log_action
    await log_action(action=c.action, user_id=c.user_id, agent_id="browser",
                     success=c.success, metadata=c.metadata)
    return {"ok": True}


@router.post("/tache/statut")
async def tache_statut(c: Statut, x_navigateur_secret: str = Header(default="")):
    _verifier(x_navigateur_secret)
    async with get_db() as conn:
        await conn.execute(
            "UPDATE browser_tasks SET status=$2, updated_at=NOW() WHERE id=$1::uuid",
            c.job_id, c.status)
    return {"ok": True}


@router.post("/tache/etapes")
async def tache_etapes(c: Etapes, x_navigateur_secret: str = Header(default="")):
    _verifier(x_navigateur_secret)
    async with get_db() as conn:
        await conn.execute(
            "UPDATE browser_tasks SET steps=$2, updated_at=NOW() WHERE id=$1::uuid",
            c.job_id, c.steps)
    return {"ok": True}


@router.post("/tache/resultat")
async def tache_resultat(c: Resultat, x_navigateur_secret: str = Header(default="")):
    _verifier(x_navigateur_secret)
    async with get_db() as conn:
        await conn.execute(
            "UPDATE browser_tasks SET status=$2, result=$3::jsonb, "
            "structured_output=$4::jsonb, steps=COALESCE($5, steps), "
            "updated_at=NOW() WHERE id=$1::uuid",
            c.job_id, c.status,
            json.dumps(c.result) if c.result is not None else None,
            json.dumps(c.structured) if c.structured is not None else None,
            c.steps)
    return {"ok": True}


@router.post("/tache/erreur")
async def tache_erreur(c: Erreur, x_navigateur_secret: str = Header(default="")):
    _verifier(x_navigateur_secret)
    async with get_db() as conn:
        await conn.execute(
            "UPDATE browser_tasks SET status='failed', error=$2, updated_at=NOW() "
            "WHERE id=$1::uuid",
            c.job_id, (c.error or "")[:1000])
    return {"ok": True}


@router.get("/tache/{job_id}")
async def tache(job_id: str, x_navigateur_secret: str = Header(default="")):
    _verifier(x_navigateur_secret)
    async with get_db() as conn:
        ligne = await conn.fetchrow(
            "SELECT id, status, task_prompt, result, structured_output, error, steps, "
            "created_at, updated_at FROM browser_tasks WHERE id=$1::uuid", job_id)
    return {"tache": _serialisable(dict(ligne)) if ligne else None}


@router.post("/validation")
async def validation(c: Validation, x_navigateur_secret: str = Header(default="")):
    _verifier(x_navigateur_secret)
    async with get_db() as conn:
        vid = await conn.fetchval(
            "INSERT INTO validations (thread_id, user_id, agent, reason, payload, "
            "draft, status) VALUES ($1, $2::uuid, 'browser', $3, $4::jsonb, $5, "
            "'pending') RETURNING id",
            c.thread_id, c.user_id, c.reason, json.dumps(c.payload), c.draft)
    return {"validation_id": str(vid)}


@router.get("/validation/{validation_id}")
async def validation_statut(validation_id: str,
                            x_navigateur_secret: str = Header(default="")):
    _verifier(x_navigateur_secret)
    async with get_db() as conn:
        statut = await conn.fetchval(
            "SELECT status FROM validations WHERE id=$1::uuid", validation_id)
    return {"status": statut}


@router.delete("/validation/{validation_id}/capture")
async def purger_capture(validation_id: str,
                         x_navigateur_secret: str = Header(default="")):
    """Retire la capture d'écran du dossier une fois la décision prise.

    Une capture montre l'écran tel qu'il était : elle peut porter un nom, un
    montant, une adresse. Elle n'a de raison d'exister que le temps de décider.
    """
    _verifier(x_navigateur_secret)
    async with get_db() as conn:
        await conn.execute(
            "UPDATE validations SET payload = payload - 'screenshot' WHERE id=$1::uuid",
            validation_id)
    return {"ok": True}


def _serialisable(d: dict) -> dict[str, Any]:
    """Dates en texte, JSON en objets : ce qui traverse doit être du JSON pur."""
    import datetime
    sortie: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, (datetime.datetime, datetime.date)):
            sortie[k] = v.isoformat()
        elif isinstance(v, str) and k in ("result", "structured_output"):
            try:
                sortie[k] = json.loads(v)
            except (ValueError, TypeError):
                sortie[k] = v
        else:
            sortie[k] = str(v) if k == "id" else v
    return sortie
