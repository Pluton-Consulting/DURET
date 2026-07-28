"""
API de gestion des boîtes mail.

Deux niveaux :
  * tout utilisateur consulte les boîtes auxquelles il a droit ;
  * un gestionnaire (permission `manage_mailboxes`) délègue une boîte à
    quelqu'un — c'est ainsi qu'une personne gère « contact@ » en plus de sa
    boîte nominative.

L'accès effectif est toujours arbitré par `mail.authorization.verifier_acces`,
jamais par ce routeur : un seul point de décision, impossible à contourner.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import has_permission
from security.audit import log_action
from mail import authorization as authz
from mail.skills import TYPES_MAIL

router = APIRouter()


def _gestionnaire(user: User) -> None:
    if not has_permission(user.role, "manage_mailboxes"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Réservé à la direction.")


class Delegation(BaseModel):
    user_id: str
    mailbox: str
    can_send: bool = True


@router.get("/mailboxes")
async def mes_boites(current_user: User = Depends(get_current_user)):
    """Boîtes accessibles à l'utilisateur connecté : la sienne + ses délégations."""
    return {"boites": await authz.boites_autorisees(current_user)}


@router.get("/types")
async def types_de_mail(current_user: User = Depends(get_current_user)):
    """Types de messages que l'assistant sait rédiger."""
    return {"types": [{"cle": k, "libelle": v[0]} for k, v in TYPES_MAIL.items()]}


@router.get("/delegations")
async def toutes_les_delegations(current_user: User = Depends(get_current_user)):
    """Vue d'ensemble des délégations (gestionnaires uniquement)."""
    _gestionnaire(current_user)
    async with get_db() as conn:
        rows = await conn.fetch(
            """SELECT m.id, m.mailbox, m.can_send, m.created_at,
                      u.id AS user_id, u.email AS user_email, u.name AS user_name, u.role,
                      g.email AS granted_by_email
               FROM user_mailboxes m
               JOIN users u ON u.id = m.user_id
               LEFT JOIN users g ON g.id = m.granted_by
               ORDER BY u.email, m.mailbox"""
        )
    return {"delegations": [dict(r) for r in rows]}


@router.post("/delegations")
async def deleguer(body: Delegation, current_user: User = Depends(get_current_user)):
    """Donne à un utilisateur l'accès à une boîte supplémentaire."""
    _gestionnaire(current_user)
    resultat = await authz.accorder(current_user, body.user_id, body.mailbox, body.can_send)
    await log_action(
        action="mailbox_delegated", user_id=str(current_user.id),
        metadata={"beneficiaire": body.user_id, "mailbox": resultat["mailbox"],
                  "can_send": resultat["can_send"]},
    )
    return {"ok": True, **resultat}


@router.delete("/delegations")
async def retirer(user_id: str, mailbox: str, current_user: User = Depends(get_current_user)):
    """Retire une délégation."""
    _gestionnaire(current_user)
    supprime = await authz.revoquer(user_id, mailbox)
    if not supprime:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Délégation introuvable.")
    await log_action(action="mailbox_revoked", user_id=str(current_user.id),
                     metadata={"beneficiaire": user_id, "mailbox": authz.normaliser(mailbox)})
    return {"ok": True}


class ApprentissageStyle(BaseModel):
    mailbox: Optional[str] = None   # défaut : la boîte de la personne connectée
    nombre: Optional[int] = None    # défaut : MAIL_STYLE_SAMPLES


@router.post("/apprendre-style")
async def apprendre_style(body: ApprentissageStyle,
                          current_user: User = Depends(get_current_user)):
    """Apprend le style d'écriture d'une boîte à laquelle on a accès.

    Libre-service : AUCUNE permission d'administration. Chacun lance
    l'apprentissage pour sa propre boîte (ou une boîte qui lui a été déléguée),
    le périmètre étant borné par `mail.authorization`.
    """
    from mail.skills import apprendre_style as executer
    resultat = await executer({"mailbox": body.mailbox, "nombre": body.nombre}, current_user)
    await log_action(action="mail_style_learned", user_id=str(current_user.id),
                     metadata={"mailbox": resultat["mailbox"],
                               "messages": resultat["messages_analyses"]})
    return resultat


@router.get("/style/{mailbox}")
async def style_de_boite(mailbox: str, current_user: User = Depends(get_current_user)):
    """Profil de style appris pour une boîte (nécessite d'y avoir accès)."""
    boite = await authz.verifier_acces(current_user, mailbox)
    from mail.style import profil_enregistre
    profil = await profil_enregistre(boite)
    return {"mailbox": boite, "profil": profil or None}
