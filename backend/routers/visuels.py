"""
Servir les visuels générés (voir visuels/depot.py).

Module propre à l'offre visuelle de ce client : `main.py` le monte par un
import OPTIONNEL, identique chez tous les clients — là où le module n'existe
pas, la route n'existe pas, et aucun fichier partagé ne diverge.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from auth.dependencies import get_current_user
from database.models import User

logger = logging.getLogger("symbiose.routers.visuels")
router = APIRouter()


@router.get("/{cle}")
async def visuel(cle: str, current_user: User = Depends(get_current_user)):
    from visuels.depot import lire, peut_lire
    # LE PROPRIÉTAIRE, PAS SEULEMENT LA CONNEXION (16/09, audit D-03/S-03). Un refus
    # répond comme un visuel absent : une clé devinée ne dit pas qu'elle existe.
    resultat = lire(cle) if peut_lire(cle, current_user) else None
    if not resultat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Visuel inconnu ou supprimé")
    octets, mime = resultat
    # `Vary: Authorization` : sur un poste partagé (« Changer de profil »), le
    # cache du navigateur ne rend pas l'image d'un profil à la session d'un autre.
    return Response(content=octets, media_type=mime,
                    headers={"Cache-Control": "private, max-age=86400", "Vary": "Authorization"})
