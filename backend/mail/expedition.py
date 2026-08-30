"""
L'ENVOI RÉEL d'un message — le geste qui manquait au socle mail.

`rediger_email` produit un BROUILLON et le dit (« Aucun message n'a été
envoyé ») ; jusqu'au 30/08, rien dans l'application ne savait FAIRE PARTIR un
message. L'assistant a même promis d'envoyer (défaut n°4 du 27/08, corrigé au
prompt) précisément parce qu'aucun geste ne le permettait. Ce module ferme la
boucle : rédiger reste gratuit et immédiat, ENVOYER est un skill à effet
EXTERNE — l'accord humain porte sur le destinataire, l'objet et le corps
exacts (payload_hash), et c'est exactement cela qui part.

Il parle au MÊME fournisseur que la lecture (`mail.collecte.fournisseur`) :

  * Outlook — Graph `POST /users/{boîte}/sendMail`, avec le jeton applicatif
    du connecteur. L'application doit détenir l'autorisation `Mail.Send`
    (portail Azure, consentement admin) ; sans elle Graph rend 403, et ce
    module le dit dans les mots de la personne qui devra corriger.
  * Gmail — `users().messages().send`, par le connecteur : la connexion
    PERSONNELLE de la boîte d'abord (le consentement de `mail/google_perso`
    porte déjà le scope d'envoi), l'emprunt d'identité ensuite — délégation
    domaine avec le SEUL scope `gmail.send`, à accorder dans la console Admin.

Les CONSTRUCTEURS de message sont des fonctions pures, séparées de l'appel
réseau : c'est ce qui permet au banc (`test_envoi_mail.py`) de vérifier ce qui
part — destinataires, copies, objet accentué — sans jamais rien envoyer.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("duret.mail.expedition")

# Un jeton d'anonymisation resté orphelin (« [PER_1] », « [EMAIL_2] ») n'est
# pas une valeur : dans un message qui SORT de l'entreprise, il n'a rien à
# faire — même règle que pour un fichier remis à quelqu'un (cf. routines).
# Contrairement au fichier, il n'existe ici aucun repli honnête : on REFUSE,
# et le message d'erreur dit quoi reformuler.
_JETON_ORPHELIN = re.compile(r"\[[A-Z]+_\d+\]")


def porte_un_jeton(texte: str) -> bool:
    """Le texte contient-il un jeton d'anonymisation jamais réhydraté ?"""
    return bool(_JETON_ORPHELIN.search(str(texte or "")))


def _adresses(cc) -> list[str]:
    """Une liste d'adresses propre, quel que soit ce que le modèle a passé."""
    if not cc:
        return []
    if isinstance(cc, str):
        cc = re.split(r"[;,]", cc)
    return [str(a).strip() for a in cc if str(a).strip()][:10]


def _message_graph(destinataire: str, objet: str, corps: str, cc=None) -> dict:
    """Le corps EXACT du POST Graph `sendMail` — pur, donc vérifiable au banc."""
    message = {
        "subject": objet,
        "body": {"contentType": "Text", "content": corps},
        "toRecipients": [{"emailAddress": {"address": destinataire}}],
    }
    copies = _adresses(cc)
    if copies:
        message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in copies]
    # `saveToSentItems` : le message envoyé doit se retrouver dans « Éléments
    # envoyés », sinon la boîte ment à son propriétaire — et l'apprentissage du
    # style (mail/style.py) ne le verrait jamais.
    return {"message": message, "saveToSentItems": True}


def _mime_gmail(boite: str, destinataire: str, objet: str, corps: str, cc=None) -> str:
    """Le message Gmail encodé (base64url), prêt pour `messages().send`."""
    import base64
    from email.mime.text import MIMEText

    mime = MIMEText(corps, "plain", "utf-8")
    mime["To"] = destinataire
    mime["From"] = boite
    mime["Subject"] = objet
    copies = _adresses(cc)
    if copies:
        mime["Cc"] = ", ".join(copies)
    return base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")


async def envoyer_message(boite: str, destinataire: str, objet: str,
                          corps: str, cc=None) -> dict:
    """Fait réellement partir le message, chez le fournisseur configuré.

    Lève avec un message en français quand l'envoi est impossible : l'appelant
    (le skill `envoyer_email`) le restitue tel quel, et la personne sait quoi
    corriger — jamais un succès optimiste sur un échec (leçon nas_deposer).
    """
    from mail.collecte import fournisseur
    nom = fournisseur()                        # lève si rien n'est configuré

    logger.info("Envoi d'un message depuis %s via %s", boite, nom)
    if nom == "outlook":
        import httpx
        from ingestion.connectors.outlook import _jeton

        jeton = await _jeton()
        url = f"https://graph.microsoft.com/v1.0/users/{boite}/sendMail"
        async with httpx.AsyncClient(timeout=30) as client:
            reponse = await client.post(
                url, json=_message_graph(destinataire, objet, corps, cc),
                headers={"Authorization": f"Bearer {jeton}",
                         "Content-Type": "application/json"})
        if reponse.status_code == 202:
            return {"envoye": True, "boite": boite,
                    "destinataire": destinataire, "objet": objet}
        if reponse.status_code == 403:
            raise RuntimeError(
                "Le serveur de courrier refuse l'ENVOI : l'application n'a que "
                "le droit de lecture. Il faut accorder l'autorisation "
                "« Mail.Send » (application) dans le portail Azure, avec le "
                "consentement d'un administrateur.")
        raise RuntimeError(
            f"L'envoi a été refusé par le serveur de courrier "
            f"(HTTP {reponse.status_code}) : {reponse.text[:300]}")

    # Gmail. Le connecteur est propre au client qui vit dans Google Workspace :
    # sur un projet qui n'en a pas, l'erreur dit la vraie cause au lieu d'un
    # ModuleNotFoundError anonyme au fond d'un journal.
    import asyncio

    def _travail() -> None:
        try:
            from ingestion.connectors.gmail import _service_envoi
        except ImportError as e:
            raise RuntimeError(
                "Ce projet n'a pas de connecteur Gmail : l'envoi n'est pas "
                "configuré pour ce fournisseur de courrier.") from e
        service = _service_envoi(boite)
        service.users().messages().send(
            userId="me",
            body={"raw": _mime_gmail(boite, destinataire, objet, corps, cc)},
        ).execute()

    try:
        await asyncio.to_thread(_travail)
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001 — l'API Google lève ses propres types
        texte = str(e)
        if "insufficient" in texte.lower() or "403" in texte:
            raise RuntimeError(
                "Le serveur de courrier refuse l'ENVOI : le consentement ne "
                "porte que la lecture. Reliez à nouveau la boîte (Paramètres > "
                "Ma boîte Google) ou accordez le scope gmail.send à la "
                "délégation domaine (console Admin).") from e
        raise RuntimeError(f"L'envoi a échoué : {texte[:300]}") from e
    return {"envoye": True, "boite": boite,
            "destinataire": destinataire, "objet": objet}
