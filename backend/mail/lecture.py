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


def _domaine_entreprise() -> str:
    return ((settings.ms_domain or "") or (getattr(settings, "gmail_domain", "") or "")).strip().lower()


_RE_ADRESSE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

# Expéditeurs qui n'ont pas d'auteur humain. Les confondre avec des collègues
# fausse toute lecture d'une boîte de réception, largement peuplée de bulletins
# et de notifications.
_MARQUEURS_AUTOMATIQUES = ("noreply", "no-reply", "no_reply", "donotreply",
                           "notification", "notifications", "digest", "mailer",
                           "postmaster", "newsletter", "info@", "alerte")


def _qualifier(adresse_brute: str) -> dict:
    """Dit ce qu'est un expéditeur : interne à l'entreprise, ou pas.

    Observé en production : faute de cette distinction, le modèle présentait
    `noreply@silae.fr` et `digest@mailinblack.com` comme « des personnes de
    l'entreprise ». Une adresse n'est pas un collègue.
    """
    trouve = _RE_ADRESSE.search(adresse_brute or "")
    adresse = (trouve.group(0) if trouve else "").lower()
    domaine = _domaine_entreprise()
    return {
        "adresse": adresse,
        "interne": bool(adresse and domaine and adresse.endswith("@" + domaine)),
        "automatique": any(m in adresse for m in _MARQUEURS_AUTOMATIQUES),
    }


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
        qualite = _qualifier(expediteur)
        resultats.append({
            "objet": m.get("subject") or "(sans objet)",
            "de": expediteur,
            "expediteur_interne": qualite["interne"],
            "expediteur_automatique": qualite["automatique"],
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
            expediteur = _entete(m, "From")
            qualite = _qualifier(expediteur)
            resultats.append({
                "objet": _entete(m, "Subject") or "(sans objet)",
                "de": expediteur,
                "expediteur_interne": qualite["interne"],
                "expediteur_automatique": qualite["automatique"],
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

    internes = sum(1 for m in messages if m.get("expediteur_interne"))
    automatiques = sum(1 for m in messages if m.get("expediteur_automatique"))
    return {
        "boite": boite, "dossier": cle, "nombre": len(messages),
        "domaine_entreprise": _domaine_entreprise(),
        "expediteurs_internes": internes,
        "expediteurs_automatiques": automatiques,
        # Dit explicitement ce que cet échantillon N'EST PAS. Sans cela, le
        # modèle tirait des conclusions sur l'entreprise entière à partir de
        # dix bulletins d'information reçus le matin même.
        "portee": (f"Les {len(messages)} derniers messages de {boite} ({cle}) — "
                   "un échantillon récent, pas un inventaire de l'entreprise. "
                   "Une adresse dont expediteur_interne vaut false n'appartient "
                   "PAS à l'entreprise."),
        "messages": messages,
    }
