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

LE CORPS ENTIER (31/08/2026). Relevé par Noa : « il n'arrive pas à lire les
corps de mails complets, il lit que les aperçus, qui sont donc coupés ». Deux
causes, qui s'additionnaient :
  * la lecture Outlook ne demandait que `bodyPreview` à Graph — que Microsoft
    plafonne à ~255 caractères, quoi qu'on lui demande. Le corps (`body`)
    n'était JAMAIS lu. Il l'est désormais, demandé en TEXTE (en-tête `Prefer`)
    pour ne pas transporter du HTML dont on ne garde que les mots ;
  * un résultat de skill est coupé à 4 000 caractères avant d'atteindre le
    modèle (`agents.agent1.PLAFOND_RESULTAT`) : dix extraits de 800 caractères
    n'y tenaient pas, le JSON était tranché au milieu d'une liste. Les skills
    mail sont passés en résultats « généreux » (12 000), et la LISTE partage
    un budget : plus il y a de messages, plus l'extrait de chacun est court
    (`_budget_apercu`). Une liste est une table des matières, pas une lecture.
La lecture elle-même est un geste à part : `lire_message` OUVRE UN message —
corps complet jusqu'à `MAX_CORPS`, pièces jointes nommées — à partir de la
`ref` courte rendue dans chaque liste (un identifiant Graph fait 150
caractères ; vingt-cinq en mangeraient le tiers du budget), ou à défaut de son
objet.
"""
from __future__ import annotations

import hashlib
import html as _html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import settings
from mail.collecte import fournisseur

logger = logging.getLogger("symbiose.mail.lecture")

DOSSIERS = {
    "outlook": {"recus": "inbox", "envoyes": "sentitems"},
    "gmail": {"recus": "INBOX", "envoyes": "SENT"},
}

MAX_MESSAGES = 25
MAX_APERCU = 800
# Un message OUVERT : le corps entier, jusqu'ici — et la coupure est DITE. Le
# plafond suit celui des résultats généreux d'agent1 (12 000) : au-delà, la
# coupure se ferait plus loin, et en silence.
MAX_CORPS = 10_000
# La LISTE a un budget global, partagé entre ses messages. Vingt-cinq extraits
# de 800 caractères font 20 000 : rien de tout cela n'atteignait le modèle.
BUDGET_LISTE = 8_500
# Ce qu'un message coûte HORS extrait (objet, adresses, date, ref, clés JSON).
ENTETE_MESSAGE = 260
# En dessous, un extrait ne dit plus de quoi parle le message.
MIN_APERCU = 160
# Le compte exact d'une période se fait en parcourant des identifiants (pas les
# messages) : bon marché, mais pas gratuit. Au-delà, on dit « plus de N ».
MAX_COMPTE = 5000

_RE_BALISES = re.compile(r"<[^>]+>")
# Ce qui, en HTML, sépare des paragraphes : un corps lisible garde ses lignes.
_RE_SAUTS_HTML = re.compile(r"</?(?:p|div|br|tr|li|h[1-6]|blockquote|table)\b[^>]*>", re.I)
_RE_INVISIBLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
# La mise en forme EN LIGNE (gras, lien) disparaît sans laisser d'espace :
# « <b>accepté</b>. » doit rendre « accepté. », pas « accepté . ».
_RE_EN_LIGNE = re.compile(r"</?(?:b|i|u|em|strong|span|a|font|small|sup|sub)\b[^>]*>", re.I)
_RE_COMMENTAIRE = re.compile(r"<!--.*?-->", re.S)
_RE_HTML = re.compile(r"<(?:p|div|br|html|body|span|table|a|b|i|font)\b", re.I)


def _texte_lisible(contenu: str, html: Optional[bool] = None) -> str:
    """Le texte d'un corps, HTML ou brut : paragraphes conservés, balises,
    scripts et entités retirés, espaces repliés ligne par ligne.

    `html=None` : on regarde le contenu. Graph dit le type (`contentType`),
    Gmail ne le dit qu'au niveau des parties MIME — et un texte brut qui cite
    un `<adresse@x.fr>` ne doit pas être pris pour du HTML.
    """
    texte = contenu or ""
    if html is None:
        html = bool(_RE_HTML.search(texte))
    if html:
        texte = _RE_COMMENTAIRE.sub(" ", _RE_INVISIBLE.sub(" ", texte))
        texte = _RE_SAUTS_HTML.sub("\n", texte)
        texte = _RE_EN_LIGNE.sub("", texte)
        texte = _RE_BALISES.sub(" ", texte)
    texte = _html.unescape(texte).replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    lignes = [" ".join(ligne.split()) for ligne in texte.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lignes)).strip()


def _apercu(texte: str, longueur: int = MAX_APERCU) -> str:
    """Extrait lisible et borné : on résume, on ne rapatrie pas la boîte."""
    return " ".join(_texte_lisible(texte).split())[:max(0, int(longueur))]


def _budget_apercu(nombre: int) -> int:
    """La longueur d'extrait qui laisse la liste ENTIÈRE atteindre le modèle.

    Un seul message : 800 caractères. Vingt-cinq : 160. Entre les deux, le
    budget se partage. Perdre la moitié des messages parce que les premiers
    étaient longs, c'est ce qui se passait avant.
    """
    if nombre <= 0:
        return MAX_APERCU
    return max(MIN_APERCU, min(MAX_APERCU, (BUDGET_LISTE - nombre * ENTETE_MESSAGE) // nombre))


# ── La référence courte d'un message ────────────────────────────────────────
# Un identifiant Graph fait ~150 caractères, opaque, que le modèle recopie
# mal. La liste rend une `ref` de 16 hexadécimaux (empreinte de l'identifiant),
# que `lire_message` sait résoudre tant que le processus vit ; après un
# redémarrage, l'objet du message prend le relais. Liée à la BOÎTE : une ref
# obtenue sur une boîte n'ouvre rien dans une autre.
_REFS: dict[str, tuple[str, str]] = {}
_MAX_REFS = 5000


def _ref(identifiant: str) -> str:
    return hashlib.sha256((identifiant or "").encode("utf-8")).hexdigest()[:16]


def _memoriser(identifiant: str, boite: str) -> str:
    ref = _ref(identifiant)
    if len(_REFS) >= _MAX_REFS:
        for ancien in list(_REFS)[: _MAX_REFS // 10]:
            _REFS.pop(ancien, None)
    _REFS[ref] = ((boite or "").lower(), identifiant)
    return ref


def _resoudre(ref: str, boite: str) -> Optional[str]:
    """La ref → l'identifiant du fournisseur, si elle est connue POUR CETTE
    boîte. Un identifiant brut (long) passe tel quel : le modèle a pu le
    recopier d'un résultat, il n'y a pas de raison de le lui refuser."""
    ref = (ref or "").strip()
    if not ref:
        return None
    connu = _REFS.get(ref)
    if connu and connu[0] == (boite or "").lower():
        return connu[1]
    if len(ref) > 24:
        return ref
    return None


def _choisir(candidats: list[dict], objet: Optional[str], de: Optional[str]) -> Optional[dict]:
    """Parmi les résultats d'une recherche, le message qui correspond le
    mieux à l'objet (et à l'expéditeur) demandés — fonction PURE."""
    if not candidats:
        return None

    def _plat(s: str) -> str:
        return " ".join(re.sub(r"^\s*(?:re|rép|rep|tr|fwd?)\s*:\s*", "", str(s or ""), flags=re.I)
                        .lower().split())

    voulu, qui = _plat(objet), (de or "").strip().lower()
    meilleurs = []
    for c in candidats:
        score = 0
        sujet = _plat(c.get("objet"))
        if voulu and (voulu == sujet or voulu in sujet or sujet in voulu):
            score += 2
        if qui and qui in str(c.get("de") or "").lower():
            score += 1
        meilleurs.append((score, c))
    meilleurs.sort(key=lambda x: -x[0])
    return meilleurs[0][1]


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


def _kql_echapper(terme: str) -> str:
    """Les guillemets fermeraient la chaîne `$search` : ils deviennent des espaces."""
    return " ".join(str(terme or "").replace('"', " ").split())


# Le corps est demandé EN PLUS de l'aperçu : `bodyPreview` est plafonné par
# Microsoft à ~255 caractères, quoi qu'on lui demande. Et il est demandé en
# TEXTE (en-tête Prefer) : Graph rend sinon le HTML, dont on ne garde que les
# mots — autant ne pas le transporter.
SELECT_OUTLOOK = ("id,subject,from,toRecipients,receivedDateTime,bodyPreview,body,"
                  "isRead,hasAttachments")
PREFER_OUTLOOK_TEXTE = 'outlook.body-content-type="text"'


def _params_outlook(limite: int, depuis: Optional[datetime], recherche: Optional[str] = None,
                    avant: Optional[datetime] = None) -> dict:
    """Les paramètres OData d'une lecture Outlook — fonction PURE, testée au banc.

    Deux régimes que Graph ne laisse pas mélanger :
      * SANS recherche : `$filter` sur la date de réception, `$orderby` du plus
        récent au plus ancien, `$count=true` pour le TOTAL exact ;
      * AVEC recherche : `$search` en KQL — Graph refuse alors `$filter`,
        `$orderby` et `$count`. Les bornes de date passent DANS la requête
        (`received>=…`, `received<…`), l'ordre est celui de la pertinence et le
        total n'est pas connu (le résultat le dit).
    `avant` : la borne haute, exclusive — c'est elle qui permet de remonter le
    temps page par page : « les 25 précédant le plus ancien affiché ».
    """
    select = SELECT_OUTLOOK
    if recherche and recherche.strip():
        kql = [_kql_echapper(recherche)]
        if depuis:
            kql.append(f"received>={depuis.strftime('%Y-%m-%d')}")
        if avant:
            kql.append(f"received<{avant.strftime('%Y-%m-%d')}")
        return {"$top": limite, "$select": select, "$search": '"' + " AND ".join(kql) + '"'}
    params = {"$top": limite, "$orderby": "receivedDateTime desc", "$count": "true",
              "$select": select}
    clauses = []
    if depuis:
        clauses.append(f"receivedDateTime ge {depuis.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if avant:
        clauses.append(f"receivedDateTime lt {avant.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if clauses:
        params["$filter"] = " and ".join(clauses)
    return params


def _requete_gmail(depuis: Optional[datetime], recherche: Optional[str] = None,
                   avant: Optional[datetime] = None) -> Optional[str]:
    """La requête Gmail (`q`) — fonction PURE. Gmail cherche dans objet et corps
    par défaut ; `after:`/`before:` prennent une date à la journée, cohérente
    avec le départ à minuit de `depuis_quand`."""
    parts = []
    if recherche and recherche.strip():
        parts.append(" ".join(recherche.split()))
    if depuis:
        parts.append(f"after:{depuis.strftime('%Y/%m/%d')}")
    if avant:
        parts.append(f"before:{avant.strftime('%Y/%m/%d')}")
    return " ".join(parts) or None


def _corps_outlook(m: dict) -> str:
    """Le corps d'un message Graph, lisible : `body` d'abord (entier),
    `bodyPreview` seulement s'il manque — c'est lui qui est coupé."""
    corps = m.get("body") or {}
    contenu = corps.get("content") or ""
    if contenu.strip():
        return _texte_lisible(contenu, html=(corps.get("contentType") or "").lower() == "html")
    return _texte_lisible(m.get("bodyPreview") or "")


def _fiche_outlook(m: dict, boite: str, longueur_apercu: int) -> dict:
    expediteur = ((m.get("from") or {}).get("emailAddress") or {}).get("address", "")
    destinataires = [((d.get("emailAddress") or {}).get("address") or "")
                     for d in (m.get("toRecipients") or [])]
    qualite = _qualifier(expediteur)
    return {
        "ref": _memoriser(m.get("id") or "", boite),
        "objet": m.get("subject") or "(sans objet)",
        "de": expediteur,
        "expediteur_interne": qualite["interne"],
        "expediteur_automatique": qualite["automatique"],
        "a": ", ".join(filter(None, destinataires))[:120],
        "date": m.get("receivedDateTime") or "",
        "date_iso": (m.get("receivedDateTime") or "")[:10],
        "lu": bool(m.get("isRead")),
        "pieces_jointes": bool(m.get("hasAttachments")),
        "apercu": _apercu(_corps_outlook(m), longueur_apercu),
    }


def _longueur_apercu(nombre: int, apercu=None) -> int:
    """La longueur d'extrait EFFECTIVE : celle que l'appelant demande (borné),
    sinon le budget partagé. `check_mails` rend des fiches plus légères que
    `lire_mails` et sait ce qu'il peut se permettre."""
    try:
        voulu = int(apercu) if apercu is not None else 0
    except (TypeError, ValueError):
        voulu = 0
    if voulu > 0:
        return max(MIN_APERCU, min(MAX_APERCU, voulu))
    return _budget_apercu(nombre)


async def _lire_outlook(boite: str, dossier: str, limite: int,
                        depuis: Optional[datetime], recherche: Optional[str] = None,
                        avant: Optional[datetime] = None,
                        apercu=None) -> tuple[list[dict], Optional[int]]:
    import httpx
    from ingestion.connectors.outlook import _jeton

    jeton = await _jeton()
    # `$count=true` rend le TOTAL de ce que le filtre retient, indépendamment de
    # `$top` : c'est ce qui permet de dire « 84 messages cette semaine » en ne
    # rapatriant que les 25 premiers. Il exige l'en-tête ConsistencyLevel.
    url = f"https://graph.microsoft.com/v1.0/users/{boite}/mailFolders/{dossier}/messages"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, params=_params_outlook(limite, depuis, recherche, avant),
                             headers={"Authorization": f"Bearer {jeton}",
                                      "ConsistencyLevel": "eventual",
                                      "Prefer": PREFER_OUTLOOK_TEXTE})
        r.raise_for_status()
        corps = r.json()
        messages = corps.get("value", [])
        total = corps.get("@odata.count")

    longueur = _longueur_apercu(len(messages), apercu)
    resultats = [_fiche_outlook(m, boite, longueur) for m in messages]
    return resultats, (int(total) if total is not None else None)


async def _ouvrir_outlook(boite: str, identifiant: str) -> dict:
    """UN message, en entier — et le nom de ses pièces jointes."""
    import httpx
    from ingestion.connectors.outlook import _jeton

    jeton = await _jeton()
    entetes = {"Authorization": f"Bearer {jeton}", "Prefer": PREFER_OUTLOOK_TEXTE}
    base = f"https://graph.microsoft.com/v1.0/users/{boite}/messages/{identifiant}"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(base, params={"$select": SELECT_OUTLOOK}, headers=entetes)
        r.raise_for_status()
        m = r.json()
        pieces = []
        if m.get("hasAttachments"):
            try:
                ra = await client.get(base + "/attachments",
                                      params={"$select": "name,size,contentType"}, headers=entetes)
                ra.raise_for_status()
                pieces = [{"nom": p.get("name") or "(sans nom)", "taille": p.get("size"),
                           "type": p.get("contentType")} for p in ra.json().get("value", [])]
            except Exception as e:  # noqa: BLE001 — les pièces jointes sont un complément
                logger.info("Pièces jointes non listées pour %s : %s", boite, e)
    fiche = _fiche_outlook(m, boite, MAX_APERCU)
    fiche["corps"] = _corps_outlook(m)
    fiche["pieces_jointes"] = pieces
    return fiche


def _pieces_gmail(charge: dict) -> list[dict]:
    pieces = []

    def _parcourir(partie: dict):
        if partie.get("filename"):
            pieces.append({"nom": partie["filename"], "taille": (partie.get("body") or {}).get("size"),
                           "type": partie.get("mimeType")})
        for sous in partie.get("parts") or []:
            _parcourir(sous)

    _parcourir(charge or {})
    return pieces


def _fiche_gmail(m: dict, boite: str, longueur_apercu: int, _entete, _texte_du_message) -> dict:
    expediteur = _entete(m, "From")
    qualite = _qualifier(expediteur)
    charge = m.get("payload") or {}
    return {
        "ref": _memoriser(m.get("id") or "", boite),
        "objet": _entete(m, "Subject") or "(sans objet)",
        "de": expediteur,
        "expediteur_interne": qualite["interne"],
        "expediteur_automatique": qualite["automatique"],
        "a": _entete(m, "To")[:120],
        "date": _entete(m, "Date"),
        # `internalDate` (ms) : la seule date que Gmail garantit lisible —
        # l'en-tête Date est libre. C'est elle que `avant` réutilise.
        "date_iso": (datetime.fromtimestamp(int(m["internalDate"]) / 1000, tz=timezone.utc)
                     .strftime("%Y-%m-%d") if m.get("internalDate") else ""),
        "lu": "UNREAD" not in (m.get("labelIds") or []),
        "pieces_jointes": bool(_pieces_gmail(charge)),
        "apercu": _apercu(_texte_du_message(charge), longueur_apercu),
    }


