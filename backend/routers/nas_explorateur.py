"""
L'EXPLORATEUR DU NAS DANS LE TABLEAU DE BORD (23/09, Duret).

Demande de Noa : naviguer dans le serveur de fichiers directement depuis
l'application, en comparant deux options — un explorateur refait ici (ces
routes), et le site Synology officiel affiché dans un cadre (`/acces` ne fait
qu'en donner l'adresse). RÉSERVÉ AU SUPER_ADMIN le temps de la comparaison :
toute route répond 403 aux autres rôles, quel que soit l'écran.

RIEN DE NEUF CÔTÉ NAS : on réutilise les gestes de l'assistant, avec leurs
garde-fous — confinement aux dossiers ouverts (`nas.acces.verifier`), niveau
d'accès par dossier selon le rôle (`security.lecteur.au_nom_de`), catalogue
pour la recherche par nom, plafond de taille AVANT le téléchargement, dépôt
dans l'atelier de la personne pour l'aperçu et le téléchargement
(`garantir_fichier_lu`). Aucun appel au modèle, aucune écriture sur le NAS :
l'explorateur LIT.
"""
from __future__ import annotations

import logging
import posixpath
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from security.audit import log_action

logger = logging.getLogger("duret.routers.nas_explorateur")
router = APIRouter()


def _exiger(user: User) -> None:
    if (getattr(user, "role", "") or "").strip().lower() != "super_admin":
        raise HTTPException(status_code=403, detail="Réservé au super administrateur.")


def _refus(e: Exception) -> HTTPException:
    """Un refus du NAS se DIT (chemin hors périmètre, serveur injoignable)."""
    from nas.acces import NasIndisponible, NasRefuse
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, NasRefuse):
        return HTTPException(status_code=403, detail=str(e) or "Chemin non autorisé.")
    if isinstance(e, NasIndisponible):
        return HTTPException(status_code=503, detail=str(e) or "Le NAS ne répond pas.")
    logger.warning("Explorateur NAS : %s", e)
    return HTTPException(status_code=502, detail=f"Le NAS n'a pas pu répondre ({type(e).__name__}).")


def _adresse_dsm() -> Optional[str]:
    """L'adresse du site Synology : l'adresse directe si elle est configurée,
    sinon QuickConnect."""
    from config import settings
    directe = (getattr(settings, "synology_base_url", None) or "").strip().rstrip("/")
    if directe:
        return directe + "/"
    qc = (getattr(settings, "synology_quickconnect_id", None) or "").strip()
    return f"https://{qc}.quickconnect.to/" if qc else None


@router.get("/acces")
async def acces(current_user: User = Depends(get_current_user)):
    """Sonde de l'écran : 200 = le composant s'affiche, 403 = rien."""
    _exiger(current_user)
    from nas.acces import dossiers_autorises
    return {"explorateur": bool(dossiers_autorises()), "dsm": _adresse_dsm()}


def _trier(entrees: list[dict]) -> list[dict]:
    return sorted(entrees, key=lambda e: (not e.get("dossier"), str(e.get("nom") or "").lower()))


@router.get("/lister")
async def lister(chemin: Optional[str] = Query(None), current_user: User = Depends(get_current_user)):
    """Le contenu d'un dossier, TOUTES ses entrées ; sans chemin, les racines ouvertes."""
    _exiger(current_user)
    from nas.acces import connexion, dossiers_autorises, _lister_ouvert
    from security.lecteur import au_nom_de
    if not (chemin or "").strip():
        racines = dossiers_autorises()
        return {"chemin": None, "total": len(racines), "racines": True,
                "entrees": [{"nom": posixpath.basename(r) or r, "chemin": r, "dossier": True}
                            for r in racines]}
    try:
        with au_nom_de(current_user):
            async with connexion() as (client, base, sid):
                lu = await _lister_ouvert(client, base, sid, chemin, tout=True)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    return {"chemin": lu["chemin"], "total": lu["total"], "entrees": _trier(lu["entrees"])}


@router.get("/chercher")
async def chercher(motif: str = Query(..., min_length=2), dossier: Optional[str] = Query(None),
                   current_user: User = Depends(get_current_user)):
    """Recherche par NOM (catalogue du NAS), dans un dossier ou partout."""
    _exiger(current_user)
    from outils.nas import chercher as chercher_nas
    from security.lecteur import au_nom_de
    try:
        with au_nom_de(current_user):
            trouve = await chercher_nas(motif.strip(), (dossier or "").strip() or None)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    resultats = [{"nom": r.get("nom"), "chemin": r.get("chemin"), "dossier": bool(r.get("dossier")),
                  "octets": r.get("octets"), "modifie": r.get("modifie")}
                 for r in (trouve.get("resultats") or [])]
    return {"motif": motif, "total": trouve.get("nombre", len(resultats)),
            "partiel": "INTERROMPU" in str(trouve.get("note") or ""),
            "resultats": resultats}


class OuvrirBody(BaseModel):
    chemin: str


@router.post("/ouvrir")
async def ouvrir(body: OuvrirBody, current_user: User = Depends(get_current_user)):
    """Un fichier → la carte du chat (aperçu, téléchargement), sans lecture du
    texte : l'explorateur montre, il n'analyse pas."""
    _exiger(current_user)
    from ingestion.connectors import synology as c
    from nas.acces import MAX_OCTETS_TELECHARGEMENT, _taille_ouverte, connexion, verifier
    from security.lecteur import au_nom_de
    from skills.affichage import garantir_fichier_lu, octets_lisibles
    try:
        with au_nom_de(current_user):
            vise = verifier(body.chemin)
            nom = posixpath.basename(vise)
            async with connexion() as (client, base, sid):
                taille, _ = await _taille_ouverte(client, base, sid, vise)
                if taille and taille > MAX_OCTETS_TELECHARGEMENT:
                    return {"chemin": vise, "octets": taille, "trop_lourd": True,
                            "message": (f"« {nom} » pèse {octets_lisibles(taille)} : trop lourd pour "
                                        "l'aperçu. Ouvrez-le depuis le site Synology.")}
                brut, raison = await c._telecharger_ou_raison(client, base, sid, vise)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    if not brut:
        raise HTTPException(status_code=404,
                            detail=f"« {nom} » n'a pas pu être lu : {raison or 'le NAS n’a rien rendu'}.")
    depot = garantir_fichier_lu({}, nom, brut, str(current_user.id))
    if not depot.get("bloc_ui"):
        raise HTTPException(status_code=500,
                            detail="Le fichier a été lu mais n'a pas pu être préparé pour l'aperçu.")
    try:
        await log_action(action="nas_explorateur_ouverture", user_id=str(current_user.id),
                         metadata={"octets": len(brut),
                                   "extension": nom.rsplit(".", 1)[-1].lower() if "." in nom else ""})
    except Exception:  # noqa: BLE001
        pass
    return {"chemin": vise, "octets": len(brut), "bloc_ui": depot["bloc_ui"]}
