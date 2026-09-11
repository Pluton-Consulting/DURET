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

import base64
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


def _identifiant(nom: str) -> str:
    """Paramètres (table `cles_api`) d'abord, `.env` ensuite — même priorité que
    les clés de modèles (`llm/cles.py`)."""
    try:
        from llm.cles import valeur
        v = valeur(nom)
    except Exception:  # noqa: BLE001 — sans cache de clés, le .env
        v = getattr(settings, nom, None)
    return str(v or "").strip()


def configure() -> bool:
    """Des identifiants IMAP existent-ils ?"""
    return bool(_identifiant("mail_imap_user") and _identifiant("mail_imap_password"))


def boite_unique() -> Optional[str]:
    """L'adresse de la boîte unique, ou None : c'est elle que tout le monde lit."""
    u = _identifiant("mail_imap_user").lower()
    return u or None


def _mot_de_passe() -> str:
    return _identifiant("mail_imap_password")


# ── LES DOSSIERS DE LA BOÎTE (11/09) ─────────────────────────────────────
# Demande de Noa (Duret) : chaque profil de la boîte partagée lit la boîte de
# réception — le « mail général » — plus les dossiers que l'administrateur lui
# ouvre. Il faut donc savoir LISTER les dossiers, en lire un par son NOM, et
# dire si un dossier est permis. Trois pièges, tous payés ici :
#   * les noms IMAP sont en « UTF-7 modifié » (RFC 3501) : « Comptabilité »
#     s'écrit « Comptabilit&AOk- » sur le fil — on décode pour l'écran et l'on
#     réencode pour ouvrir ;
#   * le dossier des envoyés porte le nom de la LANGUE du compte chez Gmail
#     (« [Gmail]/Messages envoyés » en français) : on le reconnaît à son
#     attribut `\Sent`, pas à son nom, et il se désigne par la clé « envoyes » ;
#   * « Tous les messages » (`\All`) contient TOUT : le proposer ferait d'une
#     case cochée une restriction vide. Ni lui, ni la corbeille, ni les
#     brouillons, ni le spam ne sont proposés.

CLE_RECUS = "INBOX"
CLE_ENVOYES = "envoyes"
_ALIAS_RECUS = {"", "recus", "reçus", "inbox", "reception", "réception",
                "boite de reception", "boîte de réception", "mail general", "mail général"}
_EXCLUS = {"\\all", "\\trash", "\\junk", "\\drafts", "\\flagged", "\\important",
           "\\noselect", "\\nonexistent"}
# Le nom réel du dossier des envoyés, lu sur la boîte (attribut \Sent).
_ENVOYES_DETECTE: Optional[str] = None


def utf7_decoder(nom: str) -> str:
    """« Comptabilit&AOk- » → « Comptabilité » (UTF-7 modifié, RFC 3501 §5.1.3)."""
    sortie, i = [], 0
    while i < len(nom):
        if nom[i] != "&":
            sortie.append(nom[i])
            i += 1
            continue
        fin = nom.find("-", i)
        if fin == -1:
            sortie.append(nom[i:])
            break
        if fin == i + 1:
            sortie.append("&")
        else:
            code = nom[i + 1:fin].replace(",", "/")
            code += "=" * (-len(code) % 4)
            try:
                sortie.append(base64.b64decode(code).decode("utf-16-be"))
            except Exception:  # noqa: BLE001 — un nom mal formé reste lisible tel quel
                sortie.append(nom[i:fin + 1])
        i = fin + 1
    return "".join(sortie)


def utf7_encoder(nom: str) -> str:
    """L'inverse : ce qu'on envoie au serveur pour ouvrir un dossier."""
    sortie, tampon = [], []

    def vider():
        if tampon:
            octets = "".join(tampon).encode("utf-16-be")
            sortie.append("&" + base64.b64encode(octets).decode().rstrip("=").replace("/", ",") + "-")
            tampon.clear()
    for c in nom:
        if 0x20 <= ord(c) <= 0x7E:
            vider()
            sortie.append("&-" if c == "&" else c)
        else:
            tampon.append(c)
    vider()
    return "".join(sortie)


_RE_LIST = re.compile(r'^\((?P<attributs>[^)]*)\)\s+(?:"(?:[^"\\]|\\.)*"|NIL)\s+(?P<nom>.+)$')


