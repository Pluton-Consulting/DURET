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
    """Combien d'appels de modèle peuvent partir en même temps, TOUS COMPTES
    CONFONDUS.

    UN SEUL CHIFFRE, et c'est une décision de Noa (01/09) : « ce paramètre
    concerne l'ensemble des comptes cumulés ». L'abonnement du fournisseur en
    autorise un nombre fixe ; au-delà il met en file puis refuse, et un refus
    coûte cinq minutes de quarantaine. Ce qui compte est donc le total, pas sa
    répartition.

    Le plafond PAR PERSONNE reste, mais comme garde interne non réglable ici :
    il empêche une seule personne de prendre tous les créneaux, et sa valeur
    vient du code. Rien à lire en base — c'est aussi ce qui rend cette route
    insensible à l'état des migrations.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from llm.concurrence import etat
    from llm.reglages import texte
    return {**etat(),
            "origine_global": "parametres" if texte("llm_simultanes") else "code"}


@router.put("/concurrence")
async def ecrire_concurrence(body: ConcurrenceBody,
                             current_user: User = Depends(get_current_user)):
    """Règle le plafond global — le seul réglage de cette carte."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from llm.reglages import enregistrer

    brut = body.global_max
    if brut is None or str(brut).strip() == "":
        # Vider le champ rend la main au défaut du code, il n'impose pas zéro :
        # un plafond nul empêcherait tout le monde de travailler.
        valeur_a_poser = ""
    else:
        n = int(brut)
        if not (1 <= n <= 64):
            raise HTTPException(status_code=422,
                                detail="Plafond attendu entre 1 et 64.")
        valeur_a_poser = str(n)
    try:
        await enregistrer("llm_simultanes", valeur_a_poser, str(current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    # Le cache des plafonds vit 60 s : on le vide pour que le réglage se voie
    # tout de suite, sinon l'écran montrerait une valeur déjà changée.
    try:
        from llm.concurrence import _CACHE
        _CACHE.clear()
    except Exception:  # noqa: BLE001 — un cache non vidé se périme seul
        pass
    return {"global": valeur_a_poser or "défaut du code"}


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
    from llm.reglages import rafraichir, texte
    await rafraichir(force=True)
    from config import settings as _s
    return {"modele_rapide": texte("modele_rapide"),
            "modele_puissant": texte("modele_puissant"),
            "modele_vision": texte("modele_vision"),
            "modele_embedding": texte("modele_embedding"),
            "llm_tete": texte("llm_tete"),
            # LA GÉNÉRATION D'IMAGES SE MONTRE, ELLE NE SE CHOISIT PAS.
            # Décision de Noa : « la génération d'image, je veux que ça reste
            # Nano Banana Pro avec Google AI ». L'écran l'affiche pour qu'on
            # sache ce qui tire les visuels — ne rien montrer laisserait croire
            # que rien ne s'en occupe — mais aucune route ne permet d'en
            # changer, et c'est voulu.
            "modele_image": {
                "fournisseur": "google",
                "modele": getattr(_s, "model_nano_banana", "") or "nano-banana-pro",
                "verrouille": True,
                "raison": "choix arrêté : un rendu montré à un client ne doit "
                          "pas sortir d'un modèle moindre",
            },
            # La dimension des vecteurs : changer de modèle d'embedding impose
            # de tout re-vectoriser, et l'écran doit le dire AVANT le clic.
            "embedding_dimensions": int(getattr(_s, "embedding_dimensions", 1536) or 1536),
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


# ── Re-vectorisation du corpus ────────────────────────────────────────────
#
# CHANGER DE MODÈLE D'EMBEDDING N'EST PAS UN RÉGLAGE COMME UN AUTRE. Deux
# vecteurs ne sont comparables que s'ils viennent du MÊME modèle : garder les
# anciens ne casse rien de visible, ce qui est bien pire qu'une panne — la
# recherche continue de répondre, avec des résultats faux que rien ne signale.
#
# Les deux routes ci-dessous séparent volontairement REGARDER et AGIR : on
# mesure d'abord ce que rend le modèle choisi, on lit ce que ça coûtera, et
# c'est seulement ensuite qu'on efface. Une opération qui vide 9 400 vecteurs
# ne se déclenche pas au premier clic d'un menu déroulant.

class RevectoriserRequest(BaseModel):
    # La dimension MESURÉE, telle que la route d'inspection l'a rendue. On la
    # redemande plutôt que de la recalculer : c'est la preuve que l'écran a bien
    # montré à la personne le chiffre sur lequel elle s'engage.
    dimension: int


@router.get("/embeddings")
async def etat_des_embeddings(current_user: User = Depends(get_current_user)):
    """Où en est la vectorisation, et ce que rendrait le modèle actuellement
    choisi. Ne modifie RIEN."""
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from vectorstore import revectorisation as rv

    etat = await rv.etat()
    mesuree, detail = await rv.mesurer_dimension()
    attendue = await rv.dimension_attendue()
    return {
        **etat,
        "dimension_base": attendue,
        "dimension_modele": mesuree,
        "detail": detail,
        # LE VERDICT EST CALCULÉ ICI, PAS À L'ÉCRAN : c'est la même donnée qui
        # décide de l'affichage et qui autorisera l'opération.
        "revectorisation_necessaire": bool(mesuree and mesuree != attendue),
        "mesure_possible": mesuree is not None,
    }


@router.post("/embeddings/revectoriser")
async def lancer_revectorisation(body: RevectoriserRequest,
                                 current_user: User = Depends(get_current_user)):
    """Vide les vecteurs, aligne la base sur la dimension mesurée, et remet tout
    le corpus en file d'attente.

    La re-vectorisation elle-même est faite par le worker déjà en place, à sa
    cadence et avec ses pauses de quota : on ne lance pas ici 9 400 appels au
    fournisseur, on remplit une file que quelqu'un draine déjà.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from vectorstore import revectorisation as rv

    # LA DIMENSION EST RE-MESURÉE AVANT D'EFFACER. Celle du corps de la requête
    # peut dater de plusieurs minutes, et le modèle a pu changer entre-temps
    # (deux onglets, deux administrateurs). Effacer un corpus sur une valeur
    # périmée le laisserait à une dimension que plus aucun modèle ne rend.
    mesuree, detail = await rv.mesurer_dimension()
    if mesuree is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if mesuree != body.dimension:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(f"Le modèle rend {mesuree} dimensions, l'écran en annonçait "
                    f"{body.dimension}. Rien n'a été effacé : rechargez la page "
                    "pour repartir de la mesure à jour."))

    await log_action(action="revectorisation_lancee",
                     user_id=str(current_user.id),
                     metadata={"dimension": mesuree})
    resultat = await rv.revectoriser(mesuree)
    return {
        **resultat,
        "note": (f"Les vecteurs ont été effacés et la base est passée à "
                 f"{mesuree} dimensions. Les {resultat['morceaux_en_file']} "
                 "morceaux se re-vectorisent en tâche de fond. Pendant ce "
                 "temps, la recherche continue de répondre par sa voie "
                 "textuelle : les résultats sont moins fins, pas absents."),
    }


@router.get("/embeddings/catalogue")
async def catalogue_des_embeddings(rafraichir: bool = False,
                                   current_user: User = Depends(get_current_user)):
    """Les modèles d'embedding accessibles avec les clés posées, chacun avec sa
    DIMENSION mesurée.

    C'est la seule façon honnête de répondre à « quels modèles ai-je ? » : le
    catalogue du fournisseur ne rend que des noms, et la dimension — qui décide
    de tout ici — n'est annoncée nulle part. On la mesure.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=403, detail="Réservé à l'administration système")
    from vectorstore.revectorisation import catalogue_embeddings, dimension_attendue

    return {"dimension_base": await dimension_attendue(),
            "modeles": await catalogue_embeddings(rafraichir=rafraichir)}
