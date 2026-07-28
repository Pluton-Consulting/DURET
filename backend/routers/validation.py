"""
Router human-in-the-loop : file d'attente des validations et reprise du graph.

Lorsqu'un agent suspend son exécution au « human_gate », une ligne est créée
dans la table `validations` avec le statut 'pending'. Ce router permet à un
valideur habilité de lister ces demandes, d'en consulter le détail, puis de les
résoudre (approuver ou refuser). La résolution relance le graph LangGraph
suspendu via `agents.runtime.resume_turn`.
"""
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from agents import runtime
from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import has_permission
from security.audit import log_action

router = APIRouter()


def _with_payload(row) -> dict:
    """Ligne → dict en désérialisant payload (JSONB renvoyé en str par asyncpg)."""
    d = dict(row)
    if isinstance(d.get("payload"), str):
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            d["payload"] = {}
    return d


class ResolveRequest(BaseModel):
    """Corps de la requête de résolution d'une validation."""
    approved: bool


def _peut_valider(role: str) -> bool:
    """Retourne True si le rôle peut traiter les validations (skills ou users)."""
    return has_permission(role, "validate_skills") or has_permission(role, "manage_users")


@router.get("/")
async def list_validations(current_user: User = Depends(get_current_user)):
    """
    Liste les validations en attente (status = 'pending').

    Accessible aux rôles disposant de la permission `validate_skills` ou
    `manage_users`, sinon 403. Renvoie pour chaque demande ses métadonnées ainsi
    que l'email et le nom de l'utilisateur qui l'a déclenchée (JOIN users).
    """
    if not _peut_valider(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                v.id, v.thread_id, v.agent, v.reason, v.draft, v.payload,
                v.created_at,
                u.email AS requester_email,
                u.name  AS requester_name
            FROM validations v
            LEFT JOIN users u ON u.id = v.user_id
            WHERE v.status = 'pending'
            ORDER BY v.created_at ASC
            """
        )

    return [_with_payload(row) for row in rows]


@router.get("/{validation_id}")
async def get_validation(
    validation_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """
    Détail d'une validation précise (404 si absente).

    Accessible aux rôles disposant de la permission `validate_skills` ou
    `manage_users`, sinon 403.
    """
    if not _peut_valider(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                v.id, v.thread_id, v.user_id, v.agent, v.reason, v.draft,
                v.payload, v.status, v.validated_by, v.created_at, v.resolved_at,
                u.email AS requester_email,
                u.name  AS requester_name
            FROM validations v
            LEFT JOIN users u ON u.id = v.user_id
            WHERE v.id = $1
            """,
            validation_id,
        )

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation introuvable")

    return _with_payload(row)


@router.post("/{validation_id}/resolve")
async def resolve_validation(
    validation_id: UUID,
    body: ResolveRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Résout une validation en attente puis relance le graph suspendu.

    - 404 si la validation est absente.
    - 409 si elle a déjà été résolue (status != 'pending').
    - 403 si le rôle n'a pas la permission `validate_skills` ou `manage_users`.

    La décision (`approved`) est transmise à `runtime.resume_turn`, qui reprend
    le graph LangGraph au point de suspension. L'action est journalisée.
    """
    if not _peut_valider(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        validation = await conn.fetchrow(
            """
            SELECT id, thread_id, agent, status
            FROM validations
            WHERE id = $1
            """,
            validation_id,
        )

    if not validation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation introuvable")
    if validation["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation déjà résolue")

    # Action de l'agent navigateur : PAS de graph LangGraph suspendu à reprendre.
    # Le worker navigateur poll le statut de la ligne → simple UPDATE ici (jamais resume_turn).
    if validation["agent"] == "browser":
        new_status = "approved" if body.approved else "rejected"
        async with get_db() as conn:
            await conn.execute(
                "UPDATE validations SET status=$1, validated_by=$2, resolved_at=NOW() WHERE id=$3",
                new_status, current_user.id, validation_id,
            )
        await log_action(
            action="validation_resolved",
            user_id=str(current_user.id),
            metadata={"validation_id": str(validation_id), "approved": body.approved, "type": "browser"},
        )
        return {"status": new_status, "validation_id": str(validation_id), "type": "browser"}

    # Cas standard (skills agent3, chiffrage agent2…) : reprise du graph LangGraph.
    result = await runtime.resume_turn(
        thread_id=str(validation["thread_id"]),
        approved=body.approved,
        validated_by=str(current_user.id),
        validation_id=str(validation_id),
    )

    # Une validation peut appartenir à une TÂCHE autonome, suspendue en attendant
    # cette décision (thread_id = « task:<run_id> »). On referme alors l'exécution,
    # sans quoi elle resterait indéfiniment en « awaiting_approval ».
    fil = str(validation["thread_id"] or "")
    if fil.startswith("task:"):
        run_id = fil.split(":", 1)[1]
        try:
            import json as _json
            async with get_db() as conn:
                await conn.execute(
                    """UPDATE agent_task_runs
                       SET status = $1, result = $2, updated_at = NOW()
                       WHERE id = $3::uuid""",
                    "completed" if body.approved else "cancelled",
                    _json.dumps({"reponse": result.get("response"),
                                 "validee_par": str(current_user.id)}),
                    run_id)
        except Exception as e:  # noqa: BLE001 - ne jamais faire échouer la validation
            logging.getLogger("duret.validation").warning(
                "Exécution %s non mise à jour : %s", run_id, e)

    await log_action(
        action="validation_resolved",
        user_id=str(current_user.id),
        metadata={"validation_id": str(validation_id), "approved": body.approved,
                  "fil": fil},
    )

    return result
