import logging
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from auth import appareil
from config import settings
from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import (
    has_permission, can_manage_agent_permission,
    role_agent_default, ROLE_AGENT_DEFAULTS,
)
from security.audit import log_action

router = APIRouter()
logger = logging.getLogger("duret.routers.users")

# Ce que chaque niveau peut créer
DIRECTION_CREATABLE_ROLES   = {"commercial", "bureau_etudes", "conducteur", "administratif", "terrain"}
SUPER_ADMIN_CREATABLE_ROLES = {"super_admin", "direction"} | DIRECTION_CREATABLE_ROLES

AGENTS = ("agent1", "agent2", "agent3")

# LE LIEN D'ACCÈS DÉLIVRÉ À LA MAIN (03/09, demande de Noa : « avec mon compte
# admin, pouvoir leur faire accéder à l'interface même s'ils ne reçoivent pas le
# mail magique »).
#
# 24 h, et non les 15 minutes du lien envoyé par mail. Les deux ne voyagent pas
# de la même façon : le lien du mail arrive en trois secondes et se clique dans
# la foulée ; celui-ci passe par un humain — un message, un SMS, un poste qu'on
# installe à côté de quelqu'un — et une fenêtre de quinze minutes le rendrait
# inutilisable le jour où il sert vraiment (une boîte en panne, un salarié
# injoignable jusqu'au soir).
#
# Ce qui borne le risque n'est pas la durée mais le RESTE : usage unique (la
# colonne `used` de `verification_tokens`), périmètre limité aux comptes que
# l'on gère déjà, et trace dans l'audit_log.
LIEN_ACCES_EXPIRE_HEURES = 24
# Combien de fois un lien d'accès peut servir, au plus. Cinq : de quoi équiper
# un poste, un téléphone et une tablette avec de la marge — au-delà, ce n'est
# plus un lien remis à quelqu'un, c'est une porte ouverte.
LIEN_ACCES_UTILISATIONS_MAX = 5


class LienConnexionRequest(BaseModel):
    """`utilisations` : combien d'appareils pourront franchir la porte avec ce
    lien (03/09, demande de Noa : « PC + téléphone »). 1 par défaut."""
    utilisations: int = 1


class CreateUserRequest(BaseModel):
    # Vide pour un profil métier : la boîte de l'entreprise (13/09).
    email: str = ""
    name: Optional[str] = None
    role: str = "terrain"
    quota_mensuel: Optional[int] = None
    # Les dossiers de la boîte partagée que ce profil lira, EN PLUS de la
    # boîte de réception (11/09). None = aucune restriction.
    dossiers_mail: Optional[list[str]] = None
    # Le code de la carte de connexion (13/09) : obligatoire pour la direction
    # sur la boîte de l'entreprise, facultatif pour les autres profils.
    code_pin: Optional[str] = None


class RoleRequest(BaseModel):
    role: str


class ModifierProfilRequest(BaseModel):
    """(14/09) Le nom et l'adresse d'un profil. None = inchangé."""
    name: Optional[str] = None
    email: Optional[str] = None


class CodeRequest(BaseModel):
    # Vide ou absent : retirer le code.
    code: Optional[str] = None


class DossiersMailRequest(BaseModel):
    """None = aucune restriction (tout ce que la boîte contient) ; une liste,
    même vide = la boîte de réception plus ces dossiers-là."""
    dossiers: Optional[list[str]] = None


class SetPermissionRequest(BaseModel):
    has_access: bool


class ScheduleUpdateRequest(BaseModel):
    schedule_start_hour: Optional[int] = None  # 0-23, None = garder l'existant
    schedule_end_hour: Optional[int] = None    # 1-24, None = garder l'existant
    bypass_schedule: Optional[bool] = None     # None = garder l'existant


def peut_ouvrir_pour(role_gestionnaire: str, role_cible: str) -> bool:
    """Qui peut fabriquer un lien d'accès pour qui.

    Même hiérarchie que la désactivation, et pour la même raison : ouvrir une
    session à la place de quelqu'un est un pouvoir au moins aussi fort que lui
    couper l'accès. La direction n'atteint donc que les rôles métier — sans
    quoi elle se délivrerait un accès super_admin en deux clics.

    Fonction pure, à dessein : c'est elle que le banc exécute.
    """
    if role_gestionnaire == "super_admin":
        return True
    if role_gestionnaire == "direction":
        return role_cible in DIRECTION_CREATABLE_ROLES
    return False


