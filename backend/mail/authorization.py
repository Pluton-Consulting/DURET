"""
Autorisation d'accès aux boîtes mail — point de passage OBLIGATOIRE.

Règle fondamentale : un utilisateur n'accède qu'à SA propre boîte, plus celles
qu'un dirigeant lui a explicitement déléguées. Sans cela, n'importe quel employé
pourrait faire rédiger — et un jour envoyer — un message au nom d'un dirigeant.

Principes de conception :
  * FAIL-CLOSED : toute situation ambiguë (boîte inconnue, paramètre vide,
    utilisateur sans email) refuse l'accès. Jamais de repli permissif.
  * UN SEUL point de vérification (`verifier_acces`) : toute fonction touchant
    au mail doit l'appeler. Aucun contournement possible ailleurs.
  * Les rôles d'administration ne contournent PAS la règle d'identité d'envoi.
    Un super_admin peut GÉRER les délégations ; il ne peut pas pour autant
    écrire au nom d'autrui sans s'être délégué la boîte. L'usurpation reste
    tracée dans `user_mailboxes` : c'est une décision, pas un effet de bord.
  * Comparaison insensible à la casse et aux espaces (les adresses arrivent de
    sources hétérogènes : Graph, saisie manuelle, base).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, status

from database.connection import get_db

logger = logging.getLogger("duret.mail.authz")


class AccesBoiteRefuse(HTTPException):
    """403 explicite — n'expose jamais l'existence d'une boîte tierce."""

    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# Rôle disposant d'un accès TOTAL aux boîtes, sans délégation préalable.
# Décision explicite du propriétaire du produit : l'administrateur doit pouvoir
# tout piloter depuis l'assistant. Les autres rôles, y compris `direction`,
# restent soumis aux délégations — c'est ce qui empêche un employé, ou même un
# cadre, d'écrire au nom d'un collègue. Chaque usage de ce contournement est
# journalisé.
ROLE_ACCES_TOTAL = "super_admin"

# Jeton signifiant « toutes les boîtes », consommé par le filtrage RAG.
TOUTES_LES_BOITES = "*"


def normaliser(adresse: Optional[str]) -> str:
    """Forme canonique d'une adresse : minuscules, sans espaces."""
    return (adresse or "").strip().lower()


def acces_total(role: Optional[str]) -> bool:
    return (role or "").strip().lower() == ROLE_ACCES_TOTAL


async def delegations(user_id: str) -> list[dict]:
    """Boîtes déléguées à cet utilisateur (hors sa boîte nominative).

    Requête volontairement filtrée sur `user_id` en dur plutôt que de s'appuyer
    sur la RLS : la décision d'autorisation ne doit dépendre d'aucun contexte
    de session susceptible d'être absent.
    """
    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT mailbox, can_send FROM user_mailboxes WHERE user_id = $1::uuid "
            "ORDER BY mailbox",
            str(user_id),
        )
    return [{"mailbox": r["mailbox"], "can_send": r["can_send"]} for r in rows]


async def boites_autorisees(user) -> list[dict]:
    """Toutes les boîtes accessibles : la sienne (envoi permis) + les délégations."""
    if acces_total(getattr(user, "role", None)):
        return [{"mailbox": TOUTES_LES_BOITES, "can_send": True, "propre": False,
                 "libelle": "Toutes les boîtes (administrateur)"}]

    propre = normaliser(getattr(user, "email", None))
    boites: list[dict] = []
    if propre:
        boites.append({"mailbox": propre, "can_send": True, "propre": True})

    for d in await delegations(str(user.id)):
        if d["mailbox"] != propre:                 # la sienne prime, jamais dupliquée
            boites.append({**d, "propre": False})
    return boites


