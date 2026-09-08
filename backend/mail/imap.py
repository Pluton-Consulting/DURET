"""
LA BOÎTE UNIQUE, PAR MOT DE PASSE D'APPLICATION (IMAP + SMTP) — 08/09.

Décision de Noa pour Duret : « on va passer par un seul mail pour tout le
monde, je vais mettre un mot de passe d'application ». Une adresse Gmail, un
mot de passe d'application (Google → Sécurité → Mots de passe des
applications), et tout le monde lit et envoie depuis cette boîte — sans
compte de service, sans délégation de domaine, sans consentement OAuth par
personne, sans Google Workspace.

CE MODULE EST DU SOCLE : IMAP et SMTP sont les mêmes chez tous les
fournisseurs (Gmail, Outlook.com, OVH…). Il ne fait AUCUN contrôle de droits
— c'est `mail.authorization` qui décide QUI lit cette boîte, par la
permission « Accès au mail » de la matrice des rôles. Il rend des fiches de
la même forme que les voies Graph et Gmail (`mail/lecture.py`) : le reste de
la chaîne (skills, cartes, courrier entrant, pièces jointes) ne sait pas
d'où vient le message.

Réglages (`.env`, jamais affichés) : MAIL_PROVIDER=imap (ou laissé en
« auto » : les identifiants suffisent), MAIL_IMAP_USER (l'adresse),
MAIL_IMAP_PASSWORD (le mot de passe d'application), et les hôtes, préréglés
pour Gmail. Les appels réseau sont SYNCHRONES (imaplib, smtplib) : les
appelants les passent dans un thread.

IDENTIFIANT D'UN MESSAGE : son UID IMAP, stable dans un dossier tant que la
boîte n'est pas reconstruite ; une pièce jointe est désignée par le rang de
sa partie dans le message.
"""
from __future__ import annotations

import email
import imaplib
import logging
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email import policy
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from typing import Optional

from config import settings

logger = logging.getLogger("symbiose.mail.imap")

HOTE_IMAP_DEFAUT = "imap.gmail.com"
HOTE_SMTP_DEFAUT = "smtp.gmail.com"
PORT_SMTP_DEFAUT = 587
DOSSIER_ENVOYES_GMAIL = "[Gmail]/Sent Mail"
MAX_FETCH = 50                  # messages rapatriés par listage
DELAI_S = 60


def configure() -> bool:
    """Des identifiants IMAP existent-ils ?"""
    return bool((getattr(settings, "mail_imap_user", None) or "").strip()
                and (getattr(settings, "mail_imap_password", None) or "").strip())


def boite_unique() -> Optional[str]:
    """L'adresse de la boîte unique, ou None : c'est elle que tout le monde lit."""
    u = (getattr(settings, "mail_imap_user", None) or "").strip().lower()
    return u or None


def dossier_imap(cle: str) -> str:
    if str(cle).lower().startswith("env"):
        return (getattr(settings, "mail_imap_dossier_envoyes", None) or DOSSIER_ENVOYES_GMAIL)
    return "INBOX"


def _connexion() -> imaplib.IMAP4_SSL:
    hote = (getattr(settings, "mail_imap_host", None) or HOTE_IMAP_DEFAUT).strip()
    client = imaplib.IMAP4_SSL(hote, 993, ssl_context=ssl.create_default_context(), timeout=DELAI_S)
    client.login(boite_unique() or "", (getattr(settings, "mail_imap_password", None) or "").strip())
    return client


def _decoder(valeur) -> str:
    if valeur is None:
        return ""
    try:
        return str(make_header(decode_header(str(valeur))))
    except Exception:  # noqa: BLE001 — un en-tête mal encodé reste lisible tel quel
        return str(valeur)


def _date_imap(d: Optional[datetime]) -> str:
    return d.strftime("%d-%b-%Y")


def _criteres(depuis: Optional[datetime], recherche: Optional[str], avant: Optional[datetime]) -> str:
    """Les critères IMAP SEARCH. La recherche porte sur objet ET corps (TEXT) ;
    IMAP ne connaît que la journée pour les dates, comme Gmail."""
    parts = []
    if depuis:
        parts += ["SINCE", _date_imap(depuis)]
    if avant:
        parts += ["BEFORE", _date_imap(avant)]
    if recherche:
        mots = " ".join(str(recherche).split())[:200].replace('"', "")
        parts += ["TEXT", f'"{mots}"']
    return " ".join(parts) if parts else "ALL"


def _texte_du_message(m) -> tuple[str, str]:
    """(texte brut, html) du corps."""
    texte, html = "", ""
    try:
        partie = m.get_body(preferencelist=("plain",))
        if partie is not None:
            texte = partie.get_content()
    except Exception:  # noqa: BLE001
        pass
    try:
        partie = m.get_body(preferencelist=("html",))
        if partie is not None:
            html = partie.get_content()
    except Exception:  # noqa: BLE001
        pass
    if not texte and html:
        from mail.lecture import _texte_lisible
        texte = _texte_lisible(html, html=True)
    return texte or "", html or ""


