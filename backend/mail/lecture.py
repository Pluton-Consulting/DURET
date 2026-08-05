"""
Lecture DIRECTE d'une boîte mail — le chaînon qui manquait.

Jusqu'ici, aucun skill n'allait chercher un message. `triage_email_entrant`
attendait qu'on lui COLLE l'objet et le corps, `resume_fil_email` qu'on lui
colle le fil. Le seul chemin vers du courrier passait par la recherche
documentaire, donc par ce qui avait DÉJÀ été ingéré la nuit précédente.

Conséquence observée en production : « lis mes derniers mails » ne déclenchait
rien. L'assistant cherchait en mémoire, ne trouvait pas, et concluait à tort.

Ce module lit la boîte À L'INSTANT, chez le fournisseur configuré. Il ne fait
AUCUN contrôle de droits : c'est l'appelant qui doit avoir obtenu la boîte de
`mail.authorization.verifier_acces`. La règle du projet ne change pas — un
utilisateur ne lit que sa boîte et celles qui lui sont déléguées, un
administrateur les lit toutes, et l'accès est journalisé.

Lecture seule, sans ingestion : consulter ses messages ne doit pas les verser
dans la mémoire d'entreprise. C'est la synchronisation qui décide de ce qui est
mémorisé, pas une consultation ponctuelle.
"""
from __future__ import annotations

import logging
import re

from config import settings
from mail.collecte import fournisseur

logger = logging.getLogger("duret.mail.lecture")

DOSSIERS = {
    "outlook": {"recus": "inbox", "envoyes": "sentitems"},
    "gmail": {"recus": "INBOX", "envoyes": "SENT"},
}

MAX_MESSAGES = 25
MAX_APERCU = 800

_RE_BALISES = re.compile(r"<[^>]+>")


def _apercu(texte: str) -> str:
    """Extrait lisible et borné : on résume, on ne rapatrie pas la boîte."""
    return " ".join((_RE_BALISES.sub(" ", texte or "")).split())[:MAX_APERCU]


async def _lire_outlook(boite: str, dossier: str, limite: int) -> list[dict]:
    import httpx
    from ingestion.connectors.outlook import _jeton

    jeton = await _jeton()
    url = (f"https://graph.microsoft.com/v1.0/users/{boite}/mailFolders/{dossier}/messages"
           f"?$top={limite}&$orderby=receivedDateTime desc"
           "&$select=subject,from,toRecipients,receivedDateTime,bodyPreview,isRead")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {jeton}"})
        r.raise_for_status()
        messages = r.json().get("value", [])

    resultats = []
    for m in messages:
        expediteur = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "")
        destinataires = [((d.get("emailAddress") or {}).get("address") or "")
                         for d in (m.get("toRecipients") or [])]
        resultats.append({
            "objet": m.get("subject") or "(sans objet)",
            "de": expediteur,
            "a": ", ".join(filter(None, destinataires))[:200],
            "date": m.get("receivedDateTime") or "",
            "lu": bool(m.get("isRead")),
            "apercu": _apercu(m.get("bodyPreview") or ""),
        })
    return resultats


async def _lire_gmail(boite: str, dossier: str, limite: int) -> list[dict]:
    import asyncio

    def _travail() -> list[dict]:
        from ingestion.connectors.gmail import _service, _entete, _texte_du_message
        service = _service(boite)
        liste = service.users().messages().list(
            userId="me", labelIds=[dossier], maxResults=limite).execute()
        resultats = []
        for entree in liste.get("messages", []):
            m = service.users().messages().get(
                userId="me", id=entree["id"], format="full").execute()
            resultats.append({
                "objet": _entete(m, "Subject") or "(sans objet)",
                "de": _entete(m, "From"),
                "a": _entete(m, "To")[:200],
                "date": _entete(m, "Date"),
                "lu": "UNREAD" not in (m.get("labelIds") or []),
                "apercu": _apercu(_texte_du_message(m.get("payload") or {})),
            })
        return resultats

    # Le client Google est synchrone : hors de la boucle événementielle.
    return await asyncio.to_thread(_travail)


async def lire_boite(boite: str, dossier: str = "recus",
                     limite: int = 10) -> dict:
    """Derniers messages d'une boîte, lus en direct.

    `dossier` : « recus » ou « envoyes ». L'appelant DOIT avoir vérifié l'accès.
    """
    nom = fournisseur()                       # lève si rien n'est configuré
    cle = "envoyes" if str(dossier).lower().startswith("env") else "recus"
    limite = max(1, min(int(limite or 10), MAX_MESSAGES))

    logger.info("Lecture de %s (%s, %d messages) via %s", boite, cle, limite, nom)
    if nom == "outlook":
        messages = await _lire_outlook(boite, DOSSIERS["outlook"][cle], limite)
    else:
        messages = await _lire_gmail(boite, DOSSIERS["gmail"][cle], limite)

    return {"boite": boite, "dossier": cle, "nombre": len(messages),
            "messages": messages}
