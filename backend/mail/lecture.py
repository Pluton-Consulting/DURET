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

UNE PÉRIODE ET UN COMPTE (22/08/2026). « Les mails de la semaine » rendait les
25 derniers messages, point — sans dire combien il y en avait eu, ni même si
les 25 couvraient la semaine. Le détail reste borné (on résume, on ne rapatrie
pas la boîte), mais le COMPTE est désormais exact et séparé du détail : le
fournisseur sait compter, il suffit de le lui demander. Dire « 84 messages
cette semaine, voici les 25 plus récents » n'est pas la même chose que rendre
25 messages en silence.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from mail.collecte import fournisseur

logger = logging.getLogger("duret.mail.lecture")

DOSSIERS = {
    "outlook": {"recus": "inbox", "envoyes": "sentitems"},
    "gmail": {"recus": "INBOX", "envoyes": "SENT"},
}

MAX_MESSAGES = 25
MAX_APERCU = 800
# Le compte exact d'une période se fait en parcourant des identifiants (pas les
# messages) : bon marché, mais pas gratuit. Au-delà, on dit « plus de N ».
MAX_COMPTE = 5000

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


# ── La période, dans les mots où on la demande ──────────────────────────────
_RE_JOURS = re.compile(r"^\s*(\d{1,5})\s*(j|jour|jours|d|day|days)?\s*$", re.I)
_MOTS_PERIODE = {
    "aujourd'hui": 0, "aujourdhui": 0, "today": 0,
    "hier": 1, "yesterday": 1,
    "semaine": 7, "cette semaine": 7, "7 jours": 7, "week": 7, "1s": 7,
    "15 jours": 15, "quinzaine": 15,
    "mois": 30, "ce mois": 30, "30 jours": 30, "month": 30,
    "trimestre": 90,
}


def depuis_quand(valeur) -> Optional[datetime]:
    """« 7j », « semaine », « 2026-08-15 » → l'instant de départ, en UTC.

    Rend None quand rien n'est demandé (ou quand la valeur est illisible) : on
    lit alors simplement les plus récents, comme avant. Une période mal comprise
    ne doit jamais faire échouer une lecture — elle l'élargit.
    """
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, (int, float)):
        jours = int(valeur)
    else:
        texte = str(valeur).strip().lower()
        if texte in _MOTS_PERIODE:
            jours = _MOTS_PERIODE[texte]
        else:
            m = _RE_JOURS.match(texte)
            if m:
                jours = int(m.group(1))
            else:
                # Une date ISO, avec ou sans heure.
                try:
                    d = datetime.fromisoformat(texte.replace("z", "+00:00").replace("Z", "+00:00"))
                    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
                except ValueError:
                    return None
    jours = max(0, min(jours, 3650))
    debut = datetime.now(timezone.utc) - timedelta(days=jours)
    # « Les 7 derniers jours » se compte en journées pleines : on part de minuit.
    return debut.replace(hour=0, minute=0, second=0, microsecond=0)


async def _lire_outlook(boite: str, dossier: str, limite: int,
                        depuis: Optional[datetime]) -> tuple[list[dict], Optional[int]]:
    import httpx
    from ingestion.connectors.outlook import _jeton

    jeton = await _jeton()
    # `$count=true` rend le TOTAL de ce que le filtre retient, indépendamment de
    # `$top` : c'est ce qui permet de dire « 84 messages cette semaine » en ne
    # rapatriant que les 25 premiers. Il exige l'en-tête ConsistencyLevel.
    url = (f"https://graph.microsoft.com/v1.0/users/{boite}/mailFolders/{dossier}/messages"
           f"?$top={limite}&$orderby=receivedDateTime desc&$count=true"
           "&$select=subject,from,toRecipients,receivedDateTime,bodyPreview,isRead")
    if depuis:
        url += f"&$filter=receivedDateTime ge {depuis.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {jeton}",
                                           "ConsistencyLevel": "eventual"})
        r.raise_for_status()
        corps = r.json()
        messages = corps.get("value", [])
        total = corps.get("@odata.count")

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
    return resultats, (int(total) if total is not None else None)


