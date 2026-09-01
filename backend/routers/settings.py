"""
Configuration système — accessible au super_admin uniquement pour l'écriture.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import has_permission
from security.audit import log_action

router = APIRouter()


class QuotaUpdateRequest(BaseModel):
    quotas: dict[str, Optional[int]]  # {role: monthly_limit | None}


@router.get("/quotas")
async def get_quotas(current_user: User = Depends(get_current_user)):
    # Même raison : l'onglet « Quotas » est réservé au super_admin, et l'écriture
    # exigeait déjà `manage_system`. La lecture s'aligne.
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")

    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT role, monthly_limit FROM role_quota_config ORDER BY role"
        )
    return {row["role"]: row["monthly_limit"] for row in rows}


# ============================================================
# PLAGE HORAIRE GLOBALE (modifiable)
# ============================================================


class ScheduleRequest(BaseModel):
    start_hour: int
    end_hour: int


@router.get("/schedule")
async def get_schedule(current_user: User = Depends(get_current_user)):
    """Plage horaire globale par défaut. Accès : gestion des utilisateurs."""
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT schedule_start_hour, schedule_end_hour FROM global_config WHERE id = 1"
        )
    return {
        "start_hour": row["schedule_start_hour"] if row else 8,
        "end_hour": row["schedule_end_hour"] if row else 18,
    }


@router.put("/schedule")
async def update_schedule(body: ScheduleRequest, current_user: User = Depends(get_current_user)):
    """Modifie la plage horaire globale (super_admin / direction)."""
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    if not (0 <= body.start_hour <= 23) or not (1 <= body.end_hour <= 24):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Heures invalides (début 0–23, fin 1–24)")
    if body.start_hour >= body.end_hour:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Le début doit être avant la fin")
    async with get_db() as conn:
        await conn.execute(
            "UPDATE global_config SET schedule_start_hour = $1, schedule_end_hour = $2, "
            "updated_at = NOW(), updated_by = $3 WHERE id = 1",
            body.start_hour, body.end_hour, current_user.id,
        )
    await log_action(
        action="schedule_config_updated",
        user_id=str(current_user.id),
        metadata={"start_hour": body.start_hour, "end_hour": body.end_hour},
    )
    return {"start_hour": body.start_hour, "end_hour": body.end_hour}


# ============================================================
# PERMISSIONS RBAC (matrice éditable)
# ============================================================


class PermissionRequest(BaseModel):
    role: str
    feature: str
    allowed: bool


@router.get("/permissions")
async def get_permissions(current_user: User = Depends(get_current_user)):
    """Matrice rôle × permission. Lecture : gestion des utilisateurs. Édition : super_admin."""
    if not has_permission(current_user.role, "manage_users"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
    from security.rbac import ALL_ROLES, ALL_FEATURES, FEATURE_LABELS, PROTECTED_ROLE, has_permission as hp
    matrix = {role: {f: hp(role, f) for f in ALL_FEATURES} for role in ALL_ROLES}
    return {
        "roles": ALL_ROLES,
        "features": ALL_FEATURES,
        "labels": FEATURE_LABELS,
        "protected_role": PROTECTED_ROLE,
        "matrix": matrix,
        "can_edit": has_permission(current_user.role, "manage_system"),
    }


@router.put("/permissions")
async def update_permission(body: PermissionRequest, current_user: User = Depends(get_current_user)):
    """Active/désactive une permission pour un rôle (super_admin uniquement)."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")
    from security.rbac import ALL_ROLES, ALL_FEATURES, PROTECTED_ROLE, reload_permissions
    if body.role == PROTECTED_ROLE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Les permissions du super admin ne sont pas modifiables")
    if body.role not in ALL_ROLES or body.feature not in ALL_FEATURES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Rôle ou permission inconnu")
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO roles_permissions (role, feature, allowed) VALUES ($1, $2, $3) "
            "ON CONFLICT (role, feature) DO UPDATE SET allowed = $3",
            body.role, body.feature, body.allowed,
        )
    await reload_permissions()
    await log_action(
        action="permission_config_updated",
        user_id=str(current_user.id),
        metadata={"role": body.role, "feature": body.feature, "allowed": body.allowed},
    )
    return {"role": body.role, "feature": body.feature, "allowed": body.allowed}


@router.put("/quotas")
async def update_quotas(
    body: QuotaUpdateRequest,
    current_user: User = Depends(get_current_user),
):
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")

    async with get_db() as conn:
        for role, limit in body.quotas.items():
            await conn.execute(
                """
                UPDATE role_quota_config
                SET monthly_limit = $1, updated_at = NOW(), updated_by = $2
                WHERE role = $3
                """,
                limit, current_user.id, role,
            )

    await log_action(
        action="quota_config_updated",
        user_id=str(current_user.id),
        metadata={"quotas": {k: v for k, v in body.quotas.items()}},
    )

    async with get_db() as conn:
        rows = await conn.fetch(
            "SELECT role, monthly_limit FROM role_quota_config ORDER BY role"
        )
    return {row["role"]: row["monthly_limit"] for row in rows}


