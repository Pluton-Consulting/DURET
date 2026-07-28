"""
Identité d'exécution — l'identité se STOCKE, les droits se RECALCULENT.

Une action peut s'exécuter longtemps après avoir été demandée : réponse à une
validation humaine, tâche planifiée, déclenchement par webhook. Entre-temps, le
compte a pu être désactivé, son rôle changer, une délégation de boîte être
révoquée.

On ne sérialise donc JAMAIS un utilisateur (ni son rôle, ni ses droits) : on ne
conserve que son identifiant, et on recharge son état réel au moment d'agir.
Fail-closed : un compte introuvable ou désactivé renvoie None, et l'appelant doit
abandonner l'action.
"""
from __future__ import annotations

import logging
from typing import Optional

from database.connection import get_db
from database.models import User

logger = logging.getLogger("duret.tasks.identity")


async def charger_executant(user_id: Optional[str]) -> Optional[User]:
    """Recharge l'utilisateur au nom duquel une action va s'exécuter.

    Équivalent de `get_current_user` sans le jeton : même exigence (compte actif),
    mais applicable à une exécution différée qui n'a pas de requête HTTP.
    """
    if not user_id:
        return None
    try:
        async with get_db() as conn:
            ligne = await conn.fetchrow(
                "SELECT * FROM users WHERE id = $1::uuid AND actif = true", str(user_id))
    except Exception as e:  # noqa: BLE001 - une panne de base ne doit pas ouvrir les droits
        logger.warning("Chargement de l'exécutant %s impossible : %s", user_id, e)
        return None

    if ligne is None:
        logger.info("Exécution refusée : compte %s inconnu ou désactivé", user_id)
        return None
    return User(**dict(ligne))
