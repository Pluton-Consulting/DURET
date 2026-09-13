"""
Routes du NIVEAU D'ACCÈS PAR DOSSIER du serveur de fichiers (13/09, Duret).

Paramètres → Synchronisations : l'administrateur attribue un niveau à des
dossiers du NAS. Enregistrer les règles RECLASSE aussitôt les documents déjà
importés et relance la carte du classement ; la synchronisation suivante écrit
les nouveaux fichiers au bon niveau (`nas/niveaux.py`).

Montées seulement là où le module existe (`main.py`, import optionnel) :
c'est le socle documentaire de Duret, pas celui du jumeau sur Google Drive.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status as http
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from security.audit import log_action
from security.rbac import has_permission

logger = logging.getLogger("duret.routers.nas_niveaux")
router = APIRouter()

LIBELLES = {
    "all": "Tout le monde",
    "commercial_plus": "Commercial, conducteur et au-dessus",
    "bureau_etudes_plus": "Bureau d'études et direction",
    "direction_only": "Direction uniquement",
    "admin_only": "Administrateurs uniquement",
}
PROFONDEUR_PROPOSEE = 5
DOSSIERS_PROPOSES_MAX = 4000


class Regle(BaseModel):
    chemin: str
    niveau: str


class ReglesBody(BaseModel):
    regles: list[Regle]


def _exiger(user: User) -> None:
    if not has_permission(user.role, "manage_system"):
        raise HTTPException(status_code=http.HTTP_403_FORBIDDEN,
                            detail="Réservé à l'administration système.")


def _echelle() -> list[dict]:
    from security.acces import NIVEAUX, ROLE_ACCESS_LEVELS
    return [{"cle": n, "libelle": LIBELLES.get(n, n),
             "roles": sorted(r for r, vus in ROLE_ACCESS_LEVELS.items() if n in vus)}
            for n in NIVEAUX]


@router.get("")
async def lire(current_user: User = Depends(get_current_user)):
    """Les règles, le niveau par défaut, l'échelle, et les dossiers du NAS à
    proposer (tirés du catalogue : aucun parcours du serveur)."""
    _exiger(current_user)
    from llm.reglages import rafraichir
    from nas import niveaux
    from nas.acces import _CATALOGUE, catalogue_pret, dossiers_autorises

    await rafraichir()
    cat = catalogue_pret() or []
    racines = dossiers_autorises()
    dossiers = sorted({e["chemin"] for e in cat
                       if e.get("dossier") and e.get("chemin")
                       and e["chemin"].count("/") <= PROFONDEUR_PROPOSEE})[:DOSSIERS_PROPOSES_MAX]
    try:
        connaissances = await niveaux.connaissances_des_documents()
    except Exception:  # noqa: BLE001 — l'écran reste utilisable sans ce compte
        connaissances = None
    return {"regles": niveaux.regles(), "defaut": niveaux.defaut(), "echelle": _echelle(),
            "racines": racines, "dossiers": dossiers,
            "catalogue": _CATALOGUE.get("etat"),
            "connaissances_documents": connaissances}


@router.put("")
async def enregistrer(body: ReglesBody, current_user: User = Depends(get_current_user)):
    """Enregistre les règles, reclasse les documents déjà importés, relance la
    carte du classement. Un chemin hors des dossiers ouverts est refusé : une
    règle qui ne s'appliquerait jamais laisserait croire à une protection."""
    _exiger(current_user)
    from llm.reglages import enregistrer as ecrire_reglage
    from nas import niveaux
    from nas.acces import dossiers_autorises, normaliser
    from security.acces import NIVEAUX

    racines = dossiers_autorises()
    propres = []
    for r in body.regles:
        if r.niveau not in NIVEAUX:
            raise HTTPException(status_code=http.HTTP_400_BAD_REQUEST,
                                detail=f"Niveau inconnu : {r.niveau}")
        c = normaliser(r.chemin)
        if c == "/" or not any(c == x or c.startswith(x + "/") for x in racines):
            raise HTTPException(status_code=http.HTTP_400_BAD_REQUEST,
                                detail=f"« {r.chemin} » n'est pas sous un dossier ouvert "
                                       f"du serveur ({', '.join(racines) or 'aucun'}).")
        propres.append({"chemin": c, "niveau": r.niveau})
    if len(propres) > niveaux.MAX_REGLES:
        raise HTTPException(status_code=http.HTTP_400_BAD_REQUEST,
                            detail=f"{niveaux.MAX_REGLES} règles au plus.")
    regles = niveaux.lire_regles(propres)
    await ecrire_reglage(niveaux.REGLAGE, json.dumps(regles, ensure_ascii=False) if regles else "",
                         str(current_user.id))

    bilan = {}
    try:
        bilan = await niveaux.reclasser_documents()
    except Exception as e:  # noqa: BLE001 — les règles sont posées ; le reclassement se DIT
        logger.warning("Reclassement des documents du NAS impossible : %s", e)
        bilan = {"erreur": str(e)[:200]}
    try:
        from classement.carte import rafraichir_carte
        asyncio.create_task(rafraichir_carte())
    except Exception:  # noqa: BLE001
        pass
    await log_action(action="nas_niveaux_modifies", user_id=str(current_user.id),
                     metadata={"regles": len(regles), "reclasses": bilan.get("reclasses")})
    return {"regles": regles, "reclassement": bilan}


@router.post("/reprendre-connaissances")
async def reprendre_connaissances(current_user: User = Depends(get_current_user)):
    """Retire les connaissances que la campagne documentaire a écrites, puis la
    relance : elles seront réécrites au niveau de leurs dossiers.

    POURQUOI UN RETRAIT. Une connaissance est tirée d'un GROUPE de fichiers et
    ne garde pas le lien vers chacun : quand un dossier se ferme, on ne sait pas
    lesquelles en venaient. Les laisser, c'est laisser ouvert ce qu'on vient de
    fermer. Geste d'administrateur, sur clic explicite et confirmé à l'écran.
    """
    _exiger(current_user)
    from learning import enrichissement_docs
    from nas import niveaux

    if enrichissement_docs.etat().get("en_cours"):
        raise HTTPException(status_code=http.HTTP_409_CONFLICT,
                            detail="Une campagne documentaire est déjà en cours.")
    retirees = await niveaux.retirer_connaissances_des_documents()
    await log_action(action="connaissances_documents_reprises", user_id=str(current_user.id),
                     metadata={"retirees": retirees})
    asyncio.create_task(enrichissement_docs.executer(
        lance_par=current_user.email, max_lots_par_niveau=0,
        exiger_modele_principal=True, collecter=True, lance_par_id=current_user.id))
    return {"retirees": retirees, "lance": True}