def _effective_permissions(role: str, explicit: dict[str, bool]) -> dict[str, bool]:
    """Fusionne les défauts du rôle avec les overrides explicites."""
    defaults = ROLE_AGENT_DEFAULTS.get(role, {})
    return {
        agent: explicit.get(agent, defaults.get(agent, False))
        for agent in AGENTS
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


class MonCodeRequest(BaseModel):
    code: Optional[str] = None


@router.get("/me/code")
async def mon_code(current_user: User = Depends(get_current_user)):
    """Le code de SA carte (14/09, Noa : « chacun doit pouvoir modifier le sien
    depuis son espace »). Déclarée avant `/{user_id}/…` : « me » n'est pas un
    identifiant."""
    from auth import profils as _profils
    ligne = None
    for requete in ("SELECT email, role, code_pin_hash, code_pin_chiffre FROM users WHERE id = $1",
                    "SELECT email, role, code_pin_hash, NULL AS code_pin_chiffre FROM users WHERE id = $1"):
        try:
            async with get_db() as conn:
                ligne = await conn.fetchrow(requete, current_user.id)
            break
        except Exception as e:  # noqa: BLE001
            from database.connection import schema_incomplet
            if not schema_incomplet(e):
                raise
    if not ligne:
        return {"a_code": False, "code": None, "obligatoire": False, "possible": False}
    return {"a_code": bool(ligne["code_pin_hash"]),
            "code": _profils.dechiffrer_code(ligne["code_pin_chiffre"]),
            "obligatoire": await _profils.code_obligatoire(ligne["role"], ligne["email"]),
            # (15/09) Chacun change le sien, l'administrateur compris : c'est
            # son code qui ouvre le bouton « Admin » depuis que le lien est coupé.
            "possible": True,
            "code_par_defaut": (ligne["role"] in _profils.ROLES_CARTE_ADMIN
                                and not ligne["code_pin_hash"])}


@router.put("/me/code")
async def changer_mon_code(body: MonCodeRequest, current_user: User = Depends(get_current_user)):
    """Pose, change ou retire le code de SA carte. Aucune permission requise :
    la session prouve déjà la personne (elle est entrée par sa carte, et donc
    par son code s'il en avait un)."""
    from auth import profils as _profils
    code = (body.code or "").strip()
    if code and not _profils.code_valide(code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Le code fait 4 à 6 chiffres.")
    if not code and current_user.role in _profils.ROLES_CARTE_ADMIN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=(
            "Un administrateur entre par son code : changez-le plutôt que de le retirer "
            "(sans code posé, c'est le code par défaut qui l'ouvre)."))
    async with get_db() as conn:
        moi = await conn.fetchrow("SELECT email, role FROM users WHERE id = $1", current_user.id)
    if not code and moi and await _profils.code_obligatoire(moi["role"], moi["email"]):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=(
            "Un profil de direction sur une adresse partagée garde un code : changez-le "
            "plutôt que de le retirer."))
    async with get_db() as conn:
        await _poser_code(conn, current_user.id, code or None)
    await log_action(action="code_carte_modifie", user_id=str(current_user.id),
                     metadata={"target_user_id": str(current_user.id), "par_soi": True,
                               "retire": not code})
    return {"a_code": bool(code), "code": code or None}


