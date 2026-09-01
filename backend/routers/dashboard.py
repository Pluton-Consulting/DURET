import json

from fastapi import APIRouter, Depends, HTTPException, status
from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_rls_db, get_db
from security.rbac import has_permission
from config import settings

router = APIRouter()

# LE PLANCHER DES INDICATEURS (réglage `kpi_depuis`).
#
# Une remise à zéro qui ne supprime rien : les lignes restent en base, on cesse
# de les compter. Réversible en effaçant le champ — ce qu'aucun DELETE ne
# permet. Il s'applique aux VOLUMES et aux COÛTS, pas aux listes
# opérationnelles : masquer les échecs des dernières 24 h ou les sessions en
# cours n'aurait aucun sens, ce sont des états présents, pas de l'historique.
def _plancher(colonne: str) -> str:
    from llm.reglages import plancher_sql
    return plancher_sql(colonne)



def _exiger(role: str, feature: str) -> None:
    """Lève une 403 si le rôle ne dispose pas de la permission demandée."""
    if not has_permission(role, feature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission refusée",
        )


# ============================================================
# STATISTIQUES PERSONNELLES / GLOBALES (existant)
# ============================================================


@router.get("/stats")
async def get_stats(current_user: User = Depends(get_current_user)):
    """Statistiques personnelles de l'utilisateur courant (threads + usage du jour)."""
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        thread_count = await conn.fetchval(
            f"SELECT COUNT(*) FROM threads WHERE user_id = $1{_plancher('created_at')}",
            current_user.id,
        )
        usage_today = await conn.fetchrow(
            "SELECT request_count, tokens_total, cost_eur FROM api_usage_daily "
            "WHERE user_id = $1 AND date = CURRENT_DATE",
            current_user.id,
        )
    return {
        "threads": thread_count,
        "today": dict(usage_today) if usage_today else {
            "request_count": 0,
            "tokens_total": 0,
            "cost_eur": 0,
        },
        "quota_mensuel": current_user.quota_mensuel,
    }


@router.get("/global")
async def get_global_stats(current_user: User = Depends(get_current_user)):
    """Vue globale par rôle : nombre d'utilisateurs, requêtes et coûts du jour."""
    _exiger(current_user.role, "view_dashboard_global")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT u.role,
                   COUNT(DISTINCT u.id) AS user_count,
                   COALESCE(SUM(d.request_count), 0) AS total_requests,
                   COALESCE(SUM(d.cost_eur), 0) AS total_cost
            FROM users u
            LEFT JOIN api_usage_daily d ON d.user_id = u.id AND d.date = CURRENT_DATE
            GROUP BY u.role
            ORDER BY u.role
        """)
    return [dict(row) for row in rows]


@router.get("/activity")
async def get_activity(
    current_user: User = Depends(get_current_user),
    limit: int = 20,
):
    """Journal d'activité récent (audit_log), le plus récent en premier.

    Renvoie l'intégralité des métadonnées techniques (metadata JSONB, message
    d'erreur, modèle, tokens, durée) pour la console développeur — super_admin only.
    """
    _exiger(current_user.role, "view_audit_log")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch(
            "SELECT id, user_id, action, agent_id, model_used, tokens_in, tokens_out, "
            "cost_eur, duration_ms, success, error_message, metadata, created_at "
            "FROM audit_log ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    out = []
    for row in rows:
        d = dict(row)
        # asyncpg renvoie le JSONB en str (aucun codec enregistré) → on désérialise.
        m = d.get("metadata")
        if isinstance(m, str):
            try:
                d["metadata"] = json.loads(m)
            except Exception:
                d["metadata"] = None
        out.append(d)
    return out


@router.get("/token-usage")
async def get_token_usage(current_user: User = Depends(get_current_user), days: int = 7):
    """Consommation de tokens (audit_log) par modèle + totaux + stats du cache d'optimisation."""
    _exiger(current_user.role, "view_costs_global")
    days = max(1, min(days, 90))
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        by_model = await conn.fetch(
            "SELECT model_used, COUNT(*) AS n, COALESCE(SUM(tokens_in),0) AS tokens_in, "
            "COALESCE(SUM(tokens_out),0) AS tokens_out, COALESCE(SUM(cost_eur),0) AS cost_eur "
            f"FROM audit_log WHERE created_at > NOW() - ($1::int * INTERVAL '1 day'){_plancher('created_at')} "
            "AND model_used IS NOT NULL GROUP BY model_used ORDER BY tokens_in + tokens_out DESC",
            days,
        )
        totals = await conn.fetchrow(
            "SELECT COALESCE(SUM(tokens_in),0) AS tokens_in, COALESCE(SUM(tokens_out),0) AS tokens_out, "
            "COALESCE(SUM(cost_eur),0) AS cost_eur, COUNT(*) AS n FROM audit_log "
            f"WHERE created_at > NOW() - ($1::int * INTERVAL '1 day'){_plancher('created_at')} AND model_used IS NOT NULL",
            days,
        )
    from optim.tokens import response_cache
    return {
        "days": days,
        "totals": dict(totals) if totals else {},
        "by_model": [dict(r) for r in by_model],
        "cache": response_cache.stats(),
    }


