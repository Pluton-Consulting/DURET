"""
Ingestion de la BOÎTE UNIQUE (IMAP) dans la mémoire d'entreprise — 08/09.

Le pendant de `gmail.py` et `outlook.py` pour la boîte unique par mot de
passe d'application (`mail/imap.py`) : les messages reçus et envoyés entrent
dans la mémoire (recherche documentaire, apprentissage du style, courrier
cité dans les réponses), avec le MÊME découpage de sources que les autres
connecteurs — `email:<boîte>:<id>` pour les reçus, `email_sent:…` pour les
envoyés — si bien que tout ce qui lit ces sources (RAG, profils de style,
tableau de bord) ne sait pas d'où viennent les messages.

Module du SOCLE : IMAP est le même partout. Il n'existe qu'une boîte : la
liste `boites` des autres connecteurs est acceptée et ignorée, la synchro
porte sur la boîte unique et le dit.

PAS D'ANONYMISATION À L'INGESTION, comme les autres : le masquage a lieu à
la requête, avec la carte du fil (voir le commentaire de `gmail.py`).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config import settings
from ingestion.pipeline import ingest_document
from mail.style import PREFIXE_ENVOYE, source_id as source_id_envoye

logger = logging.getLogger("symbiose.ingestion.imap")

DOSSIERS = {"INBOX": "recus", "SENT": "envoyes"}


def _niveau() -> str:
    return (getattr(settings, "gmail_access_level", None) or getattr(settings, "ms_access_level", None)
            or "all")


async def _ingerer_dossier(boite: str, cle: str, maximum: int) -> int:
    from mail import imap
    envoyes = cle == "envoyes"
    try:
        messages = await asyncio.to_thread(imap.parcourir, imap.dossier_imap(cle), maximum)
    except Exception as e:  # noqa: BLE001 — un dossier absent (« Sent Mail » nommé autrement) ne tue pas la synchro
        logger.warning("IMAP %s/%s : liste impossible (%s)", boite, cle, e)
        return 0
    ingeres = 0
    for uid, m in messages:
        try:
            texte_corps, _ = imap._texte_du_message(m)
        except Exception as e:  # noqa: BLE001
            logger.warning("IMAP %s : message %s illisible (%s)", boite, uid, e)
            continue
        if not (texte_corps or "").strip():
            continue
        objet = imap._decoder(m.get("Subject")) or ""
        texte = (f"Objet : {objet}\nDe : {imap._decoder(m.get('From'))}\nÀ : {imap._decoder(m.get('To'))}\n"
                 f"Date : {m.get('Date') or ''}\n\n{texte_corps}")
        if envoyes:
            identifiant, type_source = source_id_envoye(boite, uid), PREFIXE_ENVOYE
        else:
            identifiant, type_source = f"email:{boite}:{uid}", "email"
        if await ingest_document(text=texte, source_type=type_source, source_id=identifiant,
                                 source_filename=objet or "(sans objet)",
                                 access_level=_niveau(), anonymize=False):
            ingeres += 1
    return ingeres


async def sync(boites: Optional[list[str]] = None,
               dossiers: tuple[str, ...] = ("INBOX", "SENT"),
               maximum: Optional[int] = None) -> dict:
    """Synchronise la boîte unique (reçus et envoyés), puis son profil de style."""
    from mail import imap
    boite = imap.boite_unique()
    if not boite or not imap.configure():
        raise NotImplementedError(
            "Aucune boîte unique configurée : renseignez l'adresse et le mot de passe "
            "d'application dans Paramètres → Clés API → « La boîte mail de l'entreprise ».")
    if boites and any((b or "").strip().lower() != boite for b in boites):
        logger.info("IMAP : une seule boîte existe (%s), la liste demandée est ignorée", boite)
    maximum = maximum or int(getattr(settings, "gmail_max_messages", None) or 100)
    bilan = {"boites": 1, "boite": boite, "recus": 0, "envoyes": 0, "profils": 0, "echecs": []}
    if "INBOX" in dossiers:
        bilan["recus"] = await _ingerer_dossier(boite, "recus", maximum)
    if "SENT" in dossiers:
        bilan["envoyes"] = await _ingerer_dossier(boite, "envoyes", maximum)
    try:
        from mail.style import construire_profil
        profil = await construire_profil(boite)
        if profil.get("profil"):
            bilan["profils"] = 1
    except Exception as e:  # noqa: BLE001 — le style est un complément
        logger.warning("Profil de style non recalculé pour %s : %s", boite, e)
    logger.info("IMAP : %s", bilan)
    return bilan