async def _lire_gmail(boite: str, dossier: str, limite: int,
                      depuis: Optional[datetime], recherche: Optional[str] = None,
                      avant: Optional[datetime] = None,
                      apercu=None) -> tuple[list[dict], Optional[int]]:
    import asyncio

    def _travail() -> tuple[list[dict], Optional[int]]:
        from ingestion.connectors.gmail import _service, _entete, _texte_du_message
        service = _service(boite)
        # Gmail filtre par requête, dans sa propre syntaxe. `after:` prend une
        # date à la journée — cohérent avec le départ à minuit de depuis_quand.
        requete = _requete_gmail(depuis, recherche, avant)
        commun = {"userId": "me", "labelIds": [dossier]}
        if requete:
            commun["q"] = requete
        liste = service.users().messages().list(maxResults=limite, **commun).execute()
        entrees = liste.get("messages", [])
        longueur = _longueur_apercu(len(entrees), apercu)
        resultats = []
        for entree in entrees:
            m = service.users().messages().get(
                userId="me", id=entree["id"], format="full").execute()
            resultats.append(_fiche_gmail(m, boite, longueur, _entete, _texte_du_message))

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

    # Le cache des connexions personnelles se recharge ICI, tant qu'une boucle
    # asyncio tourne encore : `_service` (dans le thread) ne sait que le lire.
    from mail import google_perso
    await google_perso.rafraichir()
    # Le client Google est synchrone : hors de la boucle événementielle.
    return await asyncio.to_thread(_travail)


