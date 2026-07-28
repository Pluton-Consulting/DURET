from fastapi import HTTPException, status
from typing import List, Optional
import logging

logger = logging.getLogger("duret.rbac")

# Hiérarchie des rôles
# super_admin  → développeur, accès total, manage tout
# direction    → dirigeants Duret & Sols, vue client + gestion app complète
# commercial / bureau_etudes / conducteur / administratif / terrain → utilisateurs métier

ROLE_PERMISSIONS: dict[str, List[str]] = {
    "super_admin": [
        "chat_agent1", "chat_agent2", "chat_agent3",
        "view_dashboard_global", "view_own_stats",
        "validate_skills", "manage_users", "configure_agents",
        "view_costs_global", "view_own_costs", "view_audit_log",
        "manage_agent3", "manage_system", "run_browser_agent", "import_documents",
    ],
    "direction": [
        "chat_agent1", "chat_agent2", "chat_agent3",
        "view_dashboard_global", "view_own_stats",
        "validate_skills", "manage_users", "configure_agents",
        "view_costs_global", "view_own_costs", "view_audit_log",
        "manage_agent3", "run_browser_agent", "import_documents",
    ],
    "commercial": [
        "chat_agent1", "view_own_stats", "view_own_costs",
    ],
    "bureau_etudes": [
        "chat_agent1", "chat_agent2", "view_own_stats", "view_own_costs",
    ],
    "conducteur": [
        "chat_agent1", "view_own_stats", "view_own_costs",
    ],
    "administratif": [
        "chat_agent1", "view_own_stats", "view_own_costs",
    ],
    "terrain": [
        "chat_agent1",
    ],
}

# Rôles exemptés des plages horaires (ne passent jamais par check_schedule)
SCHEDULE_EXEMPT_ROLES = {"super_admin", "direction"}

# Permissions agent par défaut selon le rôle (fallback si pas d'override en base)
ROLE_AGENT_DEFAULTS: dict[str, dict[str, bool]] = {
    "super_admin":  {"agent1": True,  "agent2": True,  "agent3": True},
    "direction":    {"agent1": True,  "agent2": True,  "agent3": True},
    "commercial":   {"agent1": True,  "agent2": False, "agent3": False},
    "bureau_etudes":{"agent1": True,  "agent2": True,  "agent3": False},
    "conducteur":   {"agent1": True,  "agent2": False, "agent3": False},
    "administratif":{"agent1": True,  "agent2": False, "agent3": False},
    "terrain":      {"agent1": True,  "agent2": False, "agent3": False},
}

ROLE_QUOTAS: dict[str, int | None] = {
    "super_admin":  None,
    "direction":    None,
    "commercial":   200,
    "bureau_etudes": 150,
    "conducteur":   100,
    "administratif": 100,
    "terrain":      50,
}


# ── Permissions RBAC modifiables en base (matrice éditable) ──────────────
ALL_ROLES = ["super_admin", "direction", "commercial", "bureau_etudes",
             "conducteur", "administratif", "terrain"]

ALL_FEATURES = [
    "chat_agent1", "chat_agent2", "chat_agent3",
    "view_own_stats", "view_own_costs",
    "view_dashboard_global", "view_costs_global", "view_audit_log",
    "validate_skills", "configure_agents", "manage_agent3",
    "manage_users", "manage_system", "run_browser_agent", "import_documents",
]

FEATURE_LABELS = {
    "chat_agent1": "Agent 1 (chat)",
    "chat_agent2": "Agent 2 (vision)",
    "chat_agent3": "Agent 3 (auto-évolution)",
    "view_own_stats": "Ses stats",
    "view_own_costs": "Ses coûts",
    "view_dashboard_global": "Dashboard global",
    "view_costs_global": "Coûts globaux",
    "view_audit_log": "Journal d'audit",
    "validate_skills": "Valider skills",
    "configure_agents": "Configurer agents",
    "manage_agent3": "Gérer Agent 3",
    "manage_users": "Gérer utilisateurs",
    "import_documents": "Importer des documents",
    "manage_system": "Admin système",
    "run_browser_agent": "Agent Navigateur",
}

# Rôle dont les permissions ne sont JAMAIS modifiables (garde-fou anti-lockout).
PROTECTED_ROLE = "super_admin"

# Cache mémoire des permissions chargées depuis la base (None = fallback code).
_PERM_CACHE: Optional[dict[str, set]] = None


def has_permission(role: str, feature: str) -> bool:
    """
    Vrai si le rôle a la permission. Le super_admin a TOUJOURS tout (garde-fou).
    Lit le cache DB si disponible (matrice éditable), sinon les défauts du code.
    """
    if role == PROTECTED_ROLE:
        return True
    if _PERM_CACHE is not None:
        return feature in _PERM_CACHE.get(role, set())
    return feature in ROLE_PERMISSIONS.get(role, [])


async def seed_permissions_if_empty(conn) -> None:
    """Amorce roles_permissions depuis les défauts du code si la table est vide."""
    count = await conn.fetchval("SELECT COUNT(*) FROM roles_permissions")
    if count and count > 0:
        return
    for role, feats in ROLE_PERMISSIONS.items():
        for feat in feats:
            await conn.execute(
                "INSERT INTO roles_permissions (role, feature, allowed) VALUES ($1, $2, true) "
                "ON CONFLICT (role, feature) DO NOTHING",
                role, feat,
            )


async def reload_permissions() -> None:
    """Recharge la matrice de permissions depuis la base vers le cache mémoire."""
    global _PERM_CACHE
    from database.connection import get_db
    try:
        async with get_db() as conn:
            await seed_permissions_if_empty(conn)
            rows = await conn.fetch("SELECT role, feature FROM roles_permissions WHERE allowed = true")
        cache: dict[str, set] = {}
        for r in rows:
            cache.setdefault(r["role"], set()).add(r["feature"])
        cache[PROTECTED_ROLE] = set(ALL_FEATURES)  # super_admin toujours tout
        _PERM_CACHE = cache
        logger.info("Permissions RBAC chargées depuis la base (%d rôles)", len(cache))
    except Exception as e:
        logger.warning("Chargement permissions DB échoué (%s) — fallback code", e)


def role_agent_default(role: str, agent: str) -> bool:
    return ROLE_AGENT_DEFAULTS.get(role, {}).get(agent, False)


def can_manage_agent_permission(manager_role: str, agent: str, target_role: str) -> bool:
    """
    super_admin : peut tout modifier.
    direction   : peut tout modifier sauf les super_admin.
    """
    if manager_role == "super_admin":
        return True
    if manager_role == "direction":
        if target_role == "super_admin":
            return False
        return True
    return False


def require_permission(feature: str):
    from functools import wraps

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, current_user=None, **kwargs):
            if current_user is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
            if not has_permission(current_user.role, feature):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission '{feature}' requise",
                )
            return await func(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator
