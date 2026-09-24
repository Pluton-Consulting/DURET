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
from contextlib import contextmanager
from contextvars import ContextVar
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


# ── LES BOÎTES PRIVÉES DE LA DIRECTION (23/09, `mail/boites_privees.py`) ──
# Tout ce module se connectait à LA boîte unique. Une connexion choisit
# désormais ses identifiants selon la boîte visée : l'adresse passée en
# paramètre quand l'appel la connaît (lister, ouvrir, envoyer), sinon celle
# que `mail.authorization.verifier_acces` vient d'autoriser pour CE geste
# (pièce jointe, dépôt d'un brouillon, indicateurs, recherche hors réception).
# Sans boîte privée en jeu, rien ne change : les identifiants de la boîte
# unique, comme avant. `asyncio.to_thread` copie le contexte : le thread voit
# la boîte du geste qui l'a lancé.
_BOITE_DU_GESTE: ContextVar[Optional[str]] = ContextVar("boite_imap_du_geste", default=None)


def boite_du_geste() -> Optional[str]:
    return _BOITE_DU_GESTE.get()


def poser_boite_du_geste(boite: Optional[str]) -> None:
    """Posée par `verifier_acces` : la boîte privée autorisée, ou None."""
    _BOITE_DU_GESTE.set((boite or "").strip().lower() or None)


@contextmanager
def geste_neutre():
    """Le temps d'un geste, aucune boîte privée héritée d'un geste précédent
    (`skills/executor.execute_skill`)."""
    jeton = _BOITE_DU_GESTE.set(None)
    try:
        yield
    finally:
        _BOITE_DU_GESTE.reset(jeton)


def _compte(boite: Optional[str] = None) -> dict:
    """Les identifiants à utiliser : ceux d'une boîte privée si c'est elle qu'on
    vise, sinon ceux de la boîte unique. Une boîte privée RETIRÉE entre-temps
    ne retombe PAS sur la boîte unique (on lirait la mauvaise boîte en croyant
    lire la bonne) : l'appel échoue en le disant."""
    cible = (boite or _BOITE_DU_GESTE.get() or "").strip().lower()
    unique = boite_unique() or ""
    if cible and cible != unique:
        try:
            from mail import boites_privees
            prive = boites_privees.identifiants(cible)
        except Exception:  # noqa: BLE001
            prive = None
        if prive:
            return {"login": prive["adresse"], "mot_de_passe": prive["mot_de_passe"],
                    "hote_imap": prive["hote_imap"], "hote_smtp": prive["hote_smtp"],
                    "port_smtp": PORT_SMTP_DEFAUT}
        if _BOITE_DU_GESTE.get() == cible:
            raise RuntimeError(f"la boîte {cible} n'est plus configurée")
    return {"login": unique, "mot_de_passe": _mot_de_passe(),
            "hote_imap": (getattr(settings, "mail_imap_host", None) or HOTE_IMAP_DEFAUT).strip(),
            "hote_smtp": (getattr(settings, "mail_smtp_host", None) or HOTE_SMTP_DEFAUT).strip(),
            "port_smtp": int(getattr(settings, "mail_smtp_port", None) or PORT_SMTP_DEFAUT)}


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


def dossier_de_tous_les_messages() -> Optional[str]:
    """Le dossier qui porte TOUS les messages (attribut \\All : « [Gmail]/Tous les
    messages »), ou None. Sert à une RECHERCHE qui ne trouve rien en réception :
    un filtre Gmail range des mails dans un libellé en sautant la réception."""
    try:
        for attributs, nom in lister_dossiers():
            if any(str(x).lower() == "\\all" for x in attributs):
                return nom
    except Exception:  # noqa: BLE001
        return None
    return None


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


def _connexion(boite: Optional[str] = None) -> imaplib.IMAP4_SSL:
    compte = _compte(boite)
    client = imaplib.IMAP4_SSL(compte["hote_imap"], 993, ssl_context=ssl.create_default_context(),
                               timeout=DELAI_S)
    client.login(compte["login"] or "", compte["mot_de_passe"])
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


_DANS_L_OBJET = re.compile(r"^\s*(?:objet|sujet|subject)\s*:\s*", re.I)


def _criteres(depuis: Optional[datetime], recherche: Optional[str], avant: Optional[datetime],
              non_lus: bool = False):
    """Les critères IMAP SEARCH : (critères, texte cherché ou None).

    `recherche` porte sur objet ET corps (TEXT) ; préfixée « objet: », elle ne
    porte que sur l'OBJET (SUBJECT) — 17/09, Duret : « un mail avec maxime dans
    l'objet » rendait 5 279 messages, tous ceux dont le CORPS dit « Salut
    Maxime ». Le texte cherché voyage À PART : avec un accent (« mémoire ») il
    part en littéral UTF-8, qu'une chaîne de commande ASCII ne peut pas porter
    (« 'ascii' codec can't encode character '\\xe9' » — la boîte devenait
    inconsultable). IMAP ne connaît que la journée pour les dates, comme Gmail."""
    parts = []
    # LES NON LUS SE FILTRENT CÔTÉ SERVEUR (24/09) : « affiche mes mails non lus »
    # relisait les 25 plus récents et n'en gardait que les non lus — 36 non lus, 4
    # montrés. UNSEEN rend exactement ceux-là, tous, quel que soit leur nombre.
    if non_lus:
        parts.append("UNSEEN")
    if depuis:
        parts += ["SINCE", _date_imap(depuis)]
    if avant:
        parts += ["BEFORE", _date_imap(avant)]
    mots = None
    if recherche and str(recherche).strip():
        brut = str(recherche)
        champ = "SUBJECT" if _DANS_L_OBJET.match(brut) else "TEXT"
        mots = " ".join(_DANS_L_OBJET.sub("", brut).split())[:200].replace('"', "").strip()
        if mots:
            parts.append(champ)          # le texte suit, posé par `_uids`
        else:
            mots = None
    return (" ".join(parts) if parts else "ALL"), mots


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


def _uids(client, criteres) -> list[bytes]:
    criteres, mots = criteres if isinstance(criteres, tuple) else (criteres, None)
    if mots is None:
        statut, donnees = client.uid("search", None, criteres)
    elif mots.isascii():
        statut, donnees = client.uid("search", None, f'{criteres} "{mots}"')
    else:
        # Un texte accentué part en LITTÉRAL UTF-8 (RFC 3501) : imaplib l'envoie
        # après la commande, qui doit donc FINIR par le champ cherché.
        client.literal = mots.encode("utf-8")
        statut, donnees = client.uid("search", "CHARSET", "UTF-8", criteres)
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


def _charger_apercus(client, uids):
    """Un aller-retour pour le lot, sans télécharger ses grosses pièces jointes.

    Le préfixe MIME suffit à un aperçu, jamais à certifier une lecture intégrale.
    Ouvrir un message conserve le chemin complet `_charger` et BODY.PEEK.
    """
    if not uids:return {}
    statut, donnees = client.uid('fetch', b','.join(uids), '(UID FLAGS RFC822.SIZE BODY.PEEK[]<0.65536>)')
    if statut != 'OK':raise RuntimeError('Lecture des aperçus IMAP impossible.')
    resultats={}
    for entree in donnees or []:
        if not isinstance(entree,tuple) or len(entree)!=2:continue
        entete,brut=entree
        if not isinstance(brut,bytes):continue
        entete=entete.decode(errors='replace') if isinstance(entete,bytes) else str(entete)
        uid=re.search(r'\bUID\s+(\d+)\b',entete,re.I)
        taille=re.search(r'\bRFC822.SIZE\s+(\d+)\b',entete,re.I)
        if uid:
            resultats[uid[1].encode()] = (email.message_from_bytes(brut,policy=policy.default),entete,
                int(taille[1])>len(brut) if taille else len(brut)>=65536)
    return resultats


def lister(boite: str, dossier: str, limite: int, depuis: Optional[datetime] = None,
           recherche: Optional[str] = None, avant: Optional[datetime] = None,
           longueur_apercu: int = 160, curseur: Optional[str] = None,
           extra: Optional[dict] = None, non_lus: bool = False) -> tuple[list[dict], Optional[int]]:
    """(fiches des `limite` plus récents, nombre total de correspondances).

    `extra`, s'il est donné, reçoit `non_lus` : le nombre EXACT de messages non lus du
    dossier entier (SEARCH UNSEEN, côté serveur). 18/09 : « combien de mails non lus
    j'ai, exactement ? » répondait « 13 parmi les 15 plus récents » — le compte était
    tiré des fiches, le serveur le sait en une commande."""
    client = _connexion(boite)
    try:
        _selectionner(client, dossier)
        if extra is not None:
            try:
                statut, brut = client.uid("SEARCH", None, "UNSEEN")
                extra["non_lus"] = len((brut[0] or b"").split()) if statut == "OK" else None
            except Exception as e:  # noqa: BLE001 — un compte absent n'empêche pas la lecture
                logger.info("IMAP : compte des non lus indisponible (%s)", str(e)[:80])
        uids = _uids(client, _criteres(depuis, recherche, avant, non_lus))
        _, validite_brute=client.response('UIDVALIDITY')
        validite=(validite_brute[0] or b'').decode() if validite_brute else ''
        if curseur:
            match=re.fullmatch(r'imap:(\d+):(\d+)',str(curseur))
            if not match or match[1]!=validite:
                raise ValueError('La pagination de cette boîte a expiré ; reprends la première page.')
            uids=[u for u in uids if int(u)<int(match[2])]
        total = len(uids)
        fiches = []
        selection=list(reversed(uids[-max(1, min(int(limite), MAX_FETCH)):]))
        apercus=_charger_apercus(client,selection)
        for uid in selection:
            try:
                m, flags, coupe = apercus[uid]
            except Exception as e:  # noqa: BLE001 — un message illisible ne cache pas les autres
                logger.info("IMAP : message %s non lu (%s)", uid, str(e)[:80])
                continue
            # L'identifiant mémorisé porte le DOSSIER : c'est lui que l'ouverture
            # et les pièces jointes relisent (« INBOX|123 »).
            fiche=_fiche(m, f"{dossier}|{uid.decode()}", boite, longueur_apercu, flags)
            fiche['lecture_integrale']=not coupe
            if coupe and not fiche['pieces_jointes']:fiche['pieces_jointes']=None
            if validite.isdigit():fiche['curseur_suivant']=f'imap:{validite}:{uid.decode()}'
            fiches.append(fiche)
        return fiches, total
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def _code_dossier(nom: str) -> str:
    return '"' + utf7_encoder(nom).replace("\\", "\\\\").replace('"', '\\"') + '"'


def deplacer(boite: str, identifiants: list[str], dossier_cible: str, creer: bool = True) -> dict:
    """DÉPLACE des messages (« INBOX|123 ») dans un dossier de la boîte (24/09).

    Le classement que Damien demandait (« associe chaque mail à un dossier, puis
    classe-les ») n'avait aucun geste : rien ne savait ÉCRIRE dans la boîte. Le
    dossier cible est créé s'il manque (`creer`). Gmail et les serveurs modernes
    savent MOVE (RFC 6851) ; sinon COPY, puis le drapeau Deleted et EXPUNGE sur l'origine.
    Chaque message part ou échoue SÉPARÉMENT : un identifiant périmé n'arrête
    pas les autres, et le résultat dit lesquels."""
    client = _connexion(boite)
    deplaces, echecs, cree = [], [], False
    try:
        statut, lignes = client.list()
        existants = {nom for _, nom in analyser_list(lignes)} if statut == "OK" else set()
        if dossier_cible not in existants:
            if not creer:
                raise RuntimeError(f"dossier « {dossier_cible} » introuvable")
            statut, _ = client.create(_code_dossier(dossier_cible))
            if statut != "OK":
                raise RuntimeError(f"le dossier « {dossier_cible} » n'a pas pu être créé")
            cree = True
        cible = _code_dossier(dossier_cible)
        peut_move = "MOVE" in {str(c).upper() for c in (client.capabilities or ())}
        par_origine: dict[str, list[tuple[str, str]]] = {}
        for ident in identifiants:
            src, _, uid = str(ident).partition("|")
            if not uid:
                src, uid = "INBOX", src
            par_origine.setdefault(src, []).append((ident, uid))
        for src, lot in par_origine.items():
            statut, _ = client.select(_code_dossier(src))     # en écriture, cette fois
            if statut != "OK":
                echecs += [(ident, f"dossier d'origine « {src} » introuvable") for ident, _ in lot]
                continue
            for ident, uid in lot:
                try:
                    if peut_move:
                        statut, _ = client.uid("MOVE", uid, cible)
                    else:
                        statut, _ = client.uid("COPY", uid, cible)
                        if statut == "OK":
                            statut, _ = client.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
                    if statut != "OK":
                        raise RuntimeError("refusé par le serveur")
                    deplaces.append(ident)
                except Exception as e:  # noqa: BLE001 — un message ne bloque pas les autres
                    echecs.append((ident, str(e)[:120]))
            if not peut_move:
                try:
                    client.expunge()
                except Exception:  # noqa: BLE001
                    pass
        return {"deplaces": deplaces, "echecs": echecs, "dossier_cree": cree}
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def ouvrir(boite: str, uid: str, dossier: str = "INBOX") -> dict:
    """UN message en entier : corps texte, HTML, pièces avec leur rang."""
    from mail.lecture import MAX_APERCU, _texte_lisible
    client = _connexion(boite)
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


def tester(boite: Optional[str] = None) -> dict:
    """Une connexion IMAP puis SMTP, pour le bouton « Tester » de l'écran.
    Rend {ok, imap, smtp, boite, erreur} — jamais le mot de passe. Sans `boite` :
    la boîte unique ; avec : cette boîte privée (23/09)."""
    compte = _compte(boite) if boite else None
    if boite and (not compte or compte["login"] != boite.strip().lower()):
        return {"ok": False, "boite": boite, "erreur": "boîte privée non configurée"}
    boite = compte["login"] if compte else boite_unique()
    mdp = compte["mot_de_passe"] if compte else _mot_de_passe()
    if not boite or not mdp:
        return {"ok": False, "boite": boite, "erreur": "adresse ou mot de passe d'application absent"}
    resultat = {"ok": False, "boite": boite, "imap": False, "smtp": False, "erreur": ""}
    try:
        client = _connexion(boite)
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
        compte_smtp = _compte(boite)
        with smtplib.SMTP(compte_smtp["hote_smtp"], compte_smtp["port_smtp"], timeout=DELAI_S) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.login(boite, mdp)
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


def deposer(brut: bytes, avec_recu: bool = False):
    """Pose un message MIME dans le dossier Brouillons (APPEND, drapeau \\Draft).

    Rend le nom du dossier. Le dossier se reconnaît à son attribut `\\Drafts`
    (Gmail en français : « [Gmail]/Brouillons »), pas à un nom supposé.
    """
    import imaplib as _imaplib
    from mail.expedition import _dossier_brouillons_imap
    client = _connexion()
    try:
        _type, listes = client.list()
        dossier = _dossier_brouillons_imap(listes or [])
        statut, reponse = client.append(f'"{dossier}"', "(\\Draft)",
                                        _imaplib.Time2Internaldate(datetime.now(timezone.utc)), brut)
        if statut != "OK":
            raise RuntimeError(f"le serveur a refusé le dépôt dans « {dossier} » : {reponse}")
        if avec_recu:
            preuve = b" ".join(v for v in reponse or [] if isinstance(v, bytes))
            match = re.search(rb"APPENDUID\s+(\d+)\s+(\d+)", preuve, re.I)
            return {"dossier": dossier, "id_brouillon": dossier + "|" + match.group(2).decode() if match else None,
                    "uidvalidity": match.group(1).decode() if match else None}
        return dossier
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def envoyer(brut: bytes, expediteur: str, destinataires: list[str]) -> None:
    """Envoie un message MIME déjà construit, par SMTP + STARTTLS — avec les
    identifiants de l'expéditeur s'il est une boîte privée (23/09)."""
    compte = _compte(expediteur)
    with smtplib.SMTP(compte["hote_smtp"], compte["port_smtp"], timeout=DELAI_S) as s:
        s.ehlo()
        s.starttls(context=ssl.create_default_context())
        s.login(compte["login"] or expediteur, compte["mot_de_passe"])
        s.sendmail(expediteur, [d for d in destinataires if d], brut)


_RE_ADRESSE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