async def boites_par_id(user_id: Optional[str]) -> list[str]:
    """Adresses accessibles à un utilisateur, à partir de son seul identifiant.

    Utilisé par le nœud RAG, qui ne dispose que de `user_id` dans l'état du
    graphe. Retourne une liste VIDE si l'utilisateur est inconnu : aucun mail ne
    sera alors visible (fail-closed).
    """
    if not user_id:
        return []
    async with get_db() as conn:
        ligne = await conn.fetchrow(
            "SELECT email, role FROM users WHERE id = $1::uuid", str(user_id))
    if ligne and acces_total(ligne["role"]):
        return [TOUTES_LES_BOITES]      # l'administrateur voit tous les mails

    boites = []
    propre = normaliser(ligne["email"] if ligne else None)
    if propre:
        boites.append(propre)
    for d in await delegations(str(user_id)):
        if d["mailbox"] not in boites:
            boites.append(d["mailbox"])
    return boites


async def verifier_acces(user, mailbox: Optional[str], envoi: bool = False) -> str:
    """Vérifie l'accès et retourne la boîte normalisée. Lève 403 sinon.

    `envoi=True` exige en plus le droit d'écriture (rédiger AU NOM DE cette
    boîte). Une délégation en lecture seule permet de consulter et de trier,
    pas de préparer un message signé de quelqu'un d'autre.
    """
    cible = normaliser(mailbox)
    if not cible:
        raise AccesBoiteRefuse("Aucune boîte mail précisée.")

    if acces_total(getattr(user, "role", None)):
        # Journalisé : un accès administrateur à la boîte d'autrui doit laisser
        # une trace, même s'il est légitime.
        logger.info("Accès administrateur à la boîte %s par %s (envoi=%s)",
                    cible, user.id, envoi)
        return cible

    propre = normaliser(getattr(user, "email", None))
    if not propre:
        # Un compte sans adresse ne peut rien faire : refus, pas de tolérance.
        raise AccesBoiteRefuse("Votre compte n'a pas d'adresse mail associée.")

    if cible == propre:
        return cible

    for d in await delegations(str(user.id)):
        if d["mailbox"] == cible:
            if envoi and not d["can_send"]:
                raise AccesBoiteRefuse(
                    f"La boîte {cible} vous est déléguée en lecture seule : "
                    "vous ne pouvez pas rédiger en son nom."
                )
            return cible

    # Message identique que la boîte existe ou non : ne pas révéler l'annuaire.
    logger.warning("Accès refusé à la boîte %s pour l'utilisateur %s", cible, user.id)
    raise AccesBoiteRefuse(
        f"Vous n'avez pas accès à la boîte {cible}. "
        "Demandez à votre direction de vous la déléguer."
    )


async def accorder(admin, user_id: str, mailbox: str, can_send: bool = True) -> dict:
    """Délègue une boîte à un utilisateur (réservé aux gestionnaires)."""
    cible = normaliser(mailbox)
    if "@" not in cible:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Adresse mail invalide.")
    async with get_db() as conn:
        beneficiaire = await conn.fetchrow(
            "SELECT id, email FROM users WHERE id = $1::uuid", str(user_id))
        if not beneficiaire:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="Utilisateur introuvable.")
        if normaliser(beneficiaire["email"]) == cible:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cette personne accède déjà à sa propre boîte : délégation inutile.")

        await conn.execute(
            """INSERT INTO user_mailboxes (user_id, mailbox, can_send, granted_by)
               VALUES ($1::uuid, $2, $3, $4::uuid)
               ON CONFLICT (user_id, mailbox) DO UPDATE SET can_send = EXCLUDED.can_send""",
            str(user_id), cible, can_send, str(admin.id),
        )
    logger.info("Boîte %s déléguée à %s par %s (envoi=%s)", cible, user_id, admin.id, can_send)
    return {"mailbox": cible, "can_send": can_send}


async def revoquer(user_id: str, mailbox: str) -> bool:
    """Retire une délégation. Retourne True si une ligne a été supprimée."""
    cible = normaliser(mailbox)
    async with get_db() as conn:
        res = await conn.execute(
            "DELETE FROM user_mailboxes WHERE user_id = $1::uuid AND mailbox = $2",
            str(user_id), cible,
        )
    supprime = res.endswith("1")
    if supprime:
        logger.info("Délégation %s retirée à %s", cible, user_id)
    return supprime
