"""
Niveau de confidentialité RÉEL d'un document du socle — côté NAS Synology.

MÊME INTERFACE QUE LE JUMEAU (`niveau_reel(source_id, source_type)`), autre
socle documentaire. Sur le Drive, les partages se lisent par l'API en un appel
par fichier ; sur un partage SMB, les droits sont des ACL Windows/Synology que
le compte de synchronisation ne sait pas énumérer proprement à travers SMB —
et un droit mal lu qui OUVRE un accès serait pire que pas de lecture du tout.

Tant que cette lecture n'existe pas, `niveau_reel` rend `None` : la campagne
documentaire (`enrichissement_docs.py`, socle commun) retombe alors sur le
niveau STOCKÉ à l'ingestion — qui se règle PAR DOSSIER dans la configuration
du connecteur, exactement comme les périmètres. C'est le même résultat par un
autre chemin : le classement suit les dossiers du NAS, pas un réglage global.

Le jour où l'énumération des ACL est écrite (Synology propose une API
d'administration dédiée), seule cette fonction change : la campagne, la
traduction en niveaux (`niveau_pour_roles`, `niveau_depuis_permissions`,
gardées identiques au jumeau pour le banc commun) et l'écran n'y verront rien.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.learning.acces_docs")

_TYPES_PUBLICS = ("domain", "anyone")


def niveau_pour_roles(roles) -> str:
    """Le niveau LE PLUS OUVERT dont l'audience est couverte par ces rôles.

    Direction et super_admin sont hors du calcul : ils voient tous les
    niveaux, leur présence dans un partage ne dit rien de son ouverture.
    """
    from security.acces import ROLE_ACCESS_LEVELS

    # RÈGLE STRICTE, choisie contre la fuite : le niveau n'est accordé que si
    # TOUS ceux qu'il rend lecteurs ont réellement accès au fichier.
    toujours = {"super_admin", "direction"}
    presents = set(roles) - toujours
    for niveau in ("all", "commercial_plus", "bureau_etudes_plus"):
        audience = {r for r, vus in ROLE_ACCESS_LEVELS.items() if niveau in vus}
        if audience - toujours <= presents:
            return niveau
    return "direction_only"


def niveau_depuis_permissions(permissions, annuaire: dict) -> str:
    """Traduit une liste de partages en niveau de l'échelle maison.

    Même contrat que le jumeau : un partage « tout le monde » rend « all »,
    une adresse hors annuaire n'élargit rien, aucun compte interne reconnu
    retombe sur le plus restrictif.
    """
    roles = set()
    for p in permissions or []:
        if not isinstance(p, dict):
            continue
        if p.get("type") in _TYPES_PUBLICS:
            return "all"
        adresse = str(p.get("emailAddress") or "").strip().lower()
        if adresse and adresse in annuaire:
            roles.add(annuaire[adresse])
    if not roles:
        return "direction_only"
    return niveau_pour_roles(roles)


async def niveau_reel(source_id: str, source_type: str) -> str | None:
    """Pas encore de lecture d'ACL SMB : on ne sait pas dire, et on le dit.

    `None` rend la main à la campagne, qui applique le niveau stocké à
    l'ingestion (réglé par dossier du NAS). Ne jamais deviner ici : un droit
    inventé qui ouvre un accès serait une fuite, pas un service.
    """
    return None