@router.get("/")
async def list_users(current_user: User = Depends(get_current_user)):
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    # `dossiers_mail` vient de la migration 040 : sans elle, la liste se lit
    # quand même (colonne remplacée par NULL) — l'onglet Utilisateurs ne doit
    # pas tomber pour une restriction qui n'existe pas encore.
    requete = """
            SELECT
                u.id, u.email, u.name, u.role, u.actif, u.quota_mensuel,
                u.bypass_schedule, u.schedule_start_hour, u.schedule_end_hour,
                u.created_at, u.last_login, u.dossiers_mail,
                uap_a1.has_access AS explicit_agent1,
                uap_a2.has_access AS explicit_agent2,
                uap_a3.has_access AS explicit_agent3
            FROM users u
            LEFT JOIN user_agent_permissions uap_a1
                ON u.id = uap_a1.user_id AND uap_a1.agent = 'agent1'
            LEFT JOIN user_agent_permissions uap_a2
                ON u.id = uap_a2.user_id AND uap_a2.agent = 'agent2'
            LEFT JOIN user_agent_permissions uap_a3
                ON u.id = uap_a3.user_id AND uap_a3.agent = 'agent3'
            -- LA DIRECTION NE VOIT PAS LES SUPER_ADMIN (01/09, demande de
            -- Noa) : elle n'a aucun pouvoir sur eux, elle ne doit même pas
            -- les voir dans la liste. Le filtre est SERVEUR : un écran ne
            -- suffit pas, l'API ne doit pas les livrer.
            WHERE ($1::boolean OR u.role <> 'super_admin')
            ORDER BY u.created_at DESC
            """
    async with get_db() as conn:
        try:
            rows = await conn.fetch(requete, current_user.role == "super_admin")
        except Exception as e:  # noqa: BLE001
            from database.connection import schema_incomplet
            if not schema_incomplet(e):
                raise
            rows = await conn.fetch(
                requete.replace("u.dossiers_mail,", "NULL::text[] AS dossiers_mail,"),
                current_user.role == "super_admin")

    # Quelle carte a un code (041) — jamais l'empreinte — et le code LUI-MÊME
    # (042, 14/09 : Noa veut « les voir et les modifier après »), déchiffré
    # seulement pour les profils que l'on gère : la direction ne lit pas le
    # code d'un super_admin ni d'une autre direction. Lu à part : sans les
    # migrations, la liste reste lisible.
    from auth import profils as _profils
    avec_code: set = set()
    chiffres: dict = {}
    for requete_code in ("SELECT id, code_pin_chiffre FROM users WHERE code_pin_hash IS NOT NULL",
                         "SELECT id, NULL AS code_pin_chiffre FROM users WHERE code_pin_hash IS NOT NULL"):
        try:
            async with get_db() as conn:
                lignes_code = await conn.fetch(requete_code)
            avec_code = {str(r["id"]) for r in lignes_code}
            chiffres = {str(r["id"]): r["code_pin_chiffre"] for r in lignes_code}
            break
        except Exception as e:  # noqa: BLE001
            from database.connection import schema_incomplet
            if not schema_incomplet(e):
                raise

    result = []
    codes_lus: list[str] = []
    a_rechiffrer: dict = {}
    for row in rows:
        d = dict(row)
        d["a_code"] = str(d["id"]) in avec_code
        lisible = (str(d["id"]) == str(current_user.id)
                   or peut_ouvrir_pour(current_user.role, d["role"]))
        d["code"] = _profils.dechiffrer_code(chiffres.get(str(d["id"]))) if lisible and d["a_code"] else None
        if d["code"] and str(d["id"]) != str(current_user.id):
            codes_lus.append(str(d["id"]))
        # ROTATION DE LA CLÉ (16/09, audit D-19) : un code encore chiffré avec
        # l'ancienne clé (dérivée du secret JWT) est réécrit avec la clé
        # dédiée, dès qu'on le relit. Aucune migration, aucune perte.
        if d["code"]:
            neuf = _profils.rechiffre_avec_la_cle_du_jour(chiffres.get(str(d["id"])))
            if neuf:
                a_rechiffrer[str(d["id"])] = neuf
        explicit = {
            a: d.pop(f"explicit_{a}")
            for a in AGENTS
            if d.get(f"explicit_{a}") is not None
        }
        # clean remaining None keys
        for a in AGENTS:
            d.pop(f"explicit_{a}", None)
        d["agent_permissions"] = _effective_permissions(d["role"], explicit)
        result.append(d)

    # LIRE LE CODE DE QUELQU'UN D'AUTRE SE TRACE (16/09, audit D-19) : c'est un
    # accès administratif, pas une lecture d'écran ordinaire. Jamais le code
    # lui-même dans le journal — seulement combien, et pour qui.
    if codes_lus:
        await log_action(action="codes_cartes_consultes", user_id=str(current_user.id),
                         metadata={"profils": len(codes_lus), "ids": codes_lus[:20]})
    for user_id, chiffre in a_rechiffrer.items():
        try:
            async with get_db() as conn:
                await conn.execute("UPDATE users SET code_pin_chiffre = $2 WHERE id = $1::uuid",
                                   user_id, chiffre)
        except Exception as e:  # noqa: BLE001 — la rotation ne casse jamais la liste
            logger.warning("Code non rechiffré (%s)", type(e).__name__)
            break

    return result


