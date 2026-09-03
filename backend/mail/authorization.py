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
  * DEUX rôles contournent la délégation : `super_admin` et `direction` (cf.
    ROLES_ACCES_SUR_DEMANDE). Ils lisent, ET ÉCRIVENT AU NOM DE, toute boîte
    qu'ils NOMMENT explicitement — sans délégation préalable, `can_send` non
    consulté ; chaque usage du contournement est tracé dans `audit_log`. Le
    DÉFAUT de la direction reste sa propre boîte. Tous les autres rôles restent
    strictement bornés par `user_mailboxes`.
  * LE SUPER_ADMIN VOIT TOUT (03/09, décision de Noa : « supprime la limitation
    au mail de l'utilisateur en cours pour le super admin, il doit pouvoir
    accéder à tous les mails, et par défaut celui d'un direction »). Il n'a pas
    de boîte dans le domaine de l'entreprise — c'est le développeur — donc sa
    « propre boîte » ne lisait rien : son défaut est la boîte d'un DIRIGEANT
    (`boite_par_defaut`), et la mémoire lui montre tous les mails
    (`boites_par_id` rend le jeton « toutes les boîtes »).
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


# Rôles disposant d'un accès aux boîtes SUR DEMANDE, sans délégation préalable.
# Décision de Noa du 01/09 : le super_admin ET la direction accèdent à toute
# boîte qu'ils NOMMENT explicitement — mais leur DÉFAUT (rien de nommé) reste
# leur propre boîte, comme tout le monde. Les autres rôles restent soumis aux
# délégations — c'est ce qui empêche un employé d'écrire au nom d'un collègue.
# Chaque usage de ce contournement est journalisé.
ROLES_ACCES_SUR_DEMANDE = {"super_admin", "direction"}
# ⚠ DÉPRÉCIÉ (01/09) : ce n'est plus UN rôle mais un ENSEMBLE. Un contrôle
# écrit `if role == ROLE_ACCES_TOTAL` serait silencieusement faux pour la
# direction — utiliser `acces_total(role)`. Conservé pour les sondes externes.
ROLE_ACCES_TOTAL = ROLES_ACCES_SUR_DEMANDE

# Jeton signifiant « toutes les boîtes », consommé par le filtrage RAG.
TOUTES_LES_BOITES = "*"


def normaliser(adresse: Optional[str]) -> str:
    """Forme canonique d'une adresse : minuscules, sans espaces."""
    return (adresse or "").strip().lower()


def acces_total(role: Optional[str]) -> bool:
    """Accès aux boîtes SUR DEMANDE (boîte nommée) : super_admin et direction."""
    return (role or "").strip().lower() in ROLES_ACCES_SUR_DEMANDE


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
    # PAS DE JETON « TOUTES LES BOÎTES » ICI (01/09). Ce jeton est lu ailleurs
    # comme un blanc-seing (filtrage RAG), alors que le DÉFAUT de ces rôles est
    # désormais leur propre boîte. On rend donc les boîtes RÉELLES, et on dit à
    # part que ce rôle peut en demander une autre — c'est une capacité, pas un
    # accès déjà ouvert.
    elargi = acces_total(getattr(user, "role", None))

    propre = normaliser(getattr(user, "email", None))
    boites: list[dict] = []
    if propre:
        boites.append({"mailbox": propre, "can_send": True, "propre": True})

    for d in await delegations(str(user.id)):
        if d["mailbox"] != propre:                 # la sienne prime, jamais dupliquée
            boites.append({**d, "propre": False})
    if elargi:
        # La capacité se DIT, elle ne s'exerce qu'en nommant une boîte.
        for x in boites:
            x.setdefault("sur_demande", False)
        boites.append({"mailbox": None, "can_send": True, "propre": False,
                       "sur_demande": True,
                       "libelle": "Toute autre boîte, sur demande explicite (journalisé)"})
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
        # `actif = true` : un compte désactivé ne doit plus rien voir, y compris via
        # une tâche différée créée quand il était encore actif.
        ligne = await conn.fetchrow(
            "SELECT email, role FROM users WHERE id = $1::uuid AND actif = true", str(user_id))
    # LE DÉFAUT EST SA BOÎTE POUR LA DIRECTION ET LES MÉTIERS (01/09) ; LE
    # SUPER_ADMIN, LUI, VOIT TOUT (03/09, retour de Noa). Le 01/09 avait retiré
    # le jeton « toutes les boîtes » à l'administrateur ; à l'usage, un
    # super_admin sans boîte dans le domaine ne voyait plus AUCUN mail dans la
    # mémoire — la limitation ne protégeait personne, elle rendait le compte
    # de test aveugle. La direction, elle, garde sa boîte + ses délégations,
    # et n'ouvre une autre boîte qu'en la NOMMANT (journalisé).
    if ligne and (ligne["role"] or "").strip().lower() == "super_admin":
        return [TOUTES_LES_BOITES]
    boites = []
    propre = normaliser(ligne["email"] if ligne else None)
    if propre:
        boites.append(propre)
    for d in await delegations(str(user_id)):
        if d["mailbox"] not in boites:
            boites.append(d["mailbox"])
    return boites


async def boite_par_defaut(user) -> Optional[str]:
    """La boîte qu'on ouvre quand personne n'en nomme une.

    Pour tout le monde : la sienne. Pour le SUPER_ADMIN : celle d'un DIRIGEANT
    (03/09, Noa) — le premier compte `direction` actif, par ancienneté, donc
    toujours le même tant que les comptes ne bougent pas. Le super_admin est
    le développeur : son adresse n'existe pas dans la messagerie de
    l'entreprise, et « sa boîte » ne lisait rien. Sans dirigeant en base, on
    retombe sur sa propre adresse, comme avant.
    """
    propre = normaliser(getattr(user, "email", None))
    if (getattr(user, "role", "") or "").strip().lower() != "super_admin":
        return propre or None
    try:
        async with get_db() as conn:
            ligne = await conn.fetchrow(
                "SELECT email FROM users WHERE role = 'direction' AND actif = true "
                "ORDER BY created_at ASC LIMIT 1")
    except Exception as e:  # noqa: BLE001 - une base muette ne doit pas bloquer la lecture
        logger.warning("Boîte du dirigeant illisible : %s", e)
        ligne = None
    dirigeant = normaliser(ligne["email"] if ligne else None)
    return dirigeant or propre or None


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
        # ET DANS LA BASE : un `logger.info` part avec la rotation Docker. Depuis
        # que ce contournement couvre la direction ET autorise l'envoi au nom
        # d'un tiers, la trace doit se relire dans la Console superviseur.
        try:
            import asyncio
            from security.audit import log_action
            asyncio.create_task(log_action(
                action="mailbox_admin_access", user_id=str(user.id), success=True,
                metadata={"mailbox": cible, "envoi": bool(envoi),
                          "role": getattr(user, "role", None)}))
        except Exception:  # noqa: BLE001 - une trace absente ne bloque pas l'accès
            pass
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
