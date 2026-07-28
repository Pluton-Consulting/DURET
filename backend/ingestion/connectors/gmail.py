"""
Connecteur Gmail / Google Workspace — lecture seule.

Duret & Sols est sur Google Workspace : l'accès serveur passe par un COMPTE DE
SERVICE avec « délégation à l'échelle du domaine ». Le backend emprunte alors
l'identité de chaque boîte (impersonation) sans demander de consentement
individuel, ce qui serait ingérable pour une équipe.

⚠ La délégation domaine est PUISSANTE : le compte de service peut lire
n'importe quelle boîte du domaine. C'est précisément pourquoi :
  * on n'accorde que le scope `gmail.readonly` ;
  * la liste des boîtes synchronisées est BORNÉE (voir `boites_a_synchroniser`) ;
  * l'accès applicatif reste arbitré par `mail.authorization` — ce n'est pas
    parce que le serveur PEUT lire une boîte qu'un utilisateur y a droit.

Adresses : rien n'est codé en dur. Les boîtes viennent des comptes de
l'application (`users.email`), plus d'éventuelles boîtes partagées listées dans
`GMAIL_EXTRA_MAILBOXES`. Inutile de connaître les adresses à l'avance.

Deux dossiers sont ingérés, avec des rôles distincts :
  * INBOX  -> `source_type='email'`      : mémoire d'entreprise, recherche RAG ;
  * SENT   -> `source_type='email_sent'` : apprentissage du STYLE de la personne
    (cf. mail/style.py). Sans ce second flux, aucun profil de style n'existe.
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Optional

from config import settings
from database.connection import get_db
from ingestion.pipeline import ingest_document
from mail.style import source_id as source_id_envoye, PREFIXE_ENVOYE

logger = logging.getLogger("duret.ingestion.gmail")

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_RE_BALISES = re.compile(r"<[^>]+>")


def _texte_du_message(charge: dict) -> str:
    """Extrait le corps lisible d'un message Gmail (préfère le texte brut au HTML)."""

    def _decoder(donnees: str) -> str:
        try:
            return base64.urlsafe_b64decode(donnees + "==").decode("utf-8", "replace")
        except Exception:
            return ""

    def _parcourir(partie: dict) -> tuple[str, str]:
        """Retourne (texte_brut, html) trouvés récursivement."""
        brut = html = ""
        mime = partie.get("mimeType", "")
        donnees = (partie.get("body") or {}).get("data")
        if donnees:
            if mime == "text/plain":
                brut = _decoder(donnees)
            elif mime == "text/html":
                html = _decoder(donnees)
        for sous in partie.get("parts") or []:
            b, h = _parcourir(sous)
            brut = brut or b
            html = html or h
        return brut, html

    brut, html = _parcourir(charge)
    if brut.strip():
        return brut
    if html.strip():
        return _RE_BALISES.sub(" ", html)          # dégradation simple, suffisante pour le RAG
    return ""


def _entete(message: dict, nom: str) -> str:
    for h in (message.get("payload") or {}).get("headers") or []:
        if h.get("name", "").lower() == nom.lower():
            return h.get("value", "")
    return ""


