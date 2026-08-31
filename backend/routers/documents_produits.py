"""
Téléchargement des documents produits par l'assistant.

Le jeton ne suffit PAS : on vérifie en plus que le document appartient à la
personne connectée. Un lien partagé par erreur, ou deviné, ne donne donc rien —
et le refus est indistinct de l'absence, sinon un 403 confirmerait l'existence
du document à qui tente sa chance.
"""
from __future__ import annotations

import logging
import mimetypes
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from auth.dependencies import get_current_user
from database.models import User

logger = logging.getLogger("duret.routers.documents_produits")

# Le prefixe est pose par main.py, comme pour tous les routeurs.
router = APIRouter()

TYPES_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


def _nom_fichier(titre: str, extension: str) -> str:
    """Nom lisible et sûr : ni séparateur de chemin, ni caractère refusé."""
    propre = "".join(c if (c.isalnum() or c in " -_") else "-" for c in (titre or "document"))
    return f"{' '.join(propre.split())[:80] or 'document'}.{extension}"


@router.get("/{jeton}")
async def telecharger(jeton: str, current_user: User = Depends(get_current_user)):
    from bureautique.atelier import chemin_fichier, fiche

    proprio = str(current_user.id)
    chemin = chemin_fichier(jeton, proprio)
    if not chemin or not os.path.exists(chemin):
        # 404 et non 403 : ne pas révéler qu'un document existe pour un autre.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Document introuvable ou expiré.")

    f = fiche(jeton, proprio) or {}
    extension = (f.get("entete") or {}).get("format", "docx")
    logger.info("Document %s téléchargé par %s", jeton[:8], proprio)
    return FileResponse(
        chemin,
        media_type=TYPES_MIME.get(extension) or mimetypes.guess_type(f"x.{extension}")[0]
        or "application/octet-stream",
        filename=_nom_fichier((f.get("entete") or {}).get("titre"), extension))


@router.delete("/{jeton}")
async def supprimer(jeton: str, current_user: User = Depends(get_current_user)):
    from bureautique.atelier import abandonner
    if not abandonner(jeton, str(current_user.id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Document introuvable.")
    return {"ok": True}
