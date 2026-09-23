"""
Routes du TRI AVANT LA LECTURE du NAS (15/09, Duret — `nas/tri.py`).

Paramètres → Synchronisations : « Ce que l'assistant apprend du NAS ».
L'administrateur fait PROPOSER un tri par l'IA (elle juge les dossiers sur leurs
noms, sans rien ouvrir), relit, corrige, puis VALIDE : la synchronisation
suivante n'ouvre plus que ce qui est à apprendre. Rien n'est appliqué sans ce
clic, et rien n'est supprimé.

Montées seulement là où le module existe (`main.py`, import optionnel).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status as http
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from security.audit import log_action
from security.rbac import has_permission

logger = logging.getLogger("duret.routers.nas_tri")
router = APIRouter()


class RegleTri(BaseModel):
    chemin: str
    decision: str


class TriBody(BaseModel):
    regles: list[RegleTri]
    age_ans: Optional[int] = None


def _exiger(user: User) -> None:
    if not has_permission(user.role, "manage_system"):
        raise HTTPException(status_code=http.HTTP_403_FORBIDDEN,
                            detail="Réservé à l'administration système.")


@router.get("")
async def lire(current_user: User = Depends(get_current_user)):
    """Les règles en vigueur, la proposition de l'IA, et ce que les règles en
    vigueur feraient sur le catalogue (sans rien ouvrir)."""
    _exiger(current_user)
    from config import settings
    from llm.reglages import rafraichir
    from nas import tri
    from nas.acces import _CATALOGUE, catalogue_pret

    await rafraichir(force=True)
    cat = catalogue_pret()
    regles = tri.regles()
    return {
        "regles": regles, "age_ans": tri.age_ans(),
        "proposition": tri.etat_proposition(),
        # Hors de la boucle principale : sur un gros catalogue, ce calcul occupe
        # le processeur des secondes durant et figeait TOUTE l'API (23/09).
        "estimation": (await asyncio.to_thread(tri.estimer, cat, regles, tri.age_ans(), time.time())) if cat else None,
        "catalogue": _CATALOGUE.get("etat"),
        "ocr_differe": len(tri.ocr_differe()),
        # Les fichiers écartés et POURQUOI (16/09, audit D-27) : un « sans
        # texte » attend un changement du fichier, un « trop lent » attend son
        # prochain essai — et l'écran permet de le reprendre tout de suite.
        "ecartes": tri.resume_ecartes(tri.lire_ecartes(), time.time()),
        "reprise_demandee": tri.reprise_en_attente(),
        "continu": {**tri.etat_continu(),
                    "cycle_minutes": int(getattr(settings, "nas_cycle_minutes", 10)),
                    "palier_minutes": int(getattr(settings, "nas_palier_lecture_minutes", 8))},
        "nuit": {"debut": int(getattr(settings, "nas_ocr_nuit_debut", 21)),
                 "fin": int(getattr(settings, "nas_ocr_nuit_fin", 6))},
    }


@router.post("/proposer")
async def proposer(current_user: User = Depends(get_current_user)):
    """Lance la proposition en fond : quelques minutes (relevé du catalogue, puis
    quelques dizaines d'appels au modèle). L'avancement se lit dans `GET`."""
    _exiger(current_user)
    from nas import tri
    if tri.etat_proposition().get("en_cours"):
        raise HTTPException(status_code=http.HTTP_409_CONFLICT,
                            detail="Une proposition de tri est déjà en cours.")
    asyncio.create_task(tri.proposer(lance_par=current_user.email or ""))
    await log_action(action="nas_tri_propose", user_id=str(current_user.id))
    return {"lance": True}


class ContinuBody(BaseModel):
    active: bool


class RepriseBody(BaseModel):
    tout: bool = False


@router.post("/reprendre")
async def reprendre(body: RepriseBody, current_user: User = Depends(get_current_user)):
    """Réessayer les fichiers écartés. La demande est ENREGISTRÉE et appliquée
    au début de la prochaine synchronisation : celle qui tourne garde sa liste
    en mémoire et l'écraserait. Rien n'est supprimé ; « tout » rouvre aussi les
    fichiers restés sans texte."""
    _exiger(current_user)
    from nas import tri
    demande = tri.demander_reprise(bool(body.tout))
    await log_action(action="nas_reprise_ecartes", user_id=str(current_user.id),
                     metadata={"tout": bool(body.tout)})
    return {"demandee": demande, "ecartes": tri.resume_ecartes(tri.lire_ecartes(), time.time())}


@router.put("/continu")
async def regler_continu(body: ContinuBody, current_user: User = Depends(get_current_user)):
    """Allume ou coupe le palier automatique (un clic, effet au cycle suivant)."""
    _exiger(current_user)
    from llm.reglages import enregistrer as ecrire_reglage
    from nas import tri
    await ecrire_reglage(tri.REGLAGE_CONTINU, "active" if body.active else "desactivee",
                         str(current_user.id))
    if body.active:
        tri._CONTINU.update({"prochain": None, "rien_a_lire": False})
    await log_action(action="nas_integration_continue", user_id=str(current_user.id),
                     metadata={"active": body.active})
    return tri.etat_continu()


@router.put("")
async def valider(body: TriBody, current_user: User = Depends(get_current_user)):
    """Enregistre les décisions (et l'âge maximal). Un chemin hors des dossiers
    ouverts est refusé : une règle qui ne s'appliquerait jamais tromperait."""
    _exiger(current_user)
    from llm.reglages import enregistrer as ecrire_reglage
    from nas import tri
    from nas.acces import dossiers_autorises, normaliser

    racines = dossiers_autorises()
    propres = []
    for r in body.regles:
        if r.decision not in tri.DECISIONS:
            raise HTTPException(status_code=http.HTTP_400_BAD_REQUEST,
                                detail=f"Décision inconnue : {r.decision}")
        c = normaliser(r.chemin)
        if c == "/" or not any(c == x or c.startswith(x + "/") for x in racines):
            raise HTTPException(status_code=http.HTTP_400_BAD_REQUEST,
                                detail=f"« {r.chemin} » n'est pas sous un dossier ouvert du serveur.")
        propres.append({"chemin": c, "decision": r.decision})
    regles = tri.lire_regles(propres)
    if len(propres) > tri.MAX_REGLES:
        raise HTTPException(status_code=http.HTTP_400_BAD_REQUEST,
                            detail=f"{tri.MAX_REGLES} règles au plus.")
    try:
        await ecrire_reglage(tri.REGLAGE, json.dumps(regles, ensure_ascii=False) if regles else "",
                             str(current_user.id))
        if body.age_ans is not None:
            await ecrire_reglage(tri.REGLAGE_AGE, str(body.age_ans), str(current_user.id))
    except ValueError as e:
        raise HTTPException(status_code=http.HTTP_400_BAD_REQUEST, detail=str(e))
    await log_action(action="nas_tri_valide", user_id=str(current_user.id),
                     metadata={"regles": len(regles), "age_ans": body.age_ans})
    return {"regles": regles, "age_ans": tri.age_ans()}
