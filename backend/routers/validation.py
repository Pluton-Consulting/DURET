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

    decision = "approved" if body.approved else "rejected"

    # RÉCLAMATION ATOMIQUE. Lire le statut puis décider en Python laissait une
    # fenêtre : la reprise dure plusieurs secondes (elle EXÉCUTE l'action), donc
    # deux clics — deux onglets, deux valideurs — passaient tous deux le
    # contrôle « pending » et lançaient DEUX reprises sur le même fil. L'action
    # externe partait deux fois, et deux graphes écrivaient le même historique.
    #
    # Un seul UPDATE conditionnel tranche : celui qui touche la ligne a gagné,
    # l'autre reçoit 409. Le `RETURNING` sert à distinguer « déjà résolue » de
    # « inexistante » sans seconde requête.
    async with get_db() as conn:
        reclamee = await conn.fetchrow(
            """UPDATE validations
               SET status = $1, validated_by = $2, resolved_at = NOW()
               WHERE id = $3 AND status = 'pending'
               RETURNING id, thread_id, agent""",
            decision, current_user.id, validation_id)
        if reclamee is None:
            existe = await conn.fetchval(
                "SELECT 1 FROM validations WHERE id = $1", validation_id)
    if reclamee is None:
        if not existe:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Validation introuvable")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Validation déjà résolue")

    validation = reclamee
    fil = str(validation["thread_id"] or "")

    # Action de l'agent navigateur : PAS de graph LangGraph suspendu à reprendre.
    # Le worker navigateur poll le statut de la ligne, déjà écrit ci-dessus.
    if validation["agent"] == "browser":
        await log_action(
            action="validation_resolved",
            user_id=str(current_user.id),
            metadata={"validation_id": str(validation_id), "approved": body.approved, "type": "browser"},
        )
        return {"status": decision, "validation_id": str(validation_id), "type": "browser"}

    # Cas standard (skills agent3, chiffrage agent2…) : reprise du graph LangGraph.
    #
    # SI LA REPRISE ÉCHOUE — fournisseur de modèle en panne, quota épuisé — la
    # décision est déjà écrite : la carte d'accord disparaît, et sans ce
    # rattrapage la tâche resterait « en attente de votre accord » pour
    # toujours, avec plus rien au-dessus et un 409 à chaque nouvel essai.
    # On la bascule en échec, en le disant. On NE REJOUE PAS automatiquement :
    # personne ne sait si l'action externe est partie avant l'erreur, et la
    # relancer d'office pourrait la faire deux fois.
    try:
        result = await runtime.resume_turn(
            thread_id=fil,
            approved=body.approved,
            validated_by=str(current_user.id),
            validation_id=str(validation_id),
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger("duret.validation").warning(
            "Reprise de %s en échec : %s", validation_id, e)
        if fil.startswith("file:"):
            try:
                async with get_db() as conn:
                    await conn.execute(
                        """UPDATE taches_differees
                           SET status = 'echec',
                               error = 'la reprise après validation a échoué ; '
                                       'vérifiez si l''action a été effectuée',
                               progress = 'échec à la reprise', updated_at = NOW()
                           WHERE id = $1::uuid""", fil.split(":", 1)[1])
            except Exception:  # noqa: BLE001
                pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="La décision est enregistrée mais la reprise a échoué. "
                   "Vérifiez si l'action a été effectuée avant de relancer.")

    # Une validation peut appartenir à une tâche de la FILE D'ATTENTE du chat
    # (thread_id = « file:<id> »), approuvée parfois plusieurs jours après. La
    # reprise vient de s'exécuter ci-dessus ; on referme la ligne pour que la
    # carte affiche le résultat — ou une NOUVELLE attente si la reprise a levé
    # une seconde action externe (une demande en plusieurs étapes en compte
    # parfois deux).
    if fil.startswith("file:"):
        tache_id = fil.split(":", 1)[1]
        try:
            async with get_db() as conn:
                if result.get("status") == "pending_validation":
                    await conn.execute(
                        """UPDATE taches_differees
                           SET status = 'attente_validation',
                               validation_id = $1::uuid,
                               progress = 'en attente de votre accord',
                               updated_at = NOW()
                           WHERE id = $2::uuid""",
                        str(result.get("validation_id")), tache_id)
                else:
                    # Approuvée ou refusée, la tâche est CLOSE : la réponse de
                    # la reprise dit ce qui a été fait (ou pourquoi rien).
                    await conn.execute(
                        """UPDATE taches_differees
                           SET status = 'terminee', response = $1,
                               progress = $2, updated_at = NOW()
                           WHERE id = $3::uuid""",
                        result.get("response") or "",
                        "terminée" if body.approved else "refusée, rien n'a été fait",
                        tache_id)
        except Exception as e:  # noqa: BLE001 - ne jamais faire échouer la validation
            logging.getLogger("duret.validation").warning(
                "Tâche différée %s non mise à jour : %s", tache_id, e)

    # Une validation peut appartenir à une TÂCHE autonome, suspendue en attendant
    # cette décision (thread_id = « task:<run_id> »). On referme alors l'exécution,
    # sans quoi elle resterait indéfiniment en « awaiting_approval ».
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
