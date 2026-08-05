"""
Skill natif : lancer la campagne d'enrichissement depuis le chat.

Il existe pour une raison précise : demander « lis toutes les boîtes et
enrichis-toi » doit se dire en français, pas se cliquer dans un écran
d'administration. Mais l'action porte sur la correspondance de l'entreprise
entière — elle est donc réservée à l'administration système, et la vérification
se fait ICI, sur l'identité RECHARGÉE au moment d'agir, jamais sur ce que
raconte la conversation.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException, status

logger = logging.getLogger("duret.learning.skills")

PERMISSION = "manage_system"


async def lancer_enrichissement(data: dict, user) -> dict:
    """Démarre la campagne. Ne bloque pas : elle dure des heures."""
    from security.rbac import has_permission
    from learning import enrichissement

    role = getattr(user, "role", "")
    if not has_permission(role, PERMISSION):
        # Fail-closed : un compte sans ce droit n'apprend rien de ce refus,
        # sinon le message deviendrait un moyen de cartographier les rôles.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette campagne lit toutes les boîtes mail : elle est réservée "
                   "à l'administration système.")

    if enrichissement.etat().get("en_cours"):
        etat = enrichissement.etat()
        return {"deja_en_cours": True, "phase": etat.get("phase"),
                "boite_courante": etat.get("boite_courante"),
                "message": "Une campagne est déjà en cours, inutile d'en lancer une seconde."}

    collecter = data.get("collecter")
    collecter = True if collecter is None else bool(collecter)
    try:
        lots = int(data.get("max_lots_par_boite") or 8)
    except (TypeError, ValueError):
        lots = 8

    # Le modèle principal est EXIGÉ par défaut : ce que la campagne écrit
    # reste en mémoire, il ne doit pas venir d'un modèle de repli.
    exiger = data.get("exiger_modele_principal")
    exiger = True if exiger is None else bool(exiger)

    asyncio.create_task(enrichissement.executer(
        lance_par=getattr(user, "email", "?"),
        collecter=collecter,
        max_lots_par_boite=max(1, min(lots, 40)),
        exiger_modele_principal=exiger))

    return {
        "lance": True,
        "message": ("Campagne lancée en tâche de fond : synchronisation des boîtes, "
                    "profil d'écriture par personne, puis lecture du corpus. "
                    "Elle dure plusieurs heures sur un corpus complet."),
        "a_savoir": ("Les connaissances déduites de plusieurs boîtes ne sont plus "
                     "rattachables à une personne : elles sont rangées en accès "
                     "direction. Les compétences arrivent en brouillon désactivé, "
                     "à relire avant validation."),
        "modele": "Campagne exécutée sur le modèle principal ; elle s'arrête "
           "plutôt que de se replier sur un modèle de moindre qualité.",
        "suivi": "Onglet Auto-Évolution, ou demande-moi « où en est l'enrichissement ».",
    }


async def statut_enrichissement(data: dict, user) -> dict:
    """Avancement de la campagne. Lecture seule."""
    from security.rbac import has_permission
    from learning import enrichissement

    if not has_permission(getattr(user, "role", ""), PERMISSION):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Réservé à l'administration système.")
    etat = enrichissement.etat()
    if not etat.get("phase"):
        return {"message": "Aucune campagne n'a encore été lancée."}
    return etat
