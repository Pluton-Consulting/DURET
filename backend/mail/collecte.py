"""
Collecte des messages ENVOYÉS d'UNE boîte, pour l'apprentissage du style.

Sert le parcours libre-service : chacun se connecte avec son compte et demande
à l'assistant d'apprendre SA façon d'écrire. Contrairement à la synchronisation
globale (réservée à l'administration, qui parcourt toutes les boîtes), cette
collecte est déclenchée par l'utilisateur et strictement limitée à une boîte
dont `mail.authorization` lui a reconnu l'accès.

Indépendant du fournisseur : le connecteur est choisi d'après la configuration
présente, ce qui permet de garder le même code sur les deux projets (l'un est
sur Microsoft 365, l'autre sur Google Workspace).
"""
from __future__ import annotations

import logging
import os

from config import settings

logger = logging.getLogger("duret.mail.collecte")

# Dossier « éléments envoyés » selon le fournisseur.
DOSSIER_ENVOYES = {"outlook": "sentitems", "gmail": "SENT"}


def _module_present(chemin: str) -> bool:
    """Le module est-il installe dans CE projet ? Sans le charger."""
    import importlib.util
    try:
        return importlib.util.find_spec(chemin) is not None
    except (ImportError, ValueError):
        return False


def fournisseur() -> str:
    """'outlook', 'gmail', ou lève si rien n'est configuré."""
    choix = (getattr(settings, "mail_provider", "auto") or "auto").strip().lower()
    if choix in ("outlook", "gmail"):
        return choix

    if settings.ms_tenant_id and settings.ms_client_id and settings.ms_client_secret:
        return "outlook"

    import os
    fichier = getattr(settings, "google_sa_file", None)
    # UN FOURNISSEUR N'EST CHOISI QUE SI SON CONNECTEUR EXISTE ICI.
    #
    # Les connecteurs de courrier sont propres au client : Duret lit dans Google
    # Workspace, Symbiose dans Microsoft 365, et `gmail.py` n'est donc present
    # que d'un cote. C'est voulu. Mais ce fichier-ci est du SOCLE COMMUN, et il
    # se contentait de la presence d'une cle de compte de service Google pour
    # renvoyer « gmail » : dans le projet ou le module n'existe pas, l'import
    # plus bas levait un ModuleNotFoundError, c'est-a-dire une trace technique
    # au lieu du message qui dit quoi configurer.
    #
    # `find_spec` ne charge rien, il regarde seulement si le module est
    # trouvable. Meme technique que le controle des connecteurs au demarrage.
    # Trois façons d'être « configuré côté Google » : la clé du compte de
    # service en fichier, la même en variable, ou le client OAuth des
    # connexions PERSONNELLES (Paramètres > Ma boîte Google) — ce dernier
    # suffit : chaque boîte reliée porte son propre consentement.
    google_pret = bool(
        (fichier and os.path.exists(fichier))
        or (getattr(settings, "google_sa_json", None) or "").strip()
        or ((getattr(settings, "google_oauth_client_id", None) or "").strip()
            and (getattr(settings, "google_oauth_client_secret", None) or "").strip())
    )
    if google_pret and _module_present("ingestion.connectors.gmail"):
        return "gmail"

    raise NotImplementedError(
        "Aucune messagerie configurée : renseignez les identifiants Microsoft 365 "
        "(MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET), déposez la clé du "
        "compte de service Google (GOOGLE_SA_FILE / GOOGLE_SA_JSON), ou "
        "configurez le client OAuth des connexions personnelles "
        "(GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET)."
    )


async def collecter_envoyes(boite: str, maximum: int | None = None) -> dict:
    """Ingère les derniers messages ENVOYÉS de `boite` (et rien d'autre).

    L'appelant DOIT avoir vérifié l'accès à la boîte au préalable : cette
    fonction ne fait aucun contrôle de droits, elle exécute.
    """
    nom = fournisseur()
    maximum = maximum or settings.mail_style_samples

    if nom == "outlook":
        from ingestion.connectors.outlook import sync
    else:
        from ingestion.connectors.gmail import sync

    logger.info("Collecte des envois de %s via %s (max %d)", boite, nom, maximum)
    bilan = await sync(boites=[boite], dossiers=(DOSSIER_ENVOYES[nom],), maximum=maximum)
    return {"fournisseur": nom, **bilan}