def _service(boite: str):
    """Client Gmail empruntant l'identité de `boite`."""
    import os
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    fichier = settings.google_sa_file
    if not fichier or not os.path.exists(fichier):
        raise NotImplementedError(
            f"Google Workspace non configuré : déposez la clé du compte de service dans "
            f"{fichier or 'GOOGLE_SA_FILE'} et autorisez la délégation domaine "
            "(console Admin > Sécurité > Contrôles des API > Délégation à l'échelle du domaine) "
            f"avec le scope {SCOPES[0]}."
        )
    creds = service_account.Credentials.from_service_account_file(
        fichier, scopes=SCOPES, subject=boite       # subject = la boîte empruntée
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


async def boites_a_synchroniser() -> list[str]:
    """Boîtes à parcourir : comptes actifs de l'application + boîtes partagées.

    On part des utilisateurs plutôt que d'une liste figée : les adresses n'ont
    pas à être connues à l'avance, et une nouvelle recrue est prise en compte
    dès son ajout dans l'application.
    """
    boites: list[str] = []
    async with get_db() as conn:
        rows = await conn.fetch("SELECT email FROM users WHERE actif = true AND email IS NOT NULL")
    for r in rows:
        adresse = (r["email"] or "").strip().lower()
        if "@" in adresse:
            boites.append(adresse)

    for extra in (settings.gmail_extra_mailboxes or "").split(","):
        extra = extra.strip().lower()
        if "@" in extra and extra not in boites:
            boites.append(extra)                    # ex. contact@, compta@

    domaine = (settings.gmail_domain or "").strip().lower()
    if domaine:
        # Garde-fou : ne jamais tenter d'emprunter une identité hors du domaine
        # de l'entreprise (un compte invité ne relève pas de la délégation).
        hors = [b for b in boites if not b.endswith("@" + domaine)]
        for b in hors:
            logger.info("Boîte ignorée (hors domaine %s) : %s", domaine, b)
        boites = [b for b in boites if b.endswith("@" + domaine)]
    return boites


async def _ingerer_dossier(service, boite: str, dossier: str, maximum: int) -> int:
    """Ingère les messages d'un dossier (INBOX ou SENT). Retourne le nombre ingéré."""
    envoyes = dossier == "SENT"
    ingeres = 0
    try:
        liste = service.users().messages().list(
            userId="me", labelIds=[dossier], maxResults=maximum
        ).execute()
    except Exception as e:
        logger.warning("Gmail %s/%s : liste impossible (%s)", boite, dossier, e)
        return 0

    for entree in liste.get("messages", []):
        try:
            message = service.users().messages().get(
                userId="me", id=entree["id"], format="full").execute()
        except Exception as e:
            logger.warning("Gmail %s : message %s illisible (%s)", boite, entree["id"], e)
            continue

        corps = _texte_du_message(message.get("payload") or {})
        if not corps.strip():
            continue

        objet = _entete(message, "Subject")
        expediteur = _entete(message, "From")
        destinataire = _entete(message, "To")
        date = _entete(message, "Date")
        texte = (f"Objet : {objet}\nDe : {expediteur}\nÀ : {destinataire}\nDate : {date}\n\n"
                 f"{corps}")

        if envoyes:
            identifiant = source_id_envoye(boite, entree["id"])
            type_source = PREFIXE_ENVOYE
        else:
            identifiant = f"email:{boite}:{entree['id']}"
            type_source = "email"

        if await ingest_document(
            text=texte,
            source_type=type_source,
            source_id=identifiant,
            source_filename=objet or "(sans objet)",
            access_level=settings.gmail_access_level,
            anonymize=True,       # les mails sont la source la plus chargée en PII
        ):
            ingeres += 1
    return ingeres


async def sync(boites: Optional[list[str]] = None,
               dossiers: tuple[str, ...] = ("INBOX", "SENT"),
               maximum: Optional[int] = None) -> dict:
    """Synchronise les boîtes Gmail, puis met à jour les profils de style.

    `dossiers` permet de ne collecter QUE les envois (apprentissage du style
    déclenché par un utilisateur pour sa propre boîte, cf. mail/collecte.py).
    """
    cibles = boites or await boites_a_synchroniser()
    if not cibles:
        raise NotImplementedError(
            "Aucune boîte à synchroniser : ajoutez des utilisateurs dans l'application "
            "ou renseignez GMAIL_EXTRA_MAILBOXES."
        )

    maximum = maximum or settings.gmail_max_messages
    bilan = {"boites": 0, "recus": 0, "envoyes": 0, "profils": 0, "echecs": []}

    for boite in cibles:
        try:
            service = _service(boite)
        except NotImplementedError:
            raise                              # configuration absente : erreur globale
        except Exception as e:
            # Boîte inexistante, délégation non autorisée... : on continue les autres.
            logger.warning("Gmail : accès impossible à %s (%s)", boite, e)
            bilan["echecs"].append(boite)
            continue

        bilan["boites"] += 1
        if "INBOX" in dossiers:
            bilan["recus"] += await _ingerer_dossier(service, boite, "INBOX", maximum)
        if "SENT" in dossiers:
            bilan["envoyes"] += await _ingerer_dossier(service, boite, "SENT", maximum)

        # Le style se recalcule ici : c'est le seul moment où l'on sait que de
        # nouveaux messages envoyés viennent d'arriver.
        try:
            from mail.style import construire_profil
            profil = await construire_profil(boite)
            if profil.get("profil"):
                bilan["profils"] += 1
        except Exception as e:
            logger.warning("Profil de style non recalculé pour %s : %s", boite, e)

    logger.info("Gmail : %s", bilan)
    return bilan