async def _ouvrir_gmail(boite: str, identifiant: str) -> dict:
    import asyncio

    def _travail() -> dict:
        from ingestion.connectors.gmail import _service, _entete, _texte_du_message
        service = _service(boite)
        m = service.users().messages().get(userId="me", id=identifiant, format="full").execute()
        fiche = _fiche_gmail(m, boite, MAX_APERCU, _entete, _texte_du_message)
        charge = m.get("payload") or {}
        fiche["corps"] = _texte_lisible(_texte_du_message(charge))
        fiche["pieces_jointes"] = _pieces_gmail(charge)
        return fiche

    # Le cache des connexions personnelles se recharge ICI, tant qu'une boucle
    # asyncio tourne encore : `_service` (dans le thread) ne sait que le lire.
    from mail import google_perso
    await google_perso.rafraichir()
    return await asyncio.to_thread(_travail)


async def lire_boite(boite: str, dossier: str = "recus",
                     limite: int = 10, depuis=None, recherche=None, avant=None,
                     apercu=None) -> dict:
    """Derniers messages d'une boîte, lus en direct — et leur nombre.

    `dossier` : « recus » ou « envoyes ». `depuis` : une période (« 7j »,
    « semaine ») ou une date ISO ; sans lui, les plus récents. `recherche` :
    des mots-clés cherchés dans TOUTE la boîte (objet et corps) — ajouté le
    31/08 : « cherche dans les mails des demandes de travaux » n'avait aucun
    outil, le modèle relisait les 25 derniers et le disait. `avant` : une
    date, borne haute exclusive — c'est la PAGE SUIVANTE : le résultat donne
    `plus_ancien`, on le redonne en `avant` pour les 25 précédents. L'appelant
    DOIT avoir vérifié l'accès.
    """
    nom = fournisseur()                       # lève si rien n'est configuré
    cle = "envoyes" if str(dossier).lower().startswith("env") else "recus"
    limite = max(1, min(int(limite or 10), MAX_MESSAGES))
    debut = depuis_quand(depuis)
    borne = depuis_quand(avant)
    mots = " ".join(str(recherche or "").split()) or None
    logger.info("Lecture de %s (%s, %d messages%s%s%s) via %s", boite, cle, limite,
                f", depuis {debut.date()}" if debut else "",
                f", avant {borne.date()}" if borne else "",
                ", recherche" if mots else "", nom)
    if nom == "outlook":
        messages, total = await _lire_outlook(boite, DOSSIERS["outlook"][cle], limite, debut,
                                              recherche=mots, avant=borne, apercu=apercu)
    else:
        messages, total = await _lire_gmail(boite, DOSSIERS["gmail"][cle], limite, debut,
                                            recherche=mots, avant=borne, apercu=apercu)

    internes = sum(1 for m in messages if m.get("expediteur_interne"))
    automatiques = sum(1 for m in messages if m.get("expediteur_automatique"))

    # Ce que le modèle doit DIRE du compte — dans les mots exacts, parce que
    # « 25 messages » et « 84 messages dont voici les 25 derniers » ne sont pas
    # la même information, et c'est la seconde qu'on demande.
    plus_ancien = min((m.get("date_iso") for m in messages if m.get("date_iso")), default=None)
    if mots and total is None:
        compte = (f"{len(messages)} message(s) trouvé(s) pour « {mots} »"
                  + (f" (avant le {borne.date().strftime('%d/%m/%Y')})" if borne else "")
                  + " ; le total des correspondances n'est pas connu du fournisseur.")
    elif mots:
        compte = (f"{total}{'+' if total >= MAX_COMPTE else ''} message(s) correspondant à « {mots} »"
                  + (f" depuis le {debut.date().strftime('%d/%m/%Y')}" if debut else "")
                  + (f" avant le {borne.date().strftime('%d/%m/%Y')}" if borne else "")
                  + (f", dont voici les {len(messages)} plus récents." if total > len(messages)
                     else ", tous détaillés ci-dessous."))
    elif total is None:
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
        "recherche": mots,
        "avant": borne.isoformat() if borne else None,
        "plus_ancien": plus_ancien,
        # La PAGE SUIVANTE, mécanique : le modèle n'a rien à calculer.
        "pour_continuer": (
            f"Pour les {limite} messages PRÉCÉDENTS, rappelle lire_mails avec les mêmes "
            f"paramètres et avant={plus_ancien}."
            if plus_ancien and (len(messages) >= limite) else None),
        # L'EXTRAIT N'EST PAS LE MESSAGE. Sans cette phrase, le modèle résumait
        # « le mail » à partir de ses 160 premiers caractères, et le disait lu.
        "pour_lire_en_entier": (
            f"Chaque `apercu` est un EXTRAIT ({_longueur_apercu(len(messages), apercu)} caractères), "
            "pas le message. Pour le corps COMPLET et les pièces jointes d'un message : "
            "`lire_mail` avec sa `ref`."),
        "compte": compte,
        "domaine_entreprise": _domaine_entreprise(),
        "expediteurs_internes": internes,
        "expediteurs_automatiques": automatiques,
        # Dit explicitement ce que cet échantillon N'EST PAS. Sans cela, le
        # modèle tirait des conclusions sur l'entreprise entière à partir de
        # dix bulletins d'information reçus le matin même.
        "pour_analyser_tout_le_courrier": (
            f"Le DÉTAIL est borné à {MAX_MESSAGES} messages par appel ; le COMPTE, lui, "
            "est exact. Pour CHERCHER dans toute la boîte : `recherche` (mots-clés). "
            "Pour remonter le temps page par page : `avant` (voir pour_continuer). "
            "Pour analyser l'ensemble du courrier de l'entreprise : `lancer_enrichissement`."),
        "portee": (f"{compte} Un échantillon récent, pas un inventaire de l'entreprise. "
                   "Une adresse dont expediteur_interne vaut false n'appartient PAS à "
                   "l'entreprise."),
        "messages": messages,
    }


