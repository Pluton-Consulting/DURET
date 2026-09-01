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


def _corps(destinataire: str, objet: str, html: str, images=None) -> dict:
    """Le corps EXACT du POST Resend — pur, donc vérifiable au banc."""
    import base64

    charge = {"from": _expediteur(), "to": destinataire,
              "subject": objet, "html": html}
    jointes = []
    for i in images or []:
        octets = i.get("octets")
        if not octets:
            continue
        jointes.append({
            "filename": i.get("nom") or "image.png",
            "content": base64.b64encode(octets).decode("ascii"),
            "content_type": i.get("mime") or "image/png",
            # `content_id` est ce qui distingue une image DU CORPS d'une pièce
            # jointe ordinaire : sans lui, le logo s'afficherait en bas du
            # message au lieu de l'en-tête.
            "content_id": i.get("content_id") or "logo",
        })
    if jointes:
        charge["attachments"] = jointes
    return charge


async def envoyer(destinataire: str, objet: str, html: str,
                  images=None) -> bool:
    """Envoie un mail. Retourne True si Resend l'a accepté.

    `images` : les images AFFICHÉES DANS le corps, chacune
    `{content_id, nom, mime, octets}`. Elles partent en pièces jointes
    « inline » que le HTML retrouve par `cid:` — la seule façon d'afficher un
    vrai logo dans un mail : le SVG n'est rendu par aucun client de messagerie,
    et une image distante est bloquée par défaut chez la plupart (ici elle
    serait de toute façon inatteignable, le site vivant derrière le VPN).
    """
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "User-Agent": "python-httpx/0.27.0",
                },
                json=_corps(destinataire, objet, html, images),
                timeout=10.0,
            )
            res.raise_for_status()
        logger.info("Mail « %s » envoyé à %s", objet, destinataire)
        return True
    except Exception as e:  # noqa: BLE001
        detail = getattr(getattr(e, "response", None), "text", "")
        logger.warning("Échec d'envoi à %s (%s) : %s %s", destinataire, objet, e, detail)
        return False