# ============================================================
# SUPERVISION TEMPS RÉEL
# ============================================================


@router.get("/live-sessions")
async def get_live_sessions(current_user: User = Depends(get_current_user)):
    """
    Sessions actives récentes : threads dont la dernière activité (updated_at)
    remonte à moins de 30 minutes. Jointure sur `users` pour exposer le nom,
    l'email et le rôle de l'utilisateur derrière chaque session.
    """
    _exiger(current_user.role, "view_dashboard_global")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT t.id,
                   t.title,
                   t.agent_type,
                   t.status,
                   t.updated_at,
                   u.id    AS user_id,
                   u.name  AS user_name,
                   u.email AS user_email,
                   u.role  AS user_role
            FROM threads t
            JOIN users u ON u.id = t.user_id
            WHERE t.updated_at > NOW() - INTERVAL '30 minutes'
            ORDER BY t.updated_at DESC
        """)
    return [dict(row) for row in rows]


@router.get("/agents-activity")
async def get_agents_activity(current_user: User = Depends(get_current_user)):
    """
    Activité des agents sur la journée courante, agrégée par `agent_id` depuis
    `audit_log` : nombre de requêtes, succès/échecs, tokens totaux (in + out),
    coût total et durée moyenne d'exécution.
    """
    # ADMINISTRATION SYSTÈME (01/09) : l'onglet « États des agents » a été retiré
    # à la direction, et l'écran Superviseur — seul autre appelant — est déjà
    # réservé au super_admin. Masquer un écran ne ferme pas son API.
    _exiger(current_user.role, "manage_system")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT agent_id,
                   COUNT(*)                                   AS request_count,
                   COUNT(*) FILTER (WHERE success)            AS success_count,
                   COUNT(*) FILTER (WHERE NOT success)        AS failure_count,
                   COALESCE(SUM(tokens_in + tokens_out), 0)   AS tokens_total,
                   COALESCE(SUM(cost_eur), 0)                 AS cost_total,
                   COALESCE(ROUND(AVG(duration_ms)), 0)       AS avg_duration_ms
            FROM audit_log
            WHERE created_at::date = CURRENT_DATE
              AND agent_id IS NOT NULL
            GROUP BY agent_id
            ORDER BY agent_id
        """)
    return [dict(row) for row in rows]


# ============================================================
# COÛTS
# ============================================================


@router.get("/costs")
async def get_costs(current_user: User = Depends(get_current_user)):
    """
    Analyse des coûts :
    - `by_day` : coût, requêtes et tokens agrégés par jour sur les 30 derniers jours.
    - `current_month_total` : total du mois en cours.
    - `by_role` : répartition des coûts du mois courant par rôle (JOIN users).
    """
    _exiger(current_user.role, "view_costs_global")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        by_day = await conn.fetch(f"""
            SELECT date,
                   COALESCE(SUM(cost_eur), 0)      AS cost_eur,
                   COALESCE(SUM(request_count), 0) AS request_count,
                   COALESCE(SUM(tokens_total), 0)  AS tokens_total
            FROM api_usage_daily
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('date')}
            GROUP BY date
            ORDER BY date
        """)
        current_month_total = await conn.fetchrow(f"""
            SELECT COALESCE(SUM(cost_eur), 0)      AS cost_eur,
                   COALESCE(SUM(request_count), 0) AS request_count,
                   COALESCE(SUM(tokens_total), 0)  AS tokens_total
            FROM api_usage_daily
            WHERE date_trunc('month', date) = date_trunc('month', CURRENT_DATE){_plancher('date')}
        """)
        by_role = await conn.fetch("""
            SELECT u.role,
                   COALESCE(SUM(d.cost_eur), 0)      AS cost_eur,
                   COALESCE(SUM(d.request_count), 0) AS request_count,
                   COALESCE(SUM(d.tokens_total), 0)  AS tokens_total
            FROM users u
            LEFT JOIN api_usage_daily d
                   ON d.user_id = u.id
                  AND date_trunc('month', d.date) = date_trunc('month', CURRENT_DATE)
            GROUP BY u.role
            ORDER BY u.role
        """)
    return {
        "by_day": [dict(row) for row in by_day],
        "current_month_total": dict(current_month_total) if current_month_total else {
            "cost_eur": 0,
            "request_count": 0,
            "tokens_total": 0,
        },
        "by_role": [dict(row) for row in by_role],
    }