async def _lire_gmail(boite: str, dossier: str, limite: int,
                      depuis: Optional[datetime]) -> tuple[list[dict], Optional[int]]:
    import asyncio

    # Le cache des connexions personnelles se recharge ICI, tant qu'une boucle
    # asyncio tourne encore : `_service` (dans le thread) ne sait que le lire.
    from mail import google_perso
    await google_perso.rafraichir()

    def _travail() -> tuple[list[dict], Optional[int]]:
        from ingestion.connectors.gmail import _service, _entete, _texte_du_message
        service = _service(boite)
        # Gmail filtre par requête, dans sa propre syntaxe. `after:` prend une
        # date à la journée — cohérent avec le départ à minuit de depuis_quand.
        requete = f"after:{depuis.strftime('%Y/%m/%d')}" if depuis else None
        commun = {"userId": "me", "labelIds": [dossier]}
        if requete:
            commun["q"] = requete
        liste = service.users().messages().list(maxResults=limite, **commun).execute()
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

        # LE COMPTE. `resultSizeEstimate` est une estimation, et une estimation
        # n'est pas un chiffre qu'on annonce. Sans période, l'étiquette porte
        # son total exact. Avec période, on parcourt les identifiants (500 par
        # page, sans le contenu) : exact, et bon marché jusqu'à MAX_COMPTE.
        total: Optional[int]
        if not requete:
            try:
                total = int(service.users().labels().get(userId="me", id=dossier)
                            .execute().get("messagesTotal") or 0)
            except Exception:  # noqa: BLE001
                total = None
        else:
            total, jeton = 0, None
            while True:
                page = service.users().messages().list(
                    maxResults=500, pageToken=jeton, fields="nextPageToken,messages/id",
                    **commun).execute()
                total += len(page.get("messages", []))
                jeton = page.get("nextPageToken")
                if not jeton or total >= MAX_COMPTE:
                    break
        return resultats, total

    # Le client Google est synchrone : hors de la boucle événementielle.
    return await asyncio.to_thread(_travail)


async def lire_boite(boite: str, dossier: str = "recus",
                     limite: int = 10, depuis=None) -> dict:
    """Derniers messages d'une boîte, lus en direct — et leur nombre.

    `dossier` : « recus » ou « envoyes ». `depuis` : une période (« 7j »,
    « semaine ») ou une date ISO ; sans lui, les plus récents. L'appelant DOIT
    avoir vérifié l'accès.
    """
    nom = fournisseur()                       # lève si rien n'est configuré
    cle = "envoyes" if str(dossier).lower().startswith("env") else "recus"
    limite = max(1, min(int(limite or 10), MAX_MESSAGES))
    debut = depuis_quand(depuis)

    logger.info("Lecture de %s (%s, %d messages%s) via %s", boite, cle, limite,
                f", depuis {debut.date()}" if debut else "", nom)
    if nom == "outlook":
        messages, total = await _lire_outlook(boite, DOSSIERS["outlook"][cle], limite, debut)
    else:
        messages, total = await _lire_gmail(boite, DOSSIERS["gmail"][cle], limite, debut)

    internes = sum(1 for m in messages if m.get("expediteur_interne"))
    automatiques = sum(1 for m in messages if m.get("expediteur_automatique"))

    # Ce que le modèle doit DIRE du compte — dans les mots exacts, parce que
    # « 25 messages » et « 84 messages dont voici les 25 derniers » ne sont pas
    # la même information, et c'est la seconde qu'on demande.
    if total is None:
        compte = (f"{len(messages)} messages lus ; le total de la boîte n'a pas pu être "
                  "obtenu du fournisseur.")
    elif debut:
        compte = (f"{total}{'+' if total >= MAX_COMPTE else ''} message(s) reçu(s) depuis le "
                  f"{debut.date().strftime('%d/%m/%Y')}"
                  + (f", dont voici les {len(messages)} plus récents." if total > len(messages)
                     else ", tous détaillés ci-dessous."))
    else:
        compte = (f"La boîte contient {total} message(s) dans ce dossier ; voici les "
                  f"{len(messages)} plus récents.")

    return {
        "boite": boite, "dossier": cle, "nombre": len(messages),
        "total_periode": total,
        "periode_depuis": debut.isoformat() if debut else None,
        "tronque": bool(total is not None and total > len(messages)),
        "compte": compte,
        "domaine_entreprise": _domaine_entreprise(),
        "expediteurs_internes": internes,
        "expediteurs_automatiques": automatiques,
        # Dit explicitement ce que cet échantillon N'EST PAS. Sans cela, le
        # modèle tirait des conclusions sur l'entreprise entière à partir de
        # dix bulletins d'information reçus le matin même.
        "pour_analyser_tout_le_courrier": (
            f"Le DÉTAIL est borné à {MAX_MESSAGES} messages d'UNE boîte ; le COMPTE, lui, "
            "est exact. Pour analyser l'ensemble du courrier de l'entreprise, la seule "
            "voie est `lancer_enrichissement`."),
        "portee": (f"{compte} Un échantillon récent, pas un inventaire de l'entreprise. "
                   "Une adresse dont expediteur_interne vaut false n'appartient PAS à "
                   "l'entreprise."),
        "messages": messages,
    }