# ── Clés d'API des fournisseurs de modèles ─────────────────────────────
# Saisissables depuis les Paramètres pour qu'une clé expirée ne bloque plus
# l'application jusqu'à la prochaine session SSH. La valeur n'est JAMAIS
# renvoyée : l'interface n'affiche qu'une empreinte, et l'écriture est
# journalisée sans son contenu.

class CleBody(BaseModel):
    cle: str
    valeur: Optional[str] = None      # vide = revenir à la valeur du .env


class ReglageBody(BaseModel):
    cle: str
    valeur: Optional[str] = None      # vide = revenir à la valeur du .env


@router.get("/reglages")
async def lire_reglages(current_user: User = Depends(get_current_user)):
    """Réglages système non secrets, avec leur valeur EN CLAIR.

    Contrairement aux clés, un réglage doit être relisible : c'est la seule
    façon de vérifier ce qui est réellement en vigueur sur ce serveur.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from llm.reglages import etat
    return await etat()


@router.put("/reglages")
async def ecrire_reglage(body: ReglageBody, current_user: User = Depends(get_current_user)):
    """Enregistre ou efface un réglage. Effet immédiat, sans redéploiement."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from llm.reglages import enregistrer, REGLAGES_CONNUS
    if body.cle not in REGLAGES_CONNUS:
        raise HTTPException(status_code=422,
                            detail=f"Réglage inconnu. Attendu : {', '.join(REGLAGES_CONNUS)}")
    try:
        effective = await enregistrer(body.cle, body.valeur, str(current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # La valeur EST journalisée, à la différence des clés : ce n'est pas un
    # secret, et savoir quel modèle a été forcé — et quand — est précisément
    # ce qu'on voudra relire le jour où les temps de réponse s'effondrent.
    await log_action(action="reglage_modifie", user_id=str(current_user.id),
                     metadata={"cle": body.cle, "valeur": (body.valeur or "").strip()})
    return {"cle": body.cle, "valeur": effective,
            "note": "Prise en compte immédiate, sans redéploiement."}


class ConcurrenceBody(BaseModel):
    global_max: Optional[int] = None          # plafond tous appels confondus
    par_role: Optional[dict] = None           # {rôle: plafond}
    par_utilisateur: Optional[dict] = None    # {id: plafond}, None = suit son rôle


@router.get("/concurrence")
async def lire_concurrence(current_user: User = Depends(get_current_user)):
    """Combien d'appels de modèle peuvent partir en même temps, et par qui.

    L'abonnement du fournisseur en autorise un nombre fixe : au-delà il met en
    file puis refuse, et un refus coûte cinq minutes de quarantaine. Cet écran
    est donc le seul endroit où l'on voit, d'un coup d'œil, ce que l'on peut
    consommer et ce qui reste libre.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from database.connection import schema_incomplet
    from llm.concurrence import etat
    from llm.reglages import valeur as reglage
    base = {
        **etat(),
        "origine_global": "parametres" if (reglage("llm_simultanes") or "").strip() else "code",
        "par_role": {}, "par_utilisateur": [],
    }
    # LA MIGRATION PEUT NE PAS ÊTRE PASSÉE, et c'est un état NORMAL entre le
    # déploiement du code et son application à la main. Sans cette garde, la
    # carte rendait « HTTP 500 » — un message qui ne dit pas lequel des deux
    # gestes manque. On rend donc les plafonds du CODE (qui, eux, s'appliquent
    # bel et bien) en nommant la migration à poser.
    try:
        async with get_db() as conn:
            roles = await conn.fetch(
                "SELECT role, concurrent_limit FROM role_quota_config ORDER BY role")
            comptes = await conn.fetch(
                "SELECT id, email, name, role, llm_simultanes FROM users "
                "WHERE COALESCE(actif, true) ORDER BY email")
    except Exception as e:  # noqa: BLE001
        if not schema_incomplet(e):
            raise
        logger.warning("Concurrence : migration 029 non appliquée")
        return {**base, "migration_absente": "029_concurrence_llm.sql"}
    base["par_role"] = {r["role"]: r["concurrent_limit"] for r in roles}
    base["par_utilisateur"] = [
        {"id": str(c["id"]), "email": c["email"], "nom": c["name"],
         "role": c["role"], "plafond": c["llm_simultanes"]}
        for c in comptes]
    return base


@router.put("/concurrence")
async def ecrire_concurrence(body: ConcurrenceBody,
                             current_user: User = Depends(get_current_user)):
    """Règle le plafond global, celui d'un rôle, ou celui d'un compte."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")

    def _borne(v):
        # NULL = « suit le rang au-dessus ». Zéro n'est pas admis : un plafond
        # nul empêcherait quelqu'un de se servir de l'assistant.
        if v is None or str(v).strip() == "":
            return None
        n = int(v)
        if not (1 <= n <= 64):
            raise HTTPException(status_code=422,
                                detail="Plafond attendu entre 1 et 64.")
        return n

    fait = {}
    if body.global_max is not None:
        from llm.reglages import enregistrer
        try:
            fait["global"] = await enregistrer("llm_simultanes", str(_borne(body.global_max)),
                                               str(current_user.id))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    from database.connection import schema_incomplet
    try:
        async with get_db() as conn:
            for role, v in (body.par_role or {}).items():
                await conn.execute(
                    "UPDATE role_quota_config SET concurrent_limit = $2 WHERE role = $1",
                    role, _borne(v))
                fait.setdefault("roles", []).append(role)
            for uid, v in (body.par_utilisateur or {}).items():
                await conn.execute(
                    "UPDATE users SET llm_simultanes = $2 WHERE id = $1::uuid",
                    str(uid), _borne(v))
                fait.setdefault("comptes", []).append(str(uid))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        if not schema_incomplet(e):
            raise
        # Le plafond GLOBAL a pu être posé (il vit dans `reglages`, table
        # ancienne) : on le dit, plutôt que de laisser croire que rien n'a
        # marché. Ce qui manque est nommé, avec le geste qui le répare.
        raise HTTPException(
            status_code=409,
            detail=("Les plafonds par rôle et par compte exigent la migration "
                    "029_concurrence_llm.sql, qui n'est pas encore appliquée sur "
                    "ce serveur. Le plafond global, lui, fonctionne déjà."))
    # Le cache des plafonds vit 60 s : on le vide pour que le réglage se voie
    # tout de suite, sinon l'écran montrerait une valeur déjà changée.
    try:
        from llm.concurrence import _CACHE
        _CACHE.clear()
    except Exception:  # noqa: BLE001
        pass
    await log_action(action="concurrence_modifiee", user_id=str(current_user.id),
                     metadata=fait)
    return {"applique": fait, "note": "Prise en compte immédiate. Les appels déjà "
                                      "en vol gardent l'ancien plafond quelques secondes."}


@router.get("/cles-api")
async def lire_cles(current_user: User = Depends(get_current_user)):
    """Ce qui est configuré, et d'où ça vient. Jamais la valeur."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from llm.cles import etat
    return await etat()


@router.put("/cles-api")
async def ecrire_cle(body: CleBody, current_user: User = Depends(get_current_user)):
    """Enregistre ou efface une clé. La valeur ne ressort jamais."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from llm.cles import enregistrer, CLES_CONNUES
    if body.cle not in CLES_CONNUES:
        raise HTTPException(status_code=422,
                            detail=f"Clé inconnue. Attendu : {', '.join(CLES_CONNUES)}")
    try:
        empreinte = await enregistrer(body.cle, body.valeur, str(current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Journalisé SANS la valeur : le journal d'audit est lisible par la
    # direction, il ne doit pas devenir un second endroit où traînent les clés.
    await log_action(action="cle_api_modifiee", user_id=str(current_user.id),
                     metadata={"cle": body.cle, "effacee": not (body.valeur or "").strip()})
    return {"cle": body.cle, "empreinte": empreinte,
            "note": "Prise en compte immédiate, sans redéploiement."}

@router.get("/modeles")
async def modeles_disponibles(current_user: User = Depends(get_current_user)):
    """Ce que la carte « Le modèle de l'assistant » a besoin de savoir : les
    fournisseurs de texte et leurs modèles, qui a une clé, qui est écarté, et
    les choix en vigueur (`modele_rapide`, `modele_puissant`, et l'éventuel `llm_tete` par palier)."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from llm.router import catalogue_modeles
    from llm.reglages import rafraichir, valeur
    await rafraichir(force=True)
    return {"modele_rapide": (valeur("modele_rapide") or "").strip(),
            "modele_puissant": (valeur("modele_puissant") or "").strip(),
            "llm_tete": (valeur("llm_tete") or "").strip(),
            "fournisseurs": catalogue_modeles()}


@router.get("/cascade")
async def sante_de_la_cascade(current_user: User = Depends(get_current_user)):
    """Qui répond, qui est écarté, et pourquoi — pour l'écran d'administration.

    La lenteur ressentie a une cause mesurable, et elle était invisible : sur la
    session du 21/08, quatre fournisseurs sur cinq échouaient à chaque appel
    (clés mortes, modèles retirés du compte) sans que rien ne le dise à l'écran.
    On regardait les traces pour l'apprendre. Ce rapport rend l'état lisible
    depuis l'application.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from llm.router import sante_cascade
    return sante_cascade()