@router.post("/")
async def create_user(
    body: CreateUserRequest,
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    allowed_roles = (
        SUPER_ADMIN_CREATABLE_ROLES if current_user.role == "super_admin"
        else DIRECTION_CREATABLE_ROLES
    )
    if body.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Vous ne pouvez pas créer un utilisateur avec le rôle '{body.role}'",
        )

    # PLUSIEURS PROFILS SUR UNE MÊME ADRESSE (11/09, Duret : « tout le monde a
    # le même mail »). Permis pour les rôles métier, avec un prénom distinct —
    # jamais pour un administrateur, ni sur l'adresse d'un administrateur :
    # c'est `auth/profils.refus_creation` qui tranche, et le banc l'exécute.
    from auth import profils as _profils
    body.email = (body.email or "").strip()
    body.name = (body.name or "").strip() or None
    # LA BOÎTE DE L'ENTREPRISE PAR DÉFAUT (13/09) : un profil métier sans
    # adresse prend celle que tout le monde partage — c'est elle qui le met
    # sur la page de connexion. Un administrateur garde toujours la sienne.
    boite = await _profils.adresse_partagee()
    if not body.email and boite and not _profils.est_admin(body.role):
        body.email = boite
    if not body.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="L'adresse est obligatoire.")
    code = (getattr(body, "code_pin", None) or "").strip()
    if code and not _profils.code_valide(code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Le code d'une carte fait 4 à 6 chiffres.")
    existants = await _profils.profils_de(body.email, actifs=False)
    # (14/09) Une adresse déjà portée par un autre profil suit AUSSI les règles
    # des cartes, boîte reliée ou non : Noa crée les profils sur l'adresse de
    # l'entreprise AVANT de relier la boîte, et la direction qui la partage
    # doit alors avoir un code, comme sur la boîte.
    partagee = _profils.meme_adresse(body.email, boite) or bool(existants)
    # Sur la boîte de l'entreprise, les règles de la PAGE DE CONNEXION (13/09) :
    # la direction y vit derrière un code, le super_admin jamais. Ailleurs,
    # celles des adresses partagées par lien magique (11/09).
    refus = (_profils.refus_sur_boite(body.role, body.name, bool(code), existants) if partagee
             else _profils.refus_creation(body.role, body.name, existants))
    if refus:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refus)
    # Un administrateur lit tout : une restriction posée sur lui ne serait pas
    # appliquée (`dossiers_autorises`), autant ne pas l'écrire.
    dossiers = None if _profils.est_admin(body.role) else _nettoyer_dossiers(body.dossiers_mail)
    if (existants or partagee) and dossiers is None and not _profils.est_admin(body.role):
        # Un profil d'une boîte PARTAGÉE commence par la boîte de réception
        # seule : c'est l'administrateur qui ouvre les autres dossiers.
        dossiers = []

    async with get_db() as conn:
        # LA COLONNE EST OMISE QUAND AUCUN QUOTA N'EST DONNÉ, et ce n'est pas
        # une coquetterie : `quota_mensuel` est `NOT NULL DEFAULT 50`, et
        # passer explicitement NULL N'ACTIVE PAS le défaut — en SQL, un défaut
        # ne s'applique QUE si la colonne est absente de l'INSERT. Le
        # formulaire n'envoie pas de quota, donc chaque création partait avec
        # un NULL explicite et tombait sur la contrainte : « impossible de
        # créer un utilisateur », sans que rien à l'écran ne dise pourquoi.
        #
        # On omet la colonne plutôt que d'écrire `COALESCE($4, 50)` : recopier
        # le défaut ici en ferait un second endroit à tenir à jour, et le jour
        # où la migration change, les deux diraient des choses différentes.
        if body.quota_mensuel is None:
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, name, role)
                VALUES ($1, $2, $3)
                RETURNING id, email, name, role, actif, quota_mensuel, created_at
                """,
                body.email, body.name, body.role,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, name, role, quota_mensuel)
                VALUES ($1, $2, $3, $4)
                RETURNING id, email, name, role, actif, quota_mensuel, created_at
                """,
                body.email, body.name, body.role, body.quota_mensuel,
            )

        if dossiers is not None:
            await _poser_dossiers(conn, row["id"], dossiers)
        if code:
            await _poser_code(conn, row["id"], code)

    await log_action(
        action="user_created",
        user_id=str(current_user.id),
        metadata={"new_email": body.email, "new_role": body.role,
                  "profil_partage": bool(existants)},
    )
    d = dict(row)
    d["dossiers_mail"] = dossiers
    d["agent_permissions"] = _effective_permissions(d["role"], {})
    return d


def _nettoyer_dossiers(dossiers: Optional[list[str]]) -> Optional[list[str]]:
    """Noms de dossiers dédoublonnés, sans la boîte de réception (toujours
    lisible) ; None reste None (aucune restriction)."""
    if dossiers is None:
        return None
    propres: list[str] = []
    for d in dossiers:
        nom = str(d or "").strip()
        if nom and nom.upper() != "INBOX" and nom not in propres:
            propres.append(nom[:200])
    return propres[:100]


async def _poser_code(conn, user_id, code: Optional[str]) -> None:
    """Écrit l'EMPREINTE du code (ou le retire) et remet les essais à zéro.
    Sans la migration 041, le refus NOMME la migration : un code qu'on croit
    posé et qui ne l'est pas laisserait la carte ouverte."""
    from auth import profils as _profils
    try:
        await conn.execute(
            "UPDATE users SET code_pin_hash = $1, code_pin_chiffre = $3, code_pin_echecs = 0, "
            "code_pin_bloque_jusqu = NULL WHERE id = $2::uuid",
            _profils.hacher_code(code) if code else None, str(user_id),
            _profils.chiffrer_code(code) if code else None)
        return
    except Exception as e:  # noqa: BLE001
        from database.connection import schema_incomplet
        if not schema_incomplet(e):
            raise
    # Sans la 042 : le code ouvre la carte, mais ne se relira pas à l'écran.
    try:
        await conn.execute(
            "UPDATE users SET code_pin_hash = $1, code_pin_echecs = 0, code_pin_bloque_jusqu = NULL "
            "WHERE id = $2::uuid",
            _profils.hacher_code(code) if code else None, str(user_id))
    except Exception as e:  # noqa: BLE001
        from database.connection import schema_incomplet
        if schema_incomplet(e):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Le code des cartes exige la migration 041 (041_code_profil.sql).")
        raise


async def _poser_dossiers(conn, user_id, dossiers: Optional[list[str]]) -> None:
    """Écrit la liste — et reste muet sans la migration 040 (colonne absente) :
    la création du compte ne doit pas tomber pour une restriction."""
    try:
        await conn.execute("UPDATE users SET dossiers_mail = $1 WHERE id = $2::uuid",
                           dossiers, str(user_id))
    except Exception as e:  # noqa: BLE001
        from database.connection import schema_incomplet
        if not schema_incomplet(e):
            raise


