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
from config import settings

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


def boite_unique() -> Optional[str]:
    """La boîte UNIQUE de l'entreprise (mot de passe d'application), ou None.

    08/09, décision de Noa pour Duret : « un seul mail pour tout le monde ».
    Quand elle existe, c'est ELLE que tout le monde lit — sous la permission
    « Accès au mail » de la matrice des rôles (`access_mail`), et rien d'autre.
    """
    try:
        from mail.imap import boite_unique as _bu
        return _bu()
    except Exception:  # noqa: BLE001
        return None


def a_acces_au_mail(role: Optional[str]) -> bool:
    """La colonne « Accès au mail » de la matrice (08/09). Fail-closed : un rôle
    inconnu n'a rien ; le super_admin a toujours tout (`has_permission`)."""
    from security.rbac import has_permission
    return has_permission((role or "").strip(), "access_mail")


async def boites_autorisees(user) -> list[dict]:
    """Toutes les boîtes accessibles : la sienne (envoi permis) + les délégations.
    Avec une boîte unique : ELLE, pour qui a l'accès au mail."""
    unique = boite_unique()
    if unique:
        if not a_acces_au_mail(getattr(user, "role", None)):
            return []
        return [{"mailbox": unique, "can_send": True, "propre": True,
                 "libelle": "La boîte de l'entreprise (unique)"}]
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


# ── LES DOSSIERS DE LA BOÎTE PARTAGÉE (11/09, Duret) ─────────────────────
# Chaque profil lit la boîte de réception — le « mail général » — plus les
# dossiers que l'administrateur lui ouvre (`users.dossiers_mail`, migration
# 040). Seulement avec une boîte unique : ailleurs chacun lit SA boîte, et
# les dossiers n'ont pas à être découpés.

# Jeton glissé dans la liste des boîtes passée à la recherche en mémoire :
# « pas les messages envoyés ». Voir `vectorstore.rag._filtrer_mails`.
SANS_ENVOYES = "!email_sent"


async def dossiers_autorises(user_or_id) -> Optional[frozenset]:
    """Les dossiers ouverts à ce profil, ou None = aucune restriction.

    None pour un administrateur, sans boîte unique, pour un compte sans
    restriction posée, et sans la migration 040 (la colonne manque : rien
    n'était restreint, rien ne l'est). La boîte de réception n'y figure pas :
    elle est toujours ouverte.
    """
    if not boite_unique():
        return None
    user_id = str(getattr(user_or_id, "id", user_or_id) or "")
    if not user_id:
        return frozenset()
    try:
        async with get_db() as conn:
            ligne = await conn.fetchrow(
                "SELECT role, dossiers_mail FROM users WHERE id = $1::uuid AND actif = true",
                user_id)
    except Exception as e:  # noqa: BLE001
        from database.connection import schema_incomplet
        if schema_incomplet(e):
            return None
        raise
    if not ligne:
        return frozenset()                      # compte inconnu : la réception seule
    if acces_total(ligne["role"]) or ligne["dossiers_mail"] is None:
        return None
    return frozenset(str(d) for d in ligne["dossiers_mail"] if str(d or "").strip())


async def boites_pour_la_memoire(user_id: Optional[str]) -> list[str]:
    """Les boîtes que la recherche en mémoire peut montrer à ce profil — et,
    s'il n'a pas les messages envoyés, le jeton qui les écarte : la mémoire ne
    doit pas rendre ce que la lecture en direct refuserait."""
    boites = await boites_par_id(user_id)
    autorises = await dossiers_autorises(user_id)
    if autorises is not None and "envoyes" not in {a.lower() for a in autorises}:
        boites = list(boites) + [SANS_ENVOYES]
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
    unique = boite_unique()
    if unique:
        # La boîte unique, pour qui a l'accès au mail ; sinon rien du tout.
        return [unique] if (ligne and a_acces_au_mail(ligne["role"])) else []
    boites = []
    propre = normaliser(ligne["email"] if ligne else None)
    if propre:
        boites.append(propre)
    for d in await delegations(str(user_id)):
        if d["mailbox"] not in boites:
            boites.append(d["mailbox"])
    return boites


def domaines_messagerie() -> frozenset:
    """Les domaines de la messagerie d'entreprise. Un tenant en a PLUSIEURS.

    `MS_DOMAIN` / `GMAIL_DOMAIN` étaient lus comme UNE chaîne, comparée par
    suffixe : le domaine public dans le `.env`, et toute adresse sur
    l'`onmicrosoft.com` ou sur un alias historique devenait « hors domaine ».
    On accepte donc une LISTE (virgule, point-virgule ou espace), et l'ancienne
    valeur à un seul domaine continue de marcher telle quelle.

    Un ensemble VIDE veut dire « aucun domaine configuré », et alors on
    n'exclut personne : ce réglage sert à reconnaître les collègues, pas à
    barrer la porte.
    """
    # Le domaine Google se saisit aussi dans Paramètres (carte du compte de
    # service, 11/09) : la table `cles_api` d'abord, le `.env` ensuite.
    try:
        from llm.cles import valeur as _valeur
    except Exception:  # noqa: BLE001 — sans cache de clés, le .env
        def _valeur(cle):
            return getattr(settings, cle, None)
    brut = " ".join(str(_valeur(cle) or "")
                    for cle in ("ms_domain", "gmail_domain"))
    domaines = set()
    for morceau in brut.replace(",", " ").replace(";", " ").split():
        d = morceau.strip().strip("@").lower()
        if d:
            domaines.add(d)
    return frozenset(domaines)


def est_du_domaine(adresse) -> bool:
    """L'adresse appartient-elle à la messagerie de l'entreprise ?

    Sans domaine configuré, tout le monde en est : on ne refuse pas une lecture
    au motif qu'un réglage facultatif est vide.
    """
    adresse = normaliser(adresse)
    if not adresse or "@" not in adresse:
        return False
    domaines = domaines_messagerie()
    if not domaines:
        return True
    return adresse.rsplit("@", 1)[-1] in domaines


async def _boite_du_dirigeant() -> Optional[str]:
    """Le premier compte `direction` actif, par ancienneté — donc toujours le
    même tant que les comptes ne bougent pas."""
    try:
        async with get_db() as conn:
            ligne = await conn.fetchrow(
                "SELECT email FROM users WHERE role = 'direction' AND actif = true "
                "ORDER BY created_at ASC LIMIT 1")
    except Exception as e:  # noqa: BLE001 - une base muette ne doit pas bloquer la lecture
        logger.warning("Boîte du dirigeant illisible : %s", e)
        return None
    return normaliser(ligne["email"] if ligne else None) or None


async def boite_par_defaut(user) -> Optional[str]:
    """La boîte qu'on ouvre quand personne n'en nomme une.

    Pour tout le monde : la sienne. Pour le SUPER_ADMIN : celle d'un DIRIGEANT
    (03/09, Noa) — son adresse à lui n'existe pas dans la messagerie de
    l'entreprise, c'est le développeur, et « sa boîte » ne lisait rien.

    ET POUR LA DIRECTION HORS DOMAINE (07/09). Relevé le 03/09 à 15:24 :
    « combien d'échanges avec <adresse> ? » → « votre compte n'appartient pas
    au domaine de messagerie ». Un compte `direction` qui se connecte avec une
    adresse hors messagerie était exactement dans le cas du super_admin, et
    recevait un refus sec sur la seule question qu'il posait. La direction a
    déjà le droit d'ouvrir toute boîte qu'elle NOMME
    (`ROLES_ACCES_SUR_DEMANDE`) : lui donner par défaut celle d'un dirigeant
    n'ouvre aucune porte de plus, et `verifier_acces` reste le seul contrôle.

    Les autres rôles ne bougent pas : pour eux, une boîte que personne n'a
    nommée ne s'ouvre toujours pas (règle du 01/09).
    """
    propre = normaliser(getattr(user, "email", None))
    role = (getattr(user, "role", "") or "").strip().lower()
    unique = boite_unique()
    if unique:
        # LA BOÎTE UNIQUE (08/09) : la même pour tout le monde. Sans l'accès au
        # mail, personne — `verifier_acces` le dira avec la raison.
        return unique
    if role == "super_admin" or (role == "direction" and not est_du_domaine(propre)):
        return (await _boite_du_dirigeant()) or propre or None
    return propre or None


async def verifier_acces(user, mailbox: Optional[str], envoi: bool = False) -> str:
    """Vérifie l'accès et retourne la boîte normalisée. Lève 403 sinon.

    `envoi=True` exige en plus le droit d'écriture (rédiger AU NOM DE cette
    boîte). Une délégation en lecture seule permet de consulter et de trier,
    pas de préparer un message signé de quelqu'un d'autre.
    """
    cible = normaliser(mailbox)
    if not cible:
        raise AccesBoiteRefuse("Aucune boîte mail précisée.")

    # LA COLONNE « ACCÈS AU MAIL » (08/09) : sans elle, aucune boîte, la
    # sienne comprise. Semée VRAIE pour tous les rôles existants (migration
    # 039) : rien ne change tant que la direction ne décoche pas.
    if not a_acces_au_mail(getattr(user, "role", None)):
        raise AccesBoiteRefuse(
            "Votre rôle n'a pas l'accès au mail : la direction peut l'accorder dans "
            "Paramètres → Permissions, colonne « Accès au mail ».")

    unique = boite_unique()
    if unique:
        # LA BOÎTE UNIQUE : c'est elle, ou rien. Une autre adresse n'existe pas
        # ici — on le dit, sans révéler quoi que ce soit d'autre.
        if cible == unique:
            return cible
        raise AccesBoiteRefuse(
            f"La messagerie de l'entreprise est une boîte unique ({unique}) : "
            f"« {cible} » n'est pas une boîte accessible ici.")

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
