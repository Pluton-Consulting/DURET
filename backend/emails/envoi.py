"""
L'ENVOI — un seul chemin vers Resend, pour tous les mails du produit.

Extrait de `routers/auth.py`, où il ne concernait qu'un mail. Le jour où un
deuxième mail part (invitation, rapport, alerte), il doit emprunter ce chemin :
un envoi qui contourne cette fonction est un envoi qui ne sera pas journalisé,
et dont l'échec sera silencieux.

NE LÈVE JAMAIS. Un mail est un effet de bord ; l'appelant a déjà fait son
travail quand il arrive ici. Faire tomber une demande de connexion parce que
Resend a hoqueté priverait l'utilisateur du seul chemin d'entrée — alors même
que son jeton, lui, est valide.
"""
from __future__ import annotations

import logging

import httpx

from config import settings
from emails.marque import MARQUE

logger = logging.getLogger("pluton.emails")


def _expediteur() -> str:
    """« Nom de marque <adresse> » — le nom d'affichage, toujours.

    Sans nom d'affichage, la boîte de réception montre l'adresse technique. Si
    le `.env` en porte déjà un (présence d'un chevron), on le respecte : c'est
    peut-être le seul expéditeur vérifié chez Resend.
    """
    brut = (settings.resend_from_email or "").strip()
    if "<" in brut:
        return brut
    return f"{MARQUE['nom']} <{brut}>" if brut else MARQUE["expediteur_defaut"]


async def envoyer(destinataire: str, objet: str, html: str) -> bool:
    """Envoie un mail. Retourne True si Resend l'a accepté."""
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "User-Agent": "python-httpx/0.27.0",
                },
                json={
                    "from": _expediteur(),
                    "to": destinataire,
                    "subject": objet,
                    "html": html,
                },
                timeout=10.0,
            )
            res.raise_for_status()
        logger.info("Mail « %s » envoyé à %s", objet, destinataire)
        return True
    except Exception as e:  # noqa: BLE001
        detail = getattr(getattr(e, "response", None), "text", "")
        logger.warning("Échec d'envoi à %s (%s) : %s %s", destinataire, objet, e, detail)
        return False
