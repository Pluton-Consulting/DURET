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
        "manage_agent3", "manage_system", "run_browser_agent", "import_documents", "manage_mailboxes",
    ],
    "direction": [
        "chat_agent1", "chat_agent2", "chat_agent3",
        "view_dashboard_global", "view_own_stats",
        "validate_skills", "manage_users", "configure_agents",
        "view_costs_global", "view_own_costs", "view_audit_log",
        # ⚠ CE FICHIER N'EST PAS LA SOURCE DE VÉRITÉ EN PRODUCTION. Cette matrice
        # est semée en base au premier démarrage, puis lue depuis la table
        # `roles_permissions`. Corriger une ligne ici ne change donc RIEN sur une
        # base déjà semée : il faut une migration qui insère les permissions
        # manquantes. La ligne et la base peuvent diverger sans que rien ne le
        # signale, et c'est la base qui gagne.
        "manage_agent3", "run_browser_agent", "import_documents", "manage_mailboxes",
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

# L'ACCÈS AU MAIL EST ACCORDÉ PAR DÉFAUT À TOUS LES RÔLES (08/09) : c'est le
# comportement qu'ils avaient avant que la colonne existe. La direction retire
# ce qu'elle veut dans la matrice ; la base fait foi (migration 039).
for _role in list(ROLE_PERMISSIONS):
    if "access_mail" not in ROLE_PERMISSIONS[_role]:
        ROLE_PERMISSIONS[_role].append("access_mail")

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
    # « Accès au mail » (08/09, demande de Noa) : la colonne qui dit qui lit
    # la messagerie — avec une boîte unique, c'est elle seule qui décide.
    "access_mail",
    # `manage_mailboxes` a QUITTÉ la matrice (01/09, demande de Noa : la
    # colonne « Gérer les boîtes » disparaît de l'onglet Permissions). La
    # permission EXISTE toujours (délégations, routers/mail.py) et garde ses
    # défauts par rôle : elle ne se règle simplement plus depuis cet écran.
]

# LA MATRICE QUE L'ON MONTRE (14/09, demande de Noa : « que des permissions
# concrètes et compréhensibles pour un profil terrain »).
#
# Ce que l'écran affichait n'était pas ce que le code vérifiait. Sur 17 cases,
# CINQ ne servaient à rien — « Agent 2 (vision) », « Agent 3 (auto-évolution) »,
# « Ses stats », « Ses coûts », « Configurer agents » : aucune ligne du backend
# ne les lit, on pouvait les cocher sans rien changer. « Agent Navigateur » ne
# commandait qu'une page retirée du menu (la navigation du chat ne la lit pas),
# et « Admin système » est la clé des réglages techniques, réservée au super
# admin. Le reste était nommé en jargon (« Dashboard global », « Valider
# skills », « Gérer Agent 3 »).
#
# Chaque case montrée ici correspond donc à un contrôle RÉEL, dit ce qu'elle
# ouvre en mots de tous les jours, et appartient à un groupe. Les permissions
# retirées de l'écran restent valides en base (rien ne casse) ; l'accès aux
# experts se règle personne par personne dans l'onglet Utilisateurs.
#
# UNE CASE NE SE RÈGLE QUE LÀ OÙ ELLE PEUT AGIR. Les écrans d'administration
# (Utilisateurs, Savoir-faire, Connaissances) sont ceux de la direction : cocher
# « Gérer les utilisateurs » pour un profil terrain ne lui ouvrirait rien. Ces
# lignes ne se règlent donc que pour la direction (`roles`) ; le « Journal des
# actions » a quitté l'écran — ses pages sont celles du super admin.
ROLES_METIER = ("direction", "commercial", "bureau_etudes", "conducteur", "administratif", "terrain")
MATRICE = [
    {"groupe": "Au quotidien", "permissions": [
        {"feature": "chat_agent1", "label": "Utiliser l'assistant", "roles": ROLES_METIER,
         "description": "Écrire à l'assistant et lui confier des tâches. Sans elle, la personne ne peut pas se servir du chat."},
        {"feature": "access_mail", "label": "Lire et envoyer les mails", "roles": ROLES_METIER,
         "description": "Lire la messagerie depuis le chat et préparer des réponses. Chaque envoi attend son accord."},
        {"feature": "import_documents", "label": "Importer des fichiers", "roles": ROLES_METIER,
         "description": "Ajouter un tableau Excel ou des documents à la mémoire de l'entreprise (Paramètres → Import de données)."},
        {"feature": "view_dashboard_global", "label": "Voir l'activité de toute l'équipe", "roles": ROLES_METIER,
         "description": "Dans le tableau de bord : les tâches, l'activité et les imports de chacun. Sans elle : seulement les siens."},
    ]},
    {"groupe": "Administration — pour la direction", "permissions": [
        {"feature": "manage_users", "label": "Gérer les utilisateurs", "roles": ("direction",),
         "description": "Créer, modifier et supprimer les profils : rôle, code de connexion, dossiers du mail, horaires."},
        {"feature": "validate_skills", "label": "Valider ce que l'assistant a appris", "roles": ("direction",),
         "description": "Accepter ou écarter les nouvelles compétences, et voir les tâches planifiées de toute l'équipe."},
        {"feature": "manage_agent3", "label": "Enseigner à l'assistant", "roles": ("direction",),
         "description": "Faire le bilan de ce qu'il a appris et lui faire retenir des consignes pour toute l'entreprise."},
        {"feature": "view_costs_global", "label": "Voir ce que coûte l'IA", "roles": ("direction",),
         "description": "Le coût des modèles d'IA, affiché à côté des gains estimés du tableau de bord."},
    ]},
]
FEATURES_MATRICE = [x["feature"] for g in MATRICE for x in g["permissions"]]
FEATURE_DESCRIPTIONS = {x["feature"]: x["description"] for g in MATRICE for x in g["permissions"]}
ROLES_REGLABLES = {x["feature"]: list(x["roles"]) for g in MATRICE for x in g["permissions"]}

FEATURE_LABELS = {
    **{x["feature"]: x["label"] for g in MATRICE for x in g["permissions"]},
    "view_audit_log": "Journal des actions (super admin)",
    # Hors de l'écran, gardés pour les journaux et les anciens appels.
    "chat_agent2": "Agent 2 (vision)",
    "chat_agent3": "Agent 3 (auto-évolution)",
    "view_own_stats": "Ses stats",
    "view_own_costs": "Ses coûts",
    "configure_agents": "Configurer agents",
    "manage_mailboxes": "Gérer les boîtes mail",
    "manage_system": "Réglages techniques (super admin)",
    "run_browser_agent": "Page Navigateur (ancienne)",
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
