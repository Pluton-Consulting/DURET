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

from config import settings

logger = logging.getLogger("duret.mail.collecte")

# Dossier « éléments envoyés » selon le fournisseur.
DOSSIER_ENVOYES = {"outlook": "sentitems", "gmail": "SENT"}


def fournisseur() -> str:
    """'outlook', 'gmail', ou lève si rien n'est configuré."""
    choix = (getattr(settings, "mail_provider", "auto") or "auto").strip().lower()
    if choix in ("outlook", "gmail"):
        return choix

    if settings.ms_tenant_id and settings.ms_client_id and settings.ms_client_secret:
        return "outlook"

    import os
    fichier = getattr(settings, "google_sa_file", None)
    if fichier and os.path.exists(fichier):
        return "gmail"

    raise NotImplementedError(
        "Aucune messagerie configurée : renseignez les identifiants Microsoft 365 "
        "(MS_TENANT_ID / MS_CLIENT_ID / MS_CLIENT_SECRET) ou déposez la clé du "
        "compte de service Google (GOOGLE_SA_FILE)."
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
