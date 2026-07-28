"""
Connecteur Outlook / Microsoft 365 (Microsoft Graph, flux app-only) — lecture seule.

Non utilisé chez Duret & Sols (messagerie Google Workspace) : conservé pour
Le mot de passe seul NE suffit PAS (l'authentification basique est désactivée
par Microsoft) : il faut une application Entra avec une permission
d'APPLICATION, qui permet de lire les boîtes sans consentement individuel.

Prérequis (voir SETUP_CONNECTEURS.md) :
  1. App Entra : ms_tenant_id / ms_client_id / ms_client_secret.
  2. Permission d'application Mail.Read + « Grant admin consent ».
  3. ⚠ RESTREINDRE les boîtes accessibles via ApplicationAccessPolicy. Sans
     cette politique, l'application peut lire TOUTES les boîtes du tenant.

Adresses : rien n'est codé en dur. Les boîtes viennent des comptes de
l'application (`users.email`), plus d'éventuelles boîtes partagées listées dans
`MS_EXTRA_MAILBOXES`. Une nouvelle recrue est prise en compte dès son ajout.

Deux dossiers, deux rôles :
  * inbox      -> `source_type='email'`      : mémoire d'entreprise (RAG) ;
  * sentitems  -> `source_type='email_sent'` : apprentissage du STYLE de la
    personne (cf. mail/style.py). Sans ce second flux, aucun profil n'existe.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from config import settings
from database.connection import get_db
from ingestion.pipeline import ingest_document
from mail.style import source_id as source_id_envoye, PREFIXE_ENVOYE

logger = logging.getLogger("duret.ingestion.outlook")

_RE_BALISES = re.compile(r"<[^>]+>")


def _corps(message: dict) -> str:
    """Corps lisible : le texte brut si Graph le fournit, sinon le HTML nettoyé."""
    corps = message.get("body") or {}
    contenu = corps.get("content") or ""
    if (corps.get("contentType") or "").lower() == "html" and contenu:
        contenu = _RE_BALISES.sub(" ", contenu)
    return (contenu or message.get("bodyPreview") or "").strip()


async def boites_a_synchroniser() -> list[str]:
    """Boîtes à parcourir : comptes actifs de l'application + boîtes partagées."""
    boites: list[str] = []
    async with get_db() as conn:
        rows = await conn.fetch("SELECT email FROM users WHERE actif = true AND email IS NOT NULL")
    for r in rows:
        adresse = (r["email"] or "").strip().lower()
        if "@" in adresse:
            boites.append(adresse)

    for source in (settings.ms_extra_mailboxes, settings.ms_mailbox):
        for extra in (source or "").split(","):
            extra = extra.strip().lower()
            if "@" in extra and extra not in boites:
                boites.append(extra)

    domaine = (settings.ms_domain or "").strip().lower()
    if domaine:
        # Garde-fou : ne jamais tenter de lire une boîte hors du domaine.
        for b in [b for b in boites if not b.endswith("@" + domaine)]:
            logger.info("Boîte ignorée (hors domaine %s) : %s", domaine, b)
        boites = [b for b in boites if b.endswith("@" + domaine)]
    return boites


async def _jeton() -> str:
    import msal
    app = msal.ConfidentialClientApplication(
        settings.ms_client_id,
        authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
        client_credential=settings.ms_client_secret,
    )
    tok = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in tok:
        raise RuntimeError(tok.get("error_description", "Authentification Graph échouée"))
    return tok["access_token"]


async def _ingerer_dossier(client, headers: dict, boite: str,
                           dossier: str, maximum: int) -> int:
    """Ingère un dossier Graph ('inbox' ou 'sentitems'). Retourne le nombre ingéré."""
    envoyes = dossier == "sentitems"
    url = (f"https://graph.microsoft.com/v1.0/users/{boite}/mailFolders/{dossier}/messages"
           f"?$top={maximum}&$select=id,subject,from,toRecipients,sentDateTime,"
           f"receivedDateTime,bodyPreview,body")
    try:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        messages = r.json().get("value", [])
    except Exception as e:
        logger.warning("Graph %s/%s : lecture impossible (%s)", boite, dossier, e)
        return 0

    ingeres = 0
    for m in messages:
        contenu = _corps(m)
        if not contenu:
            continue
        expediteur = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "")
        destinataires = ", ".join(
            ((d.get("emailAddress") or {}).get("address", "")) for d in (m.get("toRecipients") or [])
        )
        date = m.get("sentDateTime") or m.get("receivedDateTime") or ""
        texte = (f"Objet : {m.get('subject', '')}\nDe : {expediteur}\n"
                 f"À : {destinataires}\nDate : {date}\n\n{contenu}")

        if envoyes:
            identifiant = source_id_envoye(boite, m["id"])
            type_source = PREFIXE_ENVOYE
        else:
            identifiant = f"email:{boite}:{m['id']}"
            type_source = "email"

        if await ingest_document(
            text=texte,
            source_type=type_source,
            source_id=identifiant,
            source_filename=m.get("subject") or "(sans objet)",
            access_level=settings.ms_access_level,
            anonymize=True,       # les mails sont la source la plus chargée en PII
        ):
            ingeres += 1
    return ingeres


async def sync(boites: Optional[list[str]] = None,
               dossiers: tuple[str, ...] = ("inbox", "sentitems"),
               maximum: Optional[int] = None) -> dict:
    """Synchronise les boîtes Outlook, puis met à jour les profils de style.

    `dossiers` permet de ne collecter QUE les envois (apprentissage du style
    déclenché par un utilisateur pour sa propre boîte, cf. mail/collecte.py).
    """
    if not (settings.ms_tenant_id and settings.ms_client_id and settings.ms_client_secret):
        raise NotImplementedError(
            "Outlook/M365 non configuré : renseignez MS_TENANT_ID, MS_CLIENT_ID et "
            "MS_CLIENT_SECRET (app Entra + permission d'application Mail.Read + "
            "consentement administrateur).")

    import httpx

    cibles = boites or await boites_a_synchroniser()
    if not cibles:
        raise NotImplementedError(
            "Aucune boîte à synchroniser : ajoutez des utilisateurs dans l'application "
            "ou renseignez MS_EXTRA_MAILBOXES.")

    maximum = maximum or settings.ms_max_messages
    headers = {"Authorization": f"Bearer {await _jeton()}"}
    bilan = {"boites": 0, "recus": 0, "envoyes": 0, "profils": 0, "echecs": []}

    async with httpx.AsyncClient(timeout=60) as client:
        for boite in cibles:
            recus = (await _ingerer_dossier(client, headers, boite, "inbox", maximum)
                     if "inbox" in dossiers else 0)
            envoyes = (await _ingerer_dossier(client, headers, boite, "sentitems", maximum)
                       if "sentitems" in dossiers else 0)
            if recus == 0 and envoyes == 0:
                # Boîte inexistante ou exclue par l'ApplicationAccessPolicy :
                # on la signale et on poursuit avec les autres.
                bilan["echecs"].append(boite)
                continue

            bilan["boites"] += 1
            bilan["recus"] += recus
            bilan["envoyes"] += envoyes

            # Le style se recalcule ici : seul moment où l'on sait que de
            # nouveaux messages envoyés viennent d'arriver.
            try:
                from mail.style import construire_profil
                profil = await construire_profil(boite)
                if profil.get("profil"):
                    bilan["profils"] += 1
            except Exception as e:
                logger.warning("Profil de style non recalculé pour %s : %s", boite, e)

    logger.info("Outlook : %s", bilan)
    return bilan
