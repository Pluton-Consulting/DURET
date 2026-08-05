"""
Échelle des niveaux d'accès — source unique.

Elle vivait dans `vectorstore/client.py`, qui importe la base de données. Or le
catalogue de skills doit consulter la même échelle sans rien tirer d'autre : un
mapping de rôles n'a aucune raison d'exiger un pilote Postgres.

Une seule définition, à dessein. Deux copies auraient divergé au premier rôle
ajouté, et un décalage entre « ce que le RAG laisse voir » et « ce que le
catalogue laisse voir » se lit comme une fuite.
"""
from __future__ import annotations

# Un rôle accède à tous les niveaux inférieurs au sien.
ROLE_ACCESS_LEVELS: dict[str, list[str]] = {
    "super_admin":   ["all", "commercial_plus", "bureau_etudes_plus", "direction_only", "admin_only"],
    "direction":     ["all", "commercial_plus", "bureau_etudes_plus", "direction_only", "admin_only"],
    "bureau_etudes": ["all", "commercial_plus", "bureau_etudes_plus"],
    "commercial":    ["all", "commercial_plus"],
    "conducteur":    ["all", "commercial_plus"],
    "administratif": ["all"],
    "terrain":       ["all"],
}

NIVEAUX = ("all", "commercial_plus", "bureau_etudes_plus", "direction_only", "admin_only")


def niveaux_visibles(role: str | None) -> set[str]:
    """Niveaux qu'un rôle peut voir.

    Un rôle inconnu — mal orthographié, supprimé, absent du mapping — obtient le
    niveau le plus bas. Une faute de frappe ne doit jamais ouvrir un accès.
    """
    return set(ROLE_ACCESS_LEVELS.get((role or "").strip(), ["all"]))
