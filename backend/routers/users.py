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
    email: str
    name: Optional[str] = None
    role: str = "terrain"
    quota_mensuel: Optional[int] = None


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


@router.get("/")
async def list_users(current_user: User = Depends(get_current_user)):
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT
                u.id, u.email, u.name, u.role, u.actif, u.quota_mensuel,
                u.bypass_schedule, u.schedule_start_hour, u.schedule_end_hour,
                u.created_at, u.last_login,
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
            """,
            current_user.role == "super_admin",
        )

    result = []
    for row in rows:
        d = dict(row)
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

    async with get_db() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE email = $1", body.email)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cet email est déjà enregistré")
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

    await log_action(
        action="user_created",
        user_id=str(current_user.id),
        metadata={"new_email": body.email, "new_role": body.role},
    )
    d = dict(row)
    d["agent_permissions"] = _effective_permissions(d["role"], {})
    return d


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
    url = (f"{settings.app_url}/verify"
           f"?token={quote(jeton, safe='')}&email={quote(cible['email'], safe='')}")
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