async def lire_message(boite: str, ref=None, objet=None, de=None, dossier: str = "recus") -> dict:
    """UN message, en entier : le corps complet (borné à MAX_CORPS, et la
    coupure est dite), les pièces jointes nommées.

    Par sa `ref` (rendue dans chaque liste) d'abord ; sinon par son `objet`
    — une recherche dans le dossier, dont on garde le meilleur candidat. Rien
    n'est modifié : le message n'est pas marqué lu. L'appelant DOIT avoir
    vérifié l'accès.
    """
    nom = fournisseur()
    cle = "envoyes" if str(dossier or "").lower().startswith("env") else "recus"
    identifiant = _resoudre(str(ref or ""), boite)
    if not identifiant:
        mots = " ".join(str(objet or "").split())
        if not mots and not de:
            raise ValueError("Il manque de quoi retrouver le message : sa référence, ou son objet.")
        recherche = mots or str(de)
        if nom == "outlook":
            candidats, _ = await _lire_outlook(boite, DOSSIERS["outlook"][cle], 5, None,
                                               recherche=recherche)
        else:
            candidats, _ = await _lire_gmail(boite, DOSSIERS["gmail"][cle], 5, None,
                                             recherche=recherche)
        choisi = _choisir(candidats, mots, de)
        if not choisi:
            raise LookupError(f"Aucun message ne correspond à « {recherche} » dans ce dossier.")
        identifiant = _resoudre(choisi["ref"], boite)
    logger.info("Ouverture d'un message de %s via %s", boite, nom)
    fiche = (await _ouvrir_outlook(boite, identifiant) if nom == "outlook"
             else await _ouvrir_gmail(boite, identifiant))
    corps = fiche.get("corps") or ""
    longueur = len(corps)
    coupe = longueur > MAX_CORPS
    fiche.update({
        "boite": boite,
        "corps": corps[:MAX_CORPS],
        "longueur": longueur,
        "corps_tronque": coupe,
        "a_faire": (
            "Le corps ci-dessus est le message ENTIER"
            + (f", sauf sa fin : {longueur - MAX_CORPS} caractères n'ont pas été lus, dis-le"
               if coupe else "")
            + ". Réponds à partir de son CONTENU (cite, résume, relève les demandes et les "
            "dates), jamais de l'extrait d'une liste."),
    })
    fiche.pop("apercu", None)
    return fiche
