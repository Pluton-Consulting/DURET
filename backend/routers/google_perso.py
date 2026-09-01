"""
Connexion Google personnelle — le parcours OAuth, côté serveur.

Quatre gestes : obtenir le lien de consentement, recevoir le retour de Google,
dire l'état, se déconnecter. Le RETOUR est le seul endpoint sans en-tête
d'authentification : c'est le navigateur qui y arrive, redirigé par Google —
l'identité voyage dans le `state` signé (JWT court), vérifié avant toute
écriture. Le refresh token, lui, ne sort JAMAIS de la base par l'API.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from auth.dependencies import get_current_user
from config import settings
from database.models import User
from mail import google_perso
from security.audit import log_action

logger = logging.getLogger("duret.routers.google_perso")
router = APIRouter()


def _retour_ecran(resultat: str) -> RedirectResponse:
    """Retour vers l'écran Paramètres, l'issue dans l'URL (l'onglet la lit)."""
    return RedirectResponse(
        settings.app_url.rstrip("/") + f"/parametres?google={resultat}")


@router.get("/lien")
async def lien(current_user: User = Depends(get_current_user)):
    """L'URL de consentement Google pour l'utilisateur connecté."""
    if not google_perso.configurable():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Connexion Google non configurée : renseignez "
                   "GOOGLE_OAUTH_CLIENT_ID et GOOGLE_OAUTH_CLIENT_SECRET.")
    return {"url": google_perso.lien_autorisation(str(current_user.id))}


@router.get("/retour")
async def retour(code: str | None = None, state: str | None = None,
                 error: str | None = None):
    """Le retour de Google, suivi par le navigateur de l'utilisateur.

    Trois issues, toutes redirigées vers Paramètres : `connecte` (la boîte est
    reliée), `refuse` (la personne a annulé chez Google), `erreur` (l'échange a
    échoué — state périmé, code déjà servi, Google injoignable).
    """
    if error or not code or not state:
        return _retour_ecran("refuse")
    try:
        user_id = google_perso.verifier_state(state)
    except Exception:  # noqa: BLE001 - state forgé ou périmé : rien n'est écrit
        return _retour_ecran("erreur")
    try:
        infos = await google_perso.echanger_code(code)
        await google_perso.enregistrer(
            user_id, infos["email"], infos["refresh_token"], infos.get("scope", ""))
    except Exception as e:  # noqa: BLE001
        logger.warning("Connexion Google non aboutie pour %s : %s", user_id, e)
        return _retour_ecran("erreur")
    try:
        await log_action(action="google_connecte", user_id=user_id,
                         metadata={"email": infos["email"]})
    except Exception:  # noqa: BLE001 - le journal ne bloque pas la connexion
        pass
    return _retour_ecran("connecte")


@router.get("/etat")
async def etat(current_user: User = Depends(get_current_user)):
    """Ce que l'onglet affiche. `disponible` distingue « pas configuré »
    (message pour l'administrateur) de « pas encore relié » (bouton)."""
    from database.connection import schema_incomplet
    try:
        ligne = await google_perso.etat(str(current_user.id))
    except Exception as e:  # noqa: BLE001
        if not schema_incomplet(e):
            raise
        # Même raison qu'ailleurs : entre le déploiement du code et
        # l'application des migrations, cette table peut ne pas exister. Rendre
        # « pas encore relié » serait un MENSONGE (le bouton ne marcherait pas
        # davantage) : on nomme la migration qui manque.
        logger.warning("Connexions Google : migration non appliquée")
        return {"disponible": False, "connecte": False, "email": None,
                "depuis": None, "migration_absente": "connexions_google"}
    return {
        "disponible": google_perso.configurable(),
        "connecte": ligne is not None,
        "email": (ligne or {}).get("email"),
        "depuis": (ligne or {}).get("connecte_le"),
    }


@router.delete("/")
async def deconnecter(current_user: User = Depends(get_current_user)):
    """Oublie la connexion et révoque le jeton chez Google (best-effort)."""
    supprime = await google_perso.deconnecter(str(current_user.id))
    if supprime:
        try:
            await log_action(action="google_deconnecte", user_id=str(current_user.id))
        except Exception:  # noqa: BLE001
            pass
    return {"deconnecte": supprime}