def pieces_du_message(m) -> list[dict]:
    """Les pièces (jointes et en ligne), désignées par le RANG de leur partie."""
    from mail.pieces import extension_du_mime
    pieces = []
    for rang, partie in enumerate(m.walk()):
        if partie.is_multipart():
            continue
        cid = (partie.get("Content-ID") or "").strip().strip("<>")
        disposition = (partie.get("Content-Disposition") or "").lower()
        nom = _decoder(partie.get_filename() or "")
        mime = partie.get_content_type() or ""
        inline = bool(cid) or disposition.startswith("inline")
        if nom or (inline and not mime.startswith("text/")):
            try:
                taille = len(partie.get_payload(decode=True) or b"")
            except Exception:  # noqa: BLE001
                taille = None
            pieces.append({"id": str(rang), "nom": nom or ((cid or "image") + (extension_du_mime(mime) or "")),
                           "taille": taille, "type": mime, "inline": inline, "content_id": cid})
    return pieces


def _fiche(m, uid: str, boite: str, longueur_apercu: int, flags: str = "") -> dict:
    from mail.lecture import _apercu, _memoriser, _qualifier
    expediteur = _decoder(m.get("From"))
    qualite = _qualifier(expediteur)
    date_brute = m.get("Date") or ""
    date_iso = ""
    try:
        d = parsedate_to_datetime(date_brute)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        date_iso = d.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 — un en-tête Date libre
        pass
    texte, _ = _texte_du_message(m)
    return {
        "ref": _memoriser(uid, boite),
        "objet": _decoder(m.get("Subject")) or "(sans objet)",
        "de": expediteur,
        "expediteur_interne": qualite["interne"],
        "expediteur_automatique": qualite["automatique"],
        "a": _decoder(m.get("To"))[:120],
        "date": date_brute,
        "date_iso": date_iso,
        "lu": "\\Seen" in (flags or ""),
        "pieces_jointes": any(not p["inline"] for p in pieces_du_message(m)),
        "apercu": _apercu(texte, longueur_apercu),
    }


def _uids(client, criteres: str) -> list[bytes]:
    statut, donnees = client.uid("search", None, criteres)
    if statut != "OK":
        raise RuntimeError(f"la recherche IMAP a échoué ({statut})")
    return (donnees[0] or b"").split()


def _charger(client, uid: bytes) -> tuple[object, str]:
    statut, donnees = client.uid("fetch", uid, "(FLAGS BODY.PEEK[])")
    if statut != "OK" or not donnees or not isinstance(donnees[0], tuple):
        raise LookupError(f"message {uid.decode()} introuvable")
    entete, brut = donnees[0]
    flags = entete.decode(errors="replace") if isinstance(entete, bytes) else str(entete)
    return email.message_from_bytes(brut, policy=policy.default), flags


def lister(boite: str, dossier: str, limite: int, depuis: Optional[datetime] = None,
           recherche: Optional[str] = None, avant: Optional[datetime] = None,
           longueur_apercu: int = 160) -> tuple[list[dict], Optional[int]]:
    """(fiches des `limite` plus récents, nombre total de correspondances)."""
    client = _connexion()
    try:
        statut, _ = client.select(f'"{dossier}"', readonly=True)
        if statut != "OK":
            raise RuntimeError(f"dossier IMAP « {dossier} » introuvable")
        uids = _uids(client, _criteres(depuis, recherche, avant))
        total = len(uids)
        fiches = []
        for uid in reversed(uids[-max(1, min(int(limite), MAX_FETCH)):]):
            try:
                m, flags = _charger(client, uid)
            except Exception as e:  # noqa: BLE001 — un message illisible ne cache pas les autres
                logger.info("IMAP : message %s non lu (%s)", uid, str(e)[:80])
                continue
            # L'identifiant mémorisé porte le DOSSIER : c'est lui que l'ouverture
            # et les pièces jointes relisent (« INBOX|123 »).
            fiches.append(_fiche(m, f"{dossier}|{uid.decode()}", boite, longueur_apercu, flags))
        return fiches, total
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def ouvrir(boite: str, uid: str, dossier: str = "INBOX") -> dict:
    """UN message en entier : corps texte, HTML, pièces avec leur rang."""
    from mail.lecture import MAX_APERCU, _texte_lisible
    client = _connexion()
    try:
        client.select(f'"{dossier}"', readonly=True)
        m, flags = _charger(client, uid.encode())
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass
    fiche = _fiche(m, f"{dossier}|{uid}", boite, MAX_APERCU, flags)
    texte, html = _texte_du_message(m)
    fiche["corps"] = _texte_lisible(texte)
    fiche["corps_html"] = html
    fiche["pieces_jointes"] = pieces_du_message(m)
    return fiche


def piece(uid: str, rang: str, dossier: str = "INBOX") -> bytes:
    """Les octets de la partie `rang` du message `uid`."""
    client = _connexion()
    try:
        client.select(f'"{dossier}"', readonly=True)
        m, _ = _charger(client, uid.encode())
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass
    for i, partie in enumerate(m.walk()):
        if str(i) == str(rang):
            return partie.get_payload(decode=True) or b""
    raise LookupError(f"pièce {rang} absente du message {uid}")


def envoyer(brut: bytes, expediteur: str, destinataires: list[str]) -> None:
    """Envoie un message MIME déjà construit, par SMTP + STARTTLS."""
    hote = (getattr(settings, "mail_smtp_host", None) or HOTE_SMTP_DEFAUT).strip()
    port = int(getattr(settings, "mail_smtp_port", None) or PORT_SMTP_DEFAUT)
    with smtplib.SMTP(hote, port, timeout=DELAI_S) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.login(boite_unique() or expediteur, (getattr(settings, "mail_imap_password", None) or "").strip())
        s.sendmail(expediteur, [d for d in destinataires if d], brut)


_RE_ADRESSE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