@router.get("/dossiers-mail")
async def dossiers_de_la_boite(current_user: User = Depends(get_current_user)):
    """Les dossiers de la boîte partagée, pour les cases à cocher de l'écran.

    Lus en direct (IMAP LIST). Les dossiers systèmes qui montreraient TOUT —
    « Tous les messages », la corbeille, les brouillons — ne sont pas proposés :
    cocher « Tous les messages » viderait la restriction de son sens.
    """
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    import asyncio
    from llm.cles import rafraichir
    await rafraichir()
    from mail import imap
    if not imap.configure():
        return {"dossiers": [], "adresse": None, "erreur": "Aucune boîte de l'entreprise n'est reliée "
                "(Paramètres → Clés API → « La boîte mail de l'entreprise »)."}
    # L'adresse partagée voyage avec les dossiers : l'écran la pose d'office
    # dans le formulaire d'un nouveau profil (13/09, page de connexion par cartes).
    adresse = imap.boite_unique()
    try:
        return {"dossiers": await asyncio.to_thread(imap.dossiers_proposables), "adresse": adresse, "erreur": ""}
    except Exception as e:  # noqa: BLE001
        return {"dossiers": [], "adresse": adresse, "erreur": f"Les dossiers n'ont pas pu être lus : {str(e)[:160]}"}


@router.put("/{user_id}/dossiers-mail")
async def poser_dossiers_mail(user_id: UUID, body: DossiersMailRequest,
                              current_user: User = Depends(get_current_user)):
    """Les dossiers que ce profil lit, en plus de la boîte de réception."""
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    async with get_db() as conn:
        cible = await conn.fetchrow("SELECT id, role FROM users WHERE id = $1", user_id)
        if not cible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
        if not peut_ouvrir_pour(current_user.role, cible["role"]):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")
        dossiers = _nettoyer_dossiers(body.dossiers)
        await _poser_dossiers(conn, user_id, dossiers)
    await log_action(action="dossiers_mail_modifies", user_id=str(current_user.id),
                     metadata={"target_user_id": str(user_id),
                               "restreint": dossiers is not None,
                               "nombre": len(dossiers or [])})
    return {"user_id": str(user_id), "dossiers_mail": dossiers}