# ============================================================
# VALIDATIONS EN ATTENTE
# ============================================================


@router.get("/pending-skills")
async def get_pending_skills(current_user: User = Depends(get_current_user)):
    """
    Skills en attente de validation (status 'draft' ou 'testing'), avec leur
    score de confiance, leur auteur et leur date de création.
    """
    _exiger(current_user.role, "validate_skills")
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT id,
                   name,
                   description,
                   version,
                   status,
                   confidence_score,
                   usage_count,
                   created_by,
                   created_at
            FROM skills
            WHERE status IN ('draft', 'testing')
            ORDER BY created_at DESC
        """)
    return [dict(row) for row in rows]


@router.get("/pending-validations")
async def get_pending_validations(current_user: User = Depends(get_current_user)):
    """
    Demandes de validation human-in-the-loop en attente (status 'pending').

    Accessible aux rôles disposant de la permission `validate_skills` OU
    `manage_users`. Jointure sur `users` pour identifier le demandeur.
    """
    if not (
        has_permission(current_user.role, "validate_skills")
        or has_permission(current_user.role, "manage_users")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission refusée",
        )
    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        rows = await conn.fetch("""
            SELECT v.id,
                   v.thread_id,
                   v.agent,
                   v.reason,
                   v.draft,
                   v.created_at,
                   u.name  AS user_name,
                   u.email AS user_email,
                   u.role  AS user_role
            FROM validations v
            LEFT JOIN users u ON u.id = v.user_id
            WHERE v.status = 'pending'
            ORDER BY v.created_at ASC
        """)
    return [dict(row) for row in rows]


# ============================================================
# ALERTES
# ============================================================


@router.get("/alerts")
async def get_alerts(current_user: User = Depends(get_current_user)):
    """
    Liste d'alertes calculées à la volée pour le tableau de bord global.

    Trois familles d'alertes sont évaluées :
    - quotas mensuels proches de la limite (> 80 % de `role_quota_config`) ;
    - échecs LLM récents (audit_log, success = false, dernières 24 h), comptés
      par action ;
    - skills en attente de validation (status 'draft' ou 'testing').

    Chaque alerte : {level: 'info'|'warning'|'error', message, count}.
    """
    _exiger(current_user.role, "view_dashboard_global")

    alerts: list[dict] = []

    async with get_rls_db(str(current_user.id), current_user.role) as conn:
        # 1. Utilisateurs proches de leur quota mensuel (> 80 %)
        quotas_row = await conn.fetchrow("""
            SELECT COUNT(*) AS nb
            FROM (
                SELECT u.id
                FROM users u
                JOIN role_quota_config rq ON rq.role = u.role
                LEFT JOIN api_usage_daily d
                       ON d.user_id = u.id
                      AND date_trunc('month', d.date) = date_trunc('month', CURRENT_DATE)
                WHERE rq.monthly_limit IS NOT NULL
                GROUP BY u.id, rq.monthly_limit
                HAVING COALESCE(SUM(d.request_count), 0) > 0.8 * rq.monthly_limit
            ) AS proches
        """)
        nb_quotas = quotas_row["nb"] if quotas_row else 0
        if nb_quotas > 0:
            alerts.append({
                "level": "warning",
                "message": f"{nb_quotas} utilisateur(s) proche(s) de leur quota mensuel (> 80 %)",
                "count": nb_quotas,
            })

        # 2. Échecs LLM des dernières 24 h, comptés par action
        echecs = await conn.fetch("""
            SELECT action, COUNT(*) AS nb
            FROM audit_log
            WHERE success = false
              AND created_at > NOW() - INTERVAL '24 hours'
            GROUP BY action
            ORDER BY nb DESC
        """)
        for row in echecs:
            alerts.append({
                "level": "error",
                "message": f"{row['nb']} échec(s) LLM sur l'action « {row['action']} » (24 h)",
                "count": row["nb"],
            })

        # 3. Skills en attente de validation
        nb_skills = await conn.fetchval("""
            SELECT COUNT(*) FROM skills WHERE status IN ('draft', 'testing')
        """)
        if nb_skills and nb_skills > 0:
            alerts.append({
                "level": "info",
                "message": f"{nb_skills} skill(s) en attente de validation",
                "count": nb_skills,
            })

    return alerts


# ============================================================
# PILOTAGE (direction) — usages, coûts, journal, par personne
# ============================================================


@router.get("/pilotage")
async def get_pilotage(current_user: User = Depends(get_current_user)):
    """Ce que la page Pilotage montre : des CHIFFRES RÉELS, agrégés en une fois.

    La page affichait « n/d » sur ses indicateurs et « route non implémentée »
    sur les coûts par personne, avec un avertissement disant que les vrais
    chiffres étaient ailleurs. Le brief (§15) en fait pourtant une exigence de
    la Direction : suivi de la consommation par utilisateur, des coûts IA, des
    usages anormaux, journalisation des actions. La donnée existait déjà —
    `api_usage_daily` (par personne et par jour) et `audit_log` (chaque action,
    sa durée, son succès) — elle n'était simplement pas servie.

    Un seul appel, parce que la page se lit d'un coup : indicateurs, série
    quotidienne sur trente jours, répartition par personne sur trente jours,
    erreurs des dernières vingt-quatre heures, dernières actions du journal.
    Le journal est borné et ne porte JAMAIS le contenu des échanges — seulement
    l'action, qui, quand, combien de temps, réussi ou non : c'est ce que
    `log_action` y écrit, rien d'autre.
    """
    _exiger(current_user.role, "view_dashboard_global")
    peut_couts = has_permission(current_user.role, "view_costs_global")
    peut_journal = has_permission(current_user.role, "view_audit_log")

    async with get_db() as conn:
        kpi = await conn.fetchrow(f"""
            SELECT
              (SELECT COALESCE(SUM(request_count), 0) FROM api_usage_daily
                WHERE date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('date')})  AS requetes_30j,
              (SELECT COUNT(*) FROM audit_log
                WHERE success = false AND created_at >= NOW() - INTERVAL '24 hours') AS erreurs_24h,
              (SELECT COALESCE(SUM(cost_eur), 0) FROM api_usage_daily
                WHERE date_trunc('month', date) = date_trunc('month', CURRENT_DATE){_plancher('date')}) AS cout_mois_eur,
              (SELECT COUNT(DISTINCT user_id) FROM api_usage_daily
                WHERE date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('date')})  AS personnes_actives_30j,
              (SELECT COUNT(*) FROM validations WHERE status = 'pending')   AS accords_en_attente,
              (SELECT COUNT(*) FROM skills WHERE status IN ('validated','stable')
                                              AND COALESCE(enabled, true))   AS competences_actives
        """)
        par_jour = await conn.fetch(f"""
            SELECT date,
                   COALESCE(SUM(request_count), 0) AS requetes,
                   COALESCE(SUM(tokens_total), 0)  AS jetons,
                   COALESCE(SUM(cost_eur), 0)      AS cout_eur
            FROM api_usage_daily
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('date')}
            GROUP BY date ORDER BY date
        """)
        par_personne = await conn.fetch(f"""
            SELECT u.id, u.name, u.email, u.role,
                   COALESCE(SUM(d.request_count), 0) AS requetes,
                   COALESCE(SUM(d.tokens_total), 0)  AS jetons,
                   COALESCE(SUM(d.cost_eur), 0)      AS cout_eur,
                   MAX(d.date)                       AS derniere_activite
            FROM users u
            LEFT JOIN api_usage_daily d
                   ON d.user_id = u.id AND d.date >= CURRENT_DATE - INTERVAL '30 days'{_plancher('d.date')}
            -- MÊME RÈGLE QUE list_users (01/09) : la direction ne voit pas les
            -- super_admin, ici non plus. Un filtre posé à un seul endroit est un
            -- rideau, pas un mur — ce tableau rend nom, e-mail et rôle.
            WHERE COALESCE(u.actif, true)
              AND ({'true' if current_user.role == 'super_admin' else "u.role <> 'super_admin'"})
            GROUP BY u.id, u.name, u.email, u.role
            ORDER BY requetes DESC, u.email
        """)
        # LE MÊME FILTRE AUX TROIS ENDROITS (01/09). Il n'était posé que sur le
        # tableau « par personne » — alors que le commentaire juste au-dessus
        # dit lui-même qu'un filtre à un seul endroit est un rideau, pas un
        # mur. Le Journal et les Erreurs rendent AUSSI le nom et l'e-mail :
        # la direction y voyait donc les super_admin qu'on venait de lui
        # masquer ailleurs. Une ligne d'un super_admin est retirée, pas
        # anonymisée : garder la ligne sans le nom dirait encore qu'il existe
        # une activité qu'on ne montre pas.
        filtre_admin = ("" if current_user.role == "super_admin"
                        else " AND (u.role IS NULL OR u.role <> 'super_admin')")
        erreurs = await conn.fetch(f"""
            SELECT a.created_at, a.action, a.agent_id, a.error_message,
                   COALESCE(u.name, u.email) AS qui
            FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
            WHERE a.success = false AND a.created_at >= NOW() - INTERVAL '24 hours'
              {filtre_admin}
            ORDER BY a.created_at DESC LIMIT 50
        """) if peut_journal else []
        journal = await conn.fetch(f"""
            SELECT a.created_at, a.action, a.agent_id, a.model_used, a.duration_ms,
                   a.success, a.tokens_in, a.tokens_out,
                   COALESCE(u.name, u.email) AS qui
            FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
            WHERE true {filtre_admin}
            ORDER BY a.created_at DESC LIMIT 80
        """) if peut_journal else []

    def _ligne(r):
        d = dict(r)
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif type(v).__name__ == "Decimal":
                d[k] = float(v)
            elif hasattr(v, "hex") and k == "id":
                d[k] = str(v)
        return d

    personnes = [_ligne(r) for r in par_personne]
    if not peut_couts:
        # Sans le droit de voir les coûts, on voit QUI utilise, pas COMBIEN ça coûte.
        for p in personnes:
            p.pop("cout_eur", None)

    return {
        "kpi": _ligne(kpi) if kpi else {},
        "par_jour": [_ligne(r) for r in par_jour],
        "par_personne": personnes,
        "erreurs_24h": [_ligne(r) for r in erreurs],
        "journal": [_ligne(r) for r in journal],
        "droits": {"couts": peut_couts, "journal": peut_journal},
    }


# ============================================================
# CONSOLE DÉVELOPPEUR (super_admin uniquement)
# ============================================================


@router.get("/system")
async def get_system(current_user: User = Depends(get_current_user)):
    """
    État système temps réel pour la console développeur : fournisseurs LLM
    disponibles, cascade par palier, observabilité, checkpointer, config runtime.
    Réservé au super_admin (permission manage_system). Aucun secret exposé.
    """
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé au super admin")

    from llm.router import _provider_available, _tier_chain, LLMTier
    import observability
    from agents import checkpointer as _cp

    providers = {
        p: _provider_available(p)
        for p in ["longcat", "deepseek", "openrouter", "groq", "anthropic", "ollama"]
    }
    chains = {
        t.value: [f"{prov}:{mod or 'default'}" for prov, mod in _tier_chain(t)]
        for t in (LLMTier.LIGHT, LLMTier.STANDARD, LLMTier.COMPLEX)
    }
    checkpointer_type = type(_cp._checkpointer).__name__ if _cp._checkpointer else "non initialisé"

    # Compteurs DB rapides
    async with get_db() as conn:
        counts = await conn.fetchrow(
            """SELECT
                 (SELECT COUNT(*) FROM users WHERE actif) AS users_actifs,
                 (SELECT COUNT(*) FROM threads) AS threads,
                 (SELECT COUNT(*) FROM audit_log) AS audit_events,
                 (SELECT COUNT(*) FROM validations WHERE status='pending') AS validations_pending,
                 (SELECT COUNT(*) FROM skills) AS skills"""
        )

    return {
        "environment": settings.environment,
        "debug": settings.debug,
        "providers": providers,
        "chains": chains,
        "observability": {
            "langfuse_enabled": observability.is_enabled(),
            "host": settings.langfuse_base_url or settings.langfuse_host,
        },
        "checkpointer": checkpointer_type,
        "browser_enabled": settings.browser_enabled,
        "schedule": f"{settings.access_start_hour}h–{settings.access_end_hour}h",
        "db": dict(counts) if counts else {},
    }