def analyser_list(lignes) -> list[tuple[set, str]]:
    """Les réponses de LIST → [(attributs en minuscules, nom décodé)]."""
    sortie = []
    for brut in lignes or []:
        if isinstance(brut, tuple):                 # nom en littéral : {12}\r\nNom
            texte = b"".join(x for x in brut if isinstance(x, bytes)).decode("utf-8", "replace")
            texte = re.sub(r"\{\d+\}", "", texte)
        elif isinstance(brut, bytes):
            texte = brut.decode("utf-8", "replace")
        else:
            continue
        m = _RE_LIST.match(texte.strip())
        if not m:
            continue
        nom = m.group("nom").strip()
        if nom.startswith('"') and nom.endswith('"'):
            nom = nom[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        attributs = {a.lower() for a in m.group("attributs").split()}
        sortie.append((attributs, utf7_decoder(nom)))
    return sortie


def _envoyes_du_serveur(client) -> Optional[str]:
    """Le dossier marqué \\Sent sur CETTE boîte (mémorisé)."""
    global _ENVOYES_DETECTE
    try:
        statut, lignes = client.list()
    except Exception:  # noqa: BLE001
        return _ENVOYES_DETECTE
    if statut == "OK":
        for attributs, nom in analyser_list(lignes):
            if "\\sent" in attributs:
                _ENVOYES_DETECTE = nom
                break
    return _ENVOYES_DETECTE


def cle_dossier(nom: Optional[str]) -> str:
    """Le nom canonique d'un dossier : « INBOX », « envoyes », ou le nom décodé."""
    brut = " ".join(str(nom or "").split())
    bas = brut.lower()
    if bas in _ALIAS_RECUS:
        return CLE_RECUS
    reglage = (getattr(settings, "mail_imap_dossier_envoyes", None) or DOSSIER_ENVOYES_GMAIL)
    if bas.startswith("env") or bas in ("sent", "messages envoyés", "messages envoyes") \
            or bas == reglage.lower() or (_ENVOYES_DETECTE and bas == _ENVOYES_DETECTE.lower()):
        return CLE_ENVOYES
    return brut


def dossier_permis(nom: Optional[str], autorises) -> bool:
    """La boîte de réception l'est toujours ; les autres, s'ils sont ouverts.
    `autorises` à None : aucune restriction."""
    if autorises is None:
        return True
    cle = cle_dossier(nom)
    if cle == CLE_RECUS:
        return True
    return cle.lower() in {str(a).strip().lower() for a in autorises}


def dossier_imap(cle: str) -> str:
    """Le nom du dossier à ouvrir : la réception, les envoyés (tel que la boîte
    le nomme, s'il a été lu), ou le dossier demandé par son nom."""
    canon = cle_dossier(cle)
    if canon == CLE_RECUS:
        return "INBOX"
    if canon == CLE_ENVOYES:
        return _ENVOYES_DETECTE or (getattr(settings, "mail_imap_dossier_envoyes", None)
                                    or DOSSIER_ENVOYES_GMAIL)
    return canon


def _selectionner(client, dossier: str) -> None:
    """Ouvre un dossier en lecture seule — nom réencodé, guillemets échappés.
    Le dossier des envoyés introuvable sous son nom réglé est cherché par son
    attribut \\Sent : c'est le cas de tout compte Gmail qui n'est pas en anglais."""
    def _ouvrir(nom: str) -> bool:
        code = utf7_encoder(nom).replace("\\", "\\\\").replace('"', '\\"')
        statut, _ = client.select(f'"{code}"', readonly=True)
        return statut == "OK"
    if _ouvrir(dossier):
        return
    if cle_dossier(dossier) == CLE_ENVOYES:
        vrai = _envoyes_du_serveur(client)
        if vrai and vrai != dossier and _ouvrir(vrai):
            return
    raise RuntimeError(f"dossier IMAP « {dossier} » introuvable")


def lister_dossiers() -> list[tuple[set, str]]:
    """Tous les dossiers de la boîte, avec leurs attributs."""
    client = _connexion()
    try:
        statut, lignes = client.list()
        if statut != "OK":
            raise RuntimeError("la boîte ne rend pas la liste de ses dossiers")
        dossiers = analyser_list(lignes)
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass
    global _ENVOYES_DETECTE
    for attributs, nom in dossiers:
        if "\\sent" in attributs:
            _ENVOYES_DETECTE = nom
    return dossiers


def dossiers_proposables(dossiers: Optional[list[tuple[set, str]]] = None) -> list[dict]:
    """Ce qu'un administrateur peut ouvrir à un profil : les envoyés (clé
    « envoyes ») et les dossiers de l'utilisateur ; ni la réception (toujours
    ouverte) ni les dossiers systèmes qui montreraient tout."""
    global _ENVOYES_DETECTE
    dossiers = lister_dossiers() if dossiers is None else dossiers
    envoyes, autres = [], []
    for attributs, nom in dossiers:
        if nom.upper() == "INBOX":
            continue
        if "\\sent" in attributs:
            _ENVOYES_DETECTE = nom        # son vrai nom, pour l'ouvrir ensuite
            envoyes = [{"nom": CLE_ENVOYES, "libelle": "Messages envoyés"}]
            continue
        if attributs & _EXCLUS:
            continue
        libelle = nom.split("/", 1)[1] if nom.startswith("[Gmail]/") else nom
        autres.append({"nom": nom, "libelle": libelle})
    return envoyes + sorted(autres, key=lambda d: d["libelle"].lower())


def _connexion() -> imaplib.IMAP4_SSL:
    hote = (getattr(settings, "mail_imap_host", None) or HOTE_IMAP_DEFAUT).strip()
    client = imaplib.IMAP4_SSL(hote, 993, ssl_context=ssl.create_default_context(), timeout=DELAI_S)
    client.login(boite_unique() or "", _mot_de_passe())
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
        _selectionner(client, dossier)
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
        _selectionner(client, dossier)
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


def parcourir(dossier: str, maximum: int) -> list[tuple[str, object]]:
    """Les `maximum` messages les plus récents d'un dossier, PARSÉS, avec leur
    UID — pour l'ingestion, qui a besoin du corps entier de chacun."""
    client = _connexion()
    try:
        _selectionner(client, dossier)
        uids = _uids(client, "ALL")
        messages = []
        for uid in reversed(uids[-max(1, int(maximum)):]):
            try:
                m, _ = _charger(client, uid)
                messages.append((uid.decode(), m))
            except Exception as e:  # noqa: BLE001
                logger.info("IMAP : message %s non lu (%s)", uid, str(e)[:80])
        return messages
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def tester() -> dict:
    """Une connexion IMAP puis SMTP, pour le bouton « Tester » de l'écran.
    Rend {ok, imap, smtp, boite, erreur} — jamais le mot de passe."""
    boite = boite_unique()
    if not boite or not _mot_de_passe():
        return {"ok": False, "boite": boite, "erreur": "adresse ou mot de passe d'application absent"}
    resultat = {"ok": False, "boite": boite, "imap": False, "smtp": False, "erreur": ""}
    try:
        client = _connexion()
        try:
            statut, donnees = client.select('"INBOX"', readonly=True)
            resultat["imap"] = statut == "OK"
            try:
                resultat["messages"] = int((donnees or [b"0"])[0] or 0)
            except Exception:  # noqa: BLE001
                pass
        finally:
            client.logout()
    except Exception as e:  # noqa: BLE001
        resultat["erreur"] = f"IMAP : {str(e)[:160]}"
        return resultat
    try:
        hote = (getattr(settings, "mail_smtp_host", None) or HOTE_SMTP_DEFAUT).strip()
        port = int(getattr(settings, "mail_smtp_port", None) or PORT_SMTP_DEFAUT)
        with smtplib.SMTP(hote, port, timeout=DELAI_S) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.login(boite, _mot_de_passe())
        resultat["smtp"] = True
    except Exception as e:  # noqa: BLE001
        resultat["erreur"] = f"SMTP : {str(e)[:160]}"
        return resultat
    resultat["ok"] = True
    return resultat


def piece(uid: str, rang: str, dossier: str = "INBOX") -> bytes:
    """Les octets de la partie `rang` du message `uid`."""
    client = _connexion()
    try:
        _selectionner(client, dossier)
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
        s.login(boite_unique() or expediteur, _mot_de_passe())
        s.sendmail(expediteur, [d for d in destinataires if d], brut)


_RE_ADRESSE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