@router.put("/{user_id}/permissions/{agent}")
async def set_agent_permission(
    user_id: UUID,
    agent: str,
    body: SetPermissionRequest,
    current_user: User = Depends(get_current_user),
):
    if agent not in AGENTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent invalide")
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        target = await conn.fetchrow("SELECT id, role FROM users WHERE id = $1", user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    if not can_manage_agent_permission(current_user.role, agent, target["role"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Seul un super admin peut gérer les permissions Agent 3"
                if agent == "agent3"
                else "Vous ne pouvez pas modifier les permissions de cet utilisateur"
            ),
        )

    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO user_agent_permissions (user_id, agent, has_access, granted_by)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, agent) DO UPDATE
                SET has_access = $3, granted_by = $4, granted_at = NOW()
            """,
            user_id, agent, body.has_access, current_user.id,
        )

    await log_action(
        action="permission_changed",
        user_id=str(current_user.id),
        metadata={
            "target_user_id": str(user_id),
            "agent": agent,
            "has_access": body.has_access,
        },
    )
    return {"user_id": str(user_id), "agent": agent, "has_access": body.has_access}


@router.post("/{user_id}/lien-connexion")
async def creer_lien_connexion(
    user_id: UUID,
    body: LienConnexionRequest | None = None,
    current_user: User = Depends(get_current_user),
):
    """Fabrique un lien de connexion à remettre EN MAIN PROPRE.

    POURQUOI (03/09). Le lien magique suppose que le mail arrive : boîte mal
    configurée, message en indésirable, salarié sans accès à sa messagerie, ou
    tout simplement un poste qu'on installe pour quelqu'un. Dans ces cas-là
    l'administration n'avait AUCUN moyen d'ouvrir l'accès — il fallait réparer
    la messagerie d'abord.

    Le lien rendu est exactement celui du mail : même table, même page
    `/verify`, même consommation à usage unique, et il pose la session
    d'appareil comme n'importe quelle connexion. Rien n'est contourné — on
    change seulement le TRANSPORT.

    ⚠️ Ce lien ouvre la session À LA PLACE de la personne : il se transmet
    directement à elle, et l'écran le dit.
    """
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    # C'est aussi un lien magique : coupé avec lui (15/09). Un profil entre par
    # sa carte, et son code se règle dans la colonne Code.
    if not getattr(settings, "lien_magique_actif", True):
        raise HTTPException(status_code=status.HTTP_410_GONE,
                            detail="Les liens de connexion sont désactivés : chaque profil entre par sa carte.")

    async with get_db() as conn:
        cible = await conn.fetchrow(
            "SELECT id, email, name, role, actif FROM users WHERE id = $1", user_id
        )
    if not cible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    if not peut_ouvrir_pour(current_user.role, cible["role"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")
    if not cible["actif"]:
        # Le lien marcherait jusqu'à /verify puis serait refusé là-bas, sans
        # rien expliquer. Autant le dire ici, avec le geste à faire.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce compte est désactivé : réactivez-le avant de créer un lien.",
        )

    # Borné des deux côtés : zéro ou un négatif serait un lien mort, plus que le
    # plafond serait une porte ouverte. On ramène, on ne refuse pas — l'écran
    # ne propose que des valeurs permises, une valeur hors bornes vient d'un
    # appel à la main.
    utilisations = max(1, min(int((body.utilisations if body else 1) or 1),
                              LIEN_ACCES_UTILISATIONS_MAX))
    jeton = secrets.token_urlsafe(32)
    expire_le = datetime.now(timezone.utc) + timedelta(hours=LIEN_ACCES_EXPIRE_HEURES)
    migration_absente = False
    async with get_db() as conn:
        try:
            await conn.execute(
                """INSERT INTO verification_tokens (email, token, expires_at, utilisations_max)
                   VALUES ($1, $2, $3, $4)""",
                cible["email"], jeton, expire_le, utilisations,
            )
        except Exception as e:  # noqa: BLE001
            from database.connection import schema_incomplet
            if not schema_incomplet(e):
                raise
            # Migration 035 absente : le lien existe, mais il ne vaudra qu'UNE
            # fois — et la réponse le DIT, plutôt que de promettre deux
            # appareils à quelqu'un qui n'en aura qu'un.
            migration_absente = True
            utilisations = 1
            await conn.execute(
                "INSERT INTO verification_tokens (email, token, expires_at) VALUES ($1, $2, $3)",
                cible["email"], jeton, expire_le,
            )

    await log_action(
        action="lien_acces_cree",
        user_id=str(current_user.id),
        metadata={"target_user_id": str(user_id), "utilisations": utilisations},
    )

    # `quote` sur les deux valeurs : un « + » dans une adresse se décode en
    # espace côté navigateur, et le lien tomberait en « Lien invalide » pour la
    # seule personne dont l'adresse en porte un.
    # `profil` (11/09) : sur une adresse partagée, le lien remis par
    # l'administrateur ouvre CE prénom, sans passer par l'écran des cartes.
    url = (f"{settings.app_url}/verify"
           f"?token={quote(jeton, safe='')}&email={quote(cible['email'], safe='')}"
           f"&profil={quote(str(cible['id']), safe='')}")
    return {
        "url": url,
        "email": cible["email"],
        "nom": cible["name"],
        "valable_heures": LIEN_ACCES_EXPIRE_HEURES,
        "expire_le": expire_le.isoformat(),
        "utilisations": utilisations,
        "migration_absente": "035_lien_multi_usages" if migration_absente else None,
    }


@router.put("/{user_id}/deactivate")
async def deactivate_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        target = await conn.fetchrow("SELECT role FROM users WHERE id = $1", user_id)
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
        if current_user.role == "direction" and target["role"] not in DIRECTION_CREATABLE_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")
        await conn.execute("UPDATE users SET actif = false WHERE id = $1", user_id)

    # Ses appareils restaient « connectés » dans la liste (03/09). L'accès était
    # déjà coupé — `compte_de` et `get_current_user` exigent tous deux un compte
    # actif — mais laisser les lignes ouvertes ferait mentir l'écran, et une
    # réactivation rouvrirait des postes que plus personne ne surveille.
    await appareil.revoquer_tout(user_id)

    await log_action(
        action="user_deactivated",
        user_id=str(current_user.id),
        metadata={"target_user_id": str(user_id)},
    )
    return {"status": "deactivated"}


@router.put("/{user_id}/reactivate")
async def reactivate_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        target = await conn.fetchrow("SELECT role FROM users WHERE id = $1", user_id)
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
        if current_user.role == "direction" and target["role"] not in DIRECTION_CREATABLE_ROLES:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")
        await conn.execute("UPDATE users SET actif = true WHERE id = $1", user_id)

    return {"status": "reactivated"}


@router.put("/{user_id}/role")
async def changer_role(user_id: UUID, body: RoleRequest,
                       current_user: User = Depends(get_current_user)):
    """CHANGER LE RÔLE d'un profil (13/09, demande de Noa : « on doit pouvoir
    dire si c'est la direction, le commercial, l'administratif… »).

    Le rôle décide de tout le reste — les fonctions ouvertes (matrice des
    permissions), les niveaux de documents et de connaissances visibles, les
    dossiers du NAS. Il se choisissait à la création et ne se changeait plus.
    Même hiérarchie que la création : la direction ne touche que les rôles
    métier et n'en fait jamais un administrateur. On ne change pas son propre
    rôle. Sur la boîte de l'entreprise, les règles de la page de connexion.
    Effet immédiat côté serveur (le rôle est relu en base à chaque requête).
    """
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    if str(user_id) == str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="On ne change pas son propre rôle : demandez à un autre administrateur.")
    permis = (SUPER_ADMIN_CREATABLE_ROLES if current_user.role == "super_admin"
              else DIRECTION_CREATABLE_ROLES)
    if body.role not in permis:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Vous ne pouvez pas attribuer le rôle « {body.role} ».")
    from auth import profils as _profils
    async with get_db() as conn:
        cible = await conn.fetchrow("SELECT id, email, name, role FROM users WHERE id = $1", user_id)
    if not cible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    if not peut_ouvrir_pour(current_user.role, cible["role"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")
    if cible["role"] == body.role:
        return {"user_id": str(user_id), "role": body.role}

    boite = await _profils.adresse_partagee()
    existants = await _profils.profils_de(cible["email"], actifs=False)
    moi = next((e for e in existants if str(e["id"]) == str(user_id)), {})
    if _profils.meme_adresse(cible["email"], boite):
        refus = _profils.refus_sur_boite(body.role, cible["name"], _profils.a_un_code(moi),
                                         existants, soi=str(user_id))
    else:
        autres = [e for e in existants if str(e["id"]) != str(user_id)]
        refus = (_profils.refus_creation(body.role, cible["name"], autres)
                 if autres and _profils.est_admin(body.role) else None)
    if refus:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refus)

    async with get_db() as conn:
        await conn.execute("UPDATE users SET role = $1 WHERE id = $2", body.role, user_id)
    await log_action(action="user_role_changed", user_id=str(current_user.id),
                     metadata={"target_user_id": str(user_id), "ancien": cible["role"],
                               "nouveau": body.role})
    return {"user_id": str(user_id), "role": body.role,
            "agent_permissions": _effective_permissions(body.role, {})}


@router.put("/{user_id}/code")
async def poser_code(user_id: UUID, body: CodeRequest,
                     current_user: User = Depends(get_current_user)):
    """Pose, change ou retire le code de la carte de connexion d'un profil."""
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    from auth import profils as _profils
    code = (body.code or "").strip()
    if code and not _profils.code_valide(code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Le code d'une carte fait 4 à 6 chiffres.")
    async with get_db() as conn:
        cible = await conn.fetchrow("SELECT id, email, role FROM users WHERE id = $1", user_id)
    if not cible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    if str(user_id) != str(current_user.id) and not peut_ouvrir_pour(current_user.role, cible["role"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")
    if not code and await _profils.code_obligatoire(cible["role"], cible["email"]):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=(
            "Un profil de direction sur une adresse partagée garde un code : "
            "changez-le plutôt que de le retirer."))
    async with get_db() as conn:
        await _poser_code(conn, user_id, code or None)
    await log_action(action="code_carte_modifie", user_id=str(current_user.id),
                     metadata={"target_user_id": str(user_id), "retire": not code})
    return {"user_id": str(user_id), "a_code": bool(code), "code": code or None}


@router.put("/{user_id}")
async def modifier_utilisateur(user_id: UUID, body: ModifierProfilRequest,
                               current_user: User = Depends(get_current_user)):
    """MODIFIER UN PROFIL (14/09, demande de Noa) : son nom et son adresse.

    Le rôle, les dossiers du mail et le code ont leurs propres routes. Même
    hiérarchie que le reste : la direction ne touche que les rôles métier.
    Une adresse partagée suit les règles des cartes (nom obligatoire et unique
    sur l'adresse, direction avec code, jamais un super_admin).
    """
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    from auth import profils as _profils
    async with get_db() as conn:
        cible = await conn.fetchrow("SELECT id, email, name, role FROM users WHERE id = $1", user_id)
    if not cible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
    if str(user_id) != str(current_user.id) and not peut_ouvrir_pour(current_user.role, cible["role"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")

    nom = cible["name"] if body.name is None else ((body.name or "").strip() or None)
    email = cible["email"] if body.email is None else (body.email or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="L'adresse est obligatoire.")

    existants = await _profils.profils_de(email, actifs=False)
    moi = next((e for e in await _profils.profils_de(cible["email"], actifs=False)
                if str(e["id"]) == str(user_id)), {})
    autres = [e for e in existants if str(e["id"]) != str(user_id)]
    if _profils.meme_adresse(email, await _profils.adresse_partagee()) or autres:
        refus = _profils.refus_sur_boite(cible["role"], nom, _profils.a_un_code(moi),
                                         existants, soi=str(user_id))
        if refus:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refus)

    async with get_db() as conn:
        try:
            await conn.execute("UPDATE users SET name = $1, email = $2 WHERE id = $3",
                               nom, email, user_id)
        except Exception as e:  # noqa: BLE001
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail=f"Un profil « {nom or ''} » existe déjà sur cette adresse.")
            raise
    await log_action(action="user_modified", user_id=str(current_user.id),
                     metadata={"target_user_id": str(user_id),
                               "nom_change": nom != cible["name"],
                               "adresse_changee": not _profils.meme_adresse(email, cible["email"])})
    return {"id": str(user_id), "name": nom, "email": email}


# Les colonnes qui désignent un utilisateur SANS « ON DELETE » : sans elles, le
# DELETE serait refusé par la base. Lues dans le catalogue plutôt qu'écrites à
# la main, pour qu'une table ajoutée demain ne rende pas la suppression
# impossible en silence.
_REFERENCES_SANS_CASCADE = """
    SELECT c.conrelid::regclass::text AS tbl, a.attname AS col, NOT a.attnotnull AS nullable
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass
      AND c.confdeltype IN ('a', 'r')
"""


def _ident(nom: str) -> str:
    return '"' + str(nom).replace('"', '""') + '"'


@router.delete("/{user_id}")
async def supprimer_utilisateur(user_id: UUID, current_user: User = Depends(get_current_user)):
    """SUPPRIMER COMPLÈTEMENT UN PROFIL (14/09, demande de Noa).

    Désactiver le laisse en base ; ceci l'efface, avec tout ce qui n'appartient
    qu'à lui (conversations, messages, tâches, consignes, validations, appareils,
    suivis — les tables en `ON DELETE CASCADE`). Ce qui a seulement été FAIT
    par lui garde sa ligne sans son nom (journal d'audit, réglages qu'il a
    modifiés, trames créées : la colonne passe à NULL) ; ce qui ne peut pas
    rester orphelin (sa consommation d'API) part. Une seule transaction : ou
    tout part, ou rien.

    On ne se supprime pas soi-même ; la direction ne supprime que des rôles
    métier ; le dernier super_admin actif ne se supprime pas.
    """
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    if str(user_id) == str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="On ne supprime pas son propre profil : demandez à un autre administrateur.")
    async with get_db() as conn:
        cible = await conn.fetchrow("SELECT id, email, name, role FROM users WHERE id = $1", user_id)
        if not cible:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
        if not peut_ouvrir_pour(current_user.role, cible["role"]):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")
        if cible["role"] == "super_admin":
            restants = await conn.fetchval(
                "SELECT count(*) FROM users WHERE role = 'super_admin' AND actif = true AND id <> $1", user_id)
            if not restants:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="C'est le dernier super administrateur actif : il ne se supprime pas.")
        async with conn.transaction():
            # Les tables sous RLS forcée (consommation d'API) ne se nettoient
            # qu'avec un contexte d'administration, local à la transaction.
            await conn.execute("SELECT set_config('app.current_user_id', $1, true)", str(current_user.id))
            await conn.execute("SELECT set_config('app.current_role', 'super_admin', true)")
            for ref in await conn.fetch(_REFERENCES_SANS_CASCADE):
                col = _ident(ref["col"])
                if ref["nullable"]:
                    await conn.execute(f"UPDATE {ref['tbl']} SET {col} = NULL WHERE {col} = $1", user_id)
                else:
                    await conn.execute(f"DELETE FROM {ref['tbl']} WHERE {col} = $1", user_id)
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    await log_action(action="user_deleted", user_id=str(current_user.id),
                     metadata={"target_user_id": str(user_id), "role": cible["role"]})
    return {"status": "deleted", "user_id": str(user_id)}


@router.put("/{user_id}/schedule")
async def update_user_schedule(
    user_id: UUID,
    body: ScheduleUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Modifie la plage horaire d'un utilisateur.
    - super_admin : peut modifier n'importe quel utilisateur.
    - direction   : peut modifier les rôles métier uniquement.
    """
    if current_user.role not in ("super_admin", "direction"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        target = await conn.fetchrow("SELECT role FROM users WHERE id = $1", user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")

    # Vérification hiérarchique
    if current_user.role == "direction" and target["role"] == "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission insuffisante")
    if current_user.role == "direction" and target["role"] not in DIRECTION_CREATABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La direction ne peut pas modifier la plage horaire d'un super_admin ou autre direction",
        )

    if body.schedule_start_hour is not None and not (0 <= body.schedule_start_hour <= 23):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Heure de début invalide (0–23)")
    if body.schedule_end_hour is not None and not (1 <= body.schedule_end_hour <= 24):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Heure de fin invalide (1–24)")
    if body.schedule_start_hour is not None and body.schedule_end_hour is not None:
        if body.schedule_start_hour >= body.schedule_end_hour:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="L'heure de début doit être strictement avant l'heure de fin",
            )

    async with get_db() as conn:
        await conn.execute(
            """
            UPDATE users SET
                schedule_start_hour = COALESCE($1, schedule_start_hour),
                schedule_end_hour   = COALESCE($2, schedule_end_hour),
                bypass_schedule     = COALESCE($3, bypass_schedule)
            WHERE id = $4
            """,
            body.schedule_start_hour,
            body.schedule_end_hour,
            body.bypass_schedule,
            user_id,
        )

    await log_action(
        action="user_schedule_updated",
        user_id=str(current_user.id),
        metadata={
            "target_user_id": str(user_id),
            **{k: v for k, v in body.model_dump().items() if v is not None},
        },
    )
    return {"ok": True, "user_id": str(user_id)}
