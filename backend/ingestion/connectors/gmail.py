"""
Connecteur Gmail / Google Workspace — lecture seule.

Duret & Sols est sur Google Workspace : l'accès serveur passe par un COMPTE DE
SERVICE avec « délégation à l'échelle du domaine ». Le backend emprunte alors
l'identité de chaque boîte (impersonation) sans demander de consentement
individuel, ce qui serait ingérable pour une équipe.

⚠ La délégation domaine est PUISSANTE : le compte de service peut lire
n'importe quelle boîte du domaine. C'est précisément pourquoi :
  * on n'accorde que `gmail.readonly` pour les mails, et — séparément —
    `admin.directory.user.readonly` pour lister les comptes. Deux scopes
    distincts : on peut accorder l'un sans l'autre, ou retirer l'un des deux ;
  * la liste des boîtes synchronisées est BORNÉE (voir `boites_a_synchroniser`) ;
  * l'accès applicatif reste arbitré par `mail.authorization` — ce n'est pas
    parce que le serveur PEUT lire une boîte qu'un utilisateur y a droit.

Adresses : rien n'est codé en dur. Les boîtes viennent des comptes de
l'application (`users.email`), du DOMAINE lui-même quand l'annuaire est
accessible (`boites_du_domaine`), plus d'éventuelles boîtes partagées listées
dans `GMAIL_EXTRA_MAILBOXES`. Inutile de connaître les adresses à l'avance.

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

# Scope SÉPARÉ, volontairement distinct de celui des mails : lister les comptes
# du domaine n'a rien à voir avec lire leur courrier. Deux scopes distincts,
# c'est deux autorisations à accorder dans la console Admin — et la possibilité
# de n'accorder que la première, ou de retirer l'une sans l'autre.
SCOPES_ANNUAIRE = ["https://www.googleapis.com/auth/admin.directory.user.readonly"]

_RE_BALISES = re.compile(r"<[^>]+>")


def _reglage(nom: str) -> str:
    """Un réglage du compte de service : Paramètres (table `cles_api`) d'abord,
    `.env` ensuite — même priorité que les clés de modèles (`llm/cles.py`).

    Pourquoi : la clé, le domaine et l'administrateur se saisissent désormais
    dans Paramètres → Clés API (11/09). Sans ce détour, une clé collée à
    l'écran serait ignorée tant que le `.env` du serveur ne la porte pas.
    """
    try:
        from llm.cles import valeur
        v = valeur(nom)
    except Exception:  # noqa: BLE001 — sans cache de clés, le .env
        v = getattr(settings, nom, None)
    return str(v or "").strip()


def _domaine() -> str:
    """Le domaine dont on emprunte les boîtes, sans « @ » ni majuscules."""
    return _reglage("gmail_domain").strip("@").lower()


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


def _cle_compte_de_service() -> Optional[dict]:
    """La clé du compte de service, VARIABLE d'abord, fichier ensuite.

    POURQUOI PAS SEULEMENT UN FICHIER. Le déposer sur le serveur suppose les
    bons droits sur `backend/secrets/`, qui appartient à root — créé par Docker.
    Le `scp` échoue en « Permission denied », et le contournement (sudo, reprise
    de propriétaire) est à refaire à chaque machine et facile à oublier au
    déploiement suivant. `GOOGLE_SA_JSON` reçoit donc le contenu de la clé,
    sur une ligne, comme les autres identifiants.

    Rend `None` quand rien n'est configuré : c'est à l'appelant de décider si
    c'est une panne (Gmail) ou un simple repli (l'annuaire).
    """
    import json
    import os

    brut = _reglage("google_sa_json")
    if brut:
        try:
            return json.loads(brut)
        except ValueError as e:
            raise NotImplementedError(
                f"Clé du compte de service illisible ({e}). Attendu : le contenu "
                "exact du fichier .json téléchargé dans la console Google Cloud "
                "(Paramètres → Clés API, ou GOOGLE_SA_JSON sur une ligne).") from e

    fichier = settings.google_sa_file
    if fichier and os.path.exists(fichier):
        with open(fichier, encoding="utf-8") as f:
            return json.load(f)
    return None


def _service(boite: str):
    """Client Gmail : la connexion PERSONNELLE de la boîte d'abord, l'emprunt
    d'identité (compte de service, délégation domaine) ensuite.

    L'ordre est une question de consentement : quand la personne a relié sa
    boîte elle-même (Paramètres > Ma boîte Google), c'est SON autorisation qui
    sert — l'emprunt d'identité reste le chemin des boîtes jamais reliées.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    from mail import google_perso
    perso = google_perso.credentials_pour_boite(boite)
    if perso is not None:
        return build("gmail", "v1", credentials=perso, cache_discovery=False)

    infos = _cle_compte_de_service()
    if infos is None:
        raise NotImplementedError(
            f"La boîte {boite} n'est pas reliée (Paramètres > Ma boîte Google) "
            "et aucun compte de service n'est configuré : collez la clé "
            "dans Paramètres → Clés API (carte « Gmail par compte de service »), "
            f"ou dans GOOGLE_SA_JSON (une ligne), ou déposez-la dans "
            f"{settings.google_sa_file or 'GOOGLE_SA_FILE'}, puis autorisez la "
            "délégation domaine (console Admin > Sécurité > Contrôles des API > "
            f"Délégation à l'échelle du domaine) avec le scope {SCOPES[0]}."
        )
    creds = service_account.Credentials.from_service_account_info(
        infos, scopes=SCOPES, subject=boite         # subject = la boîte empruntée
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# Scope SÉPARÉ, même logique que l'annuaire : ENVOYER n'a rien à voir avec
# LIRE. La délégation domaine s'accorde scope par scope dans la console Admin —
# on peut donner la lecture sans l'envoi, ou retirer l'envoi seul.
SCOPES_ENVOI = ["https://www.googleapis.com/auth/gmail.send"]


def _service_envoi(boite: str):
    """Client Gmail capable d'ENVOYER depuis cette boîte.

    Même ordre que `_service` : la connexion personnelle d'abord — le
    consentement de `mail/google_perso` porte déjà `gmail.send`, prévu « pour
    le jour où l'expéditeur sera la personne elle-même », qui est arrivé —,
    l'emprunt d'identité ensuite, avec le SEUL scope d'envoi : un client qui
    envoie n'a pas besoin de lire.

    L'unique appelant est `mail.expedition.envoyer_message`, lui-même appelé
    par le seul skill `envoyer_email`, à effet EXTERNE : aucun message ne part
    sans validation humaine.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    from mail import google_perso
    perso = google_perso.credentials_pour_boite(boite)
    if perso is not None:
        return build("gmail", "v1", credentials=perso, cache_discovery=False)

    infos = _cle_compte_de_service()
    if infos is None:
        raise NotImplementedError(
            f"La boîte {boite} n'est pas reliée (Paramètres > Ma boîte Google) "
            "et aucun compte de service n'est configuré : l'envoi est "
            "impossible. Reliez la boîte, ou accordez la délégation domaine "
            f"avec le scope {SCOPES_ENVOI[0]}."
        )
    creds = service_account.Credentials.from_service_account_info(
        infos, scopes=SCOPES_ENVOI, subject=boite
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# L'AGENDA (11/09) : scope séparé, comme l'envoi et l'annuaire. Lire et poser
# des rendez-vous — pas les réglages de l'agenda lui-même.
SCOPES_AGENDA = ["https://www.googleapis.com/auth/calendar.events"]


def _service_agenda(boite: str):
    """Client Google Agenda pour cette boîte.

    Même ordre que `_service` : la connexion OAuth du compte d'abord — c'est la
    SEULE voie pour un compte Gmail personnel (le mot de passe d'application ne
    vaut que pour IMAP/SMTP, et Google a fermé CalDAV à tout sauf OAuth) —,
    l'emprunt d'identité ensuite, pour un domaine Google Workspace.

    Un compte relié AVANT l'ajout de l'agenda n'a pas accordé ce droit : on le
    dit (« reliez à nouveau ») au lieu de laisser Google répondre un 403 muet.
    """
    from googleapiclient.discovery import build

    from mail import google_perso
    accorde = google_perso.accorde(boite, SCOPES_AGENDA[0])
    if accorde is False:
        raise NotImplementedError(
            f"Le compte Google {boite} est relié, mais sans l'agenda (il l'a été "
            "avant que l'agenda soit demandé). Reliez-le à nouveau : Paramètres → "
            "Clés API → carte de la boîte mail → « Relier l'agenda Google ».")
    perso = google_perso.credentials_pour_boite(boite) if accorde else None
    if perso is not None:
        return build("calendar", "v3", credentials=perso, cache_discovery=False)

    infos = _cle_compte_de_service()
    if infos is None:
        raise NotImplementedError(
            f"L'agenda de {boite} n'est pas relié. Pour un compte Gmail, il faut "
            "une connexion Google (OAuth) : Paramètres → Clés API → renseigner le "
            "client OAuth, puis, sur la carte de la boîte mail, « Relier l'agenda "
            "Google » avec ce compte.")
    from google.oauth2 import service_account
    creds = service_account.Credentials.from_service_account_info(
        infos, scopes=SCOPES_AGENDA, subject=boite)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _service_annuaire():
    """Client Admin SDK, empruntant l'identité d'un ADMINISTRATEUR du domaine.

    Différence essentielle avec Gmail : là on emprunte chaque boîte, ici il faut
    une identité administrateur — l'annuaire n'est pas lisible par un compte
    ordinaire. D'où un réglage distinct, `GOOGLE_ADMIN_SUBJECT`.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sujet = _reglage("google_admin_subject").lower()
    if not sujet:
        return None
    infos = _cle_compte_de_service()
    if infos is None:
        return None
    creds = service_account.Credentials.from_service_account_info(
        infos, scopes=SCOPES_ANNUAIRE, subject=sujet)
    return build("admin", "directory_v1", credentials=creds, cache_discovery=False)


async def boites_du_domaine() -> list[str]:
    """Toutes les boîtes du domaine, demandées à l'annuaire Google.

    Sans cela, une personne SANS compte dans l'application a une boîte
    invisible : la liste était déduite des seuls comptes applicatifs, et il
    fallait déclarer chaque adresse à la main.

    Ne lève jamais. La découverte est un CONFORT : si le scope annuaire n'est
    pas délégué, ou si aucun compte administrateur n'est configuré, on renvoie
    une liste vide et le connecteur retombe sur les comptes de l'application.
    """
    import asyncio

    domaine = _domaine()

    def _lister() -> list[str]:
        service = _service_annuaire()
        if service is None:
            logger.info("Découverte du domaine désactivée : GOOGLE_ADMIN_SUBJECT "
                        "ou clé de compte de service absente.")
            return []
        trouvees: list[str] = []
        jeton = None
        while True:
            requete = service.users().list(
                domain=domaine or None,
                customer=None if domaine else "my_customer",
                maxResults=500, orderBy="email", pageToken=jeton)
            reponse = requete.execute()
            for u in reponse.get("users", []):
                # Un compte suspendu ou archivé n'a plus de boîte à lire.
                if u.get("suspended") or u.get("archived"):
                    continue
                adresse = (u.get("primaryEmail") or "").strip().lower()
                if "@" in adresse:
                    trouvees.append(adresse)
            jeton = reponse.get("nextPageToken")
            if not jeton:
                return trouvees

    try:
        # Le client Google est SYNCHRONE : hors de la boucle événementielle,
        # sinon la pagination fige tout le backend le temps de l'inventaire.
        trouvees = await asyncio.to_thread(_lister)
    except Exception as e:  # noqa: BLE001
        # 403 = scope annuaire non délégué. C'est le cas le plus fréquent, et il
        # ne doit pas faire échouer la synchronisation des mails.
        logger.info("Découverte du domaine impossible (%s) — seuls les comptes "
                    "de l'application seront synchronisés.", e)
        return []

    if domaine:
        trouvees = [b for b in trouvees if b.endswith("@" + domaine)]
    logger.info("Découverte du domaine : %d boîte(s)", len(trouvees))
    return trouvees


async def boites_a_synchroniser() -> list[str]:
    """Boîtes à parcourir : comptes de l'application, domaine, boîtes partagées.

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

    # Les boîtes RELIÉES personnellement (Paramètres > Ma boîte Google) : une
    # adresse Google peut différer du compte applicatif, elle doit quand même
    # être synchronisée — et elle échappe au filtre de domaine ci-dessous,
    # car elle n'emprunte aucune identité : la personne a consenti elle-même.
    from mail import google_perso
    await google_perso.rafraichir()
    connectees = set(google_perso.emails_connectes())
    for adresse in sorted(connectees):
        if adresse not in boites:
            boites.append(adresse)

    # Puis tout le domaine, si l'annuaire est accessible. L'ordre compte : les
    # comptes de l'application restent en tête, ce sont les plus utiles.
    if settings.gmail_decouvrir_domaine:
        for adresse in await boites_du_domaine():
            if adresse not in boites:
                boites.append(adresse)

    for extra in (settings.gmail_extra_mailboxes or "").split(","):
        extra = extra.strip().lower()
        if "@" in extra and extra not in boites:
            boites.append(extra)                    # ex. contact@, compta@

    domaine = _domaine()
    if domaine:
        # Garde-fou : ne jamais tenter d'emprunter une identité hors du domaine
        # de l'entreprise (un compte invité ne relève pas de la délégation).
        hors = [b for b in boites
                if not b.endswith("@" + domaine) and b not in connectees]
        for b in hors:
            logger.info("Boîte ignorée (hors domaine %s) : %s", domaine, b)
        boites = [b for b in boites
                  if b.endswith("@" + domaine) or b in connectees]
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
            # PAS d'anonymisation à l'ingestion, volontairement. Elle jetterait la
            # carte de correspondance : les messages seraient stockés avec des
            # jetons [PER_1] indéchiffrables à jamais, et — plus grave — ces jetons
            # entreraient en collision avec ceux du tour de conversation, si bien
            # que la réhydratation réinjecterait le NOM DE QUELQU'UN D'AUTRE dans
            # une citation de mail. Le masquage a lieu à la requête (anonymize_node),
            # avec une carte cohérente : aucune PII n'atteint le modèle pour autant.
            anonymize=False,
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


# ── LA CARTE DE PARAMÈTRES (11/09) ────────────────────────────────────────────
# Noa : « connecter Gmail via compte de service, prévois ça pour que je rentre
# les clés ». La carte « Gmail par compte de service » (Paramètres → Clés API)
# passe par `routers/settings.py`, qui reste du socle : ses routes n'existent
# que là où CE connecteur existe. Trois gestes : valider la clé collée, dire
# ce qui est configuré, éprouver chaque autorisation.

CHAMPS_CLE = ("client_email", "client_id", "private_key", "token_uri")


def valider_cle(brut: str) -> str:
    """La clé collée (ou lue d'un fichier), vérifiée, remise sur UNE ligne.

    Lève `ValueError` avec une raison lisible. Le piège le plus courant est
    refusé en le nommant : la console Google Cloud télécharge AUSSI en .json
    la clé d'un client OAuth, qui ne sait emprunter aucune boîte.
    """
    import json

    texte = (brut or "").strip()
    if not texte:
        raise ValueError("aucune clé fournie")
    try:
        infos = json.loads(texte)
    except ValueError as e:
        raise ValueError(f"ce n'est pas du JSON lisible ({e}) — collez le fichier "
                         "en entier, accolades comprises") from e
    if not isinstance(infos, dict):
        raise ValueError("le fichier attendu est un objet JSON, entre accolades")
    if "web" in infos or "installed" in infos:
        raise ValueError(
            "c'est la clé d'un client OAuth, pas celle d'un compte de service : "
            "console Google Cloud → IAM et administration → Comptes de service → "
            "le compte → Clés → Ajouter une clé → JSON")
    if infos.get("type") != "service_account":
        raise ValueError(f"le champ « type » vaut « {infos.get('type')} » "
                         "au lieu de « service_account »")
    manquants = [c for c in CHAMPS_CLE if not str(infos.get(c) or "").strip()]
    if manquants:
        raise ValueError("champ(s) manquant(s) dans la clé : " + ", ".join(manquants))
    if "PRIVATE KEY" not in infos["private_key"]:
        raise ValueError("la clé privée est illisible (copie tronquée ?)")
    try:
        from google.oauth2 import service_account
        service_account.Credentials.from_service_account_info(infos, scopes=SCOPES)
    except ImportError:
        pass  # bibliothèque absente (banc hors conteneur) : le test de connexion jugera
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"clé privée refusée par la bibliothèque Google ({str(e)[:120]})") from e
    return json.dumps(infos, separators=(",", ":"), ensure_ascii=False)


def _origine_cle() -> Optional[str]:
    """D'où vient la clé effective : 'parametres', 'env', 'fichier' ou None."""
    import os
    try:
        from llm.cles import _CACHE
        if (_CACHE.get("google_sa_json") or "").strip():
            return "parametres"
    except Exception:  # noqa: BLE001
        pass
    if (getattr(settings, "google_sa_json", None) or "").strip():
        return "env"
    fichier = getattr(settings, "google_sa_file", None)
    if fichier and os.path.exists(fichier):
        return "fichier"
    return None


def etat_compte_de_service() -> dict:
    """Pour la carte : ce qui est configuré, d'où ça vient, et ce qu'il faut
    coller dans la console Admin. JAMAIS la clé privée.

    L'identifiant du client et l'adresse du compte ne sont pas des secrets :
    ce sont eux que l'administrateur recopie dans la délégation.
    """
    try:
        from llm.cles import masquer
    except Exception:  # noqa: BLE001
        def masquer(v):
            return "•" * len(v or "")
    etat = {
        "disponible": True, "configuree": False, "origine": _origine_cle(),
        "domaine": _domaine(), "administrateur": _reglage("google_admin_subject").lower(),
        "scopes": {"lecture": SCOPES[0], "envoi": SCOPES_ENVOI[0],
                   "agenda": SCOPES_AGENDA[0], "annuaire": SCOPES_ANNUAIRE[0]},
        "erreur": "",
    }
    try:
        infos = _cle_compte_de_service()
    except NotImplementedError as e:
        etat["erreur"] = str(e)
        infos = None
    if infos:
        etat.update(
            configuree=True,
            compte=str(infos.get("client_email") or ""),
            client_id=str(infos.get("client_id") or ""),
            projet=str(infos.get("project_id") or ""),
            empreinte=masquer(str(infos.get("private_key_id") or "")),
        )
        # L'ordre de la console : lecture, envoi, agenda, annuaire, séparés par des virgules.
        etat["a_coller"] = ",".join((SCOPES[0], SCOPES_ENVOI[0], SCOPES_AGENDA[0],
                                     SCOPES_ANNUAIRE[0]))
    return etat


def _raison_google(e: Exception) -> str:
    """L'erreur de Google traduite en geste à faire.

    Les messages bruts (« unauthorized_client: Client is unauthorized to
    retrieve access tokens using this method ») ne disent jamais QUOI faire ;
    chacun correspond pourtant à un réglage précis de la console.
    """
    texte = str(e)
    bas = texte.lower()
    if "accessnotconfigured" in bas or "has not been used in project" in bas or "it is disabled" in bas:
        return ("l'API n'est pas activée dans le projet Google Cloud (Bibliothèque "
                "→ « Gmail API », « Google Calendar API » pour l'agenda, « Admin "
                "SDK API » pour l'annuaire → Activer)")
    if "insufficient authentication scopes" in bas or "insufficientpermissions" in bas:
        return ("le compte a été relié sans ce droit : reliez-le à nouveau pour "
                "accorder aussi l'agenda")
    if "unauthorized_client" in bas:
        return ("autorisation non accordée : ajoutez ce champ d'application à la "
                "délégation du compte de service dans la console Admin (quelques "
                "minutes de propagation après l'ajout)")
    if "invalid_grant" in bas and ("invalid email" in bas or "user id" in bas):
        return "cette adresse n'est pas une boîte du domaine Google Workspace"
    if "invalid_grant" in bas:
        return (f"Google refuse la clé ({texte[:120]}) : clé supprimée ou "
                "désactivée dans la console, ou horloge du serveur décalée")
    if "failedprecondition" in bas or "precondition check failed" in bas:
        return "Gmail n'est pas activé pour cette boîte (compte sans licence Gmail, ou adresse hors Workspace)"
    if "not authorized to access this resource" in bas:
        return ("ce compte n'est pas administrateur du domaine : l'annuaire exige "
                "un administrateur qui peut lire les utilisateurs")
    return texte[:200]


async def boite_pour_le_test(email_courant: Optional[str] = None) -> Optional[str]:
    """La boîte sur laquelle éprouver la délégation.

    L'administrateur d'abord (c'est une vraie boîte du domaine, et c'est lui
    qui ouvre l'annuaire) ; sinon la personne qui clique, si elle est du
    domaine ; sinon le premier compte actif de l'application qui l'est. Le
    super-administrateur est souvent HORS domaine : sans ce repli, le bouton
    échouerait pour la seule personne qui s'en sert.
    """
    admin = _reglage("google_admin_subject").lower()
    if admin:
        return admin
    domaine = _domaine()
    moi = (email_courant or "").strip().lower()
    if moi and (not domaine or moi.endswith("@" + domaine)):
        return moi
    if not domaine:
        return moi or None
    try:
        async with get_db() as conn:
            adresse = await conn.fetchval(
                "SELECT lower(email) FROM users WHERE actif = true "
                "AND lower(email) LIKE $1 ORDER BY created_at LIMIT 1",
                "%@" + domaine)
    except Exception as e:  # noqa: BLE001
        logger.info("Boîte de test introuvable en base (%s)", e)
        adresse = None
    return adresse or None


def tester_compte_de_service(boite: Optional[str]) -> dict:
    """Un jeton par autorisation, puis une lecture réelle : ok, ou la raison.

    Quatre contrôles indépendants, parce que la délégation s'accorde champ par
    champ : lire peut marcher sans envoyer, l'agenda et l'annuaire sans l'un
    ni l'autre. RIEN n'est envoyé ni ouvert : l'envoi se juge à l'obtention de
    son jeton, la lecture au nombre de messages de la boîte. Synchrone (le
    client Google l'est) : l'appelant le passe dans un thread.
    """
    resultat = {"ok": False, "boite": boite or "", "lecture": None, "envoi": None,
                "agenda": None, "annuaire": None, "erreur": ""}
    try:
        infos = _cle_compte_de_service()
    except NotImplementedError as e:
        resultat["erreur"] = str(e)
        return resultat
    if infos is None:
        resultat["erreur"] = "aucune clé de compte de service enregistrée"
        return resultat
    if not boite:
        resultat["erreur"] = ("aucune boîte du domaine pour le test : renseignez "
                              "le domaine ou l'administrateur")
        return resultat
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as e:
        resultat["erreur"] = f"bibliothèque Google absente du serveur ({e})"
        return resultat

    def _jeton(scopes, sujet):
        creds = service_account.Credentials.from_service_account_info(
            infos, scopes=scopes, subject=sujet)
        creds.refresh(Request())
        return creds

    try:
        creds = _jeton(SCOPES, boite)
        profil = build("gmail", "v1", credentials=creds, cache_discovery=False) \
            .users().getProfile(userId="me").execute()
        resultat["lecture"] = {"ok": True, "messages": profil.get("messagesTotal")}
    except Exception as e:  # noqa: BLE001
        resultat["lecture"] = {"ok": False, "raison": _raison_google(e)}

    try:
        _jeton(SCOPES_ENVOI, boite)
        resultat["envoi"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        resultat["envoi"] = {"ok": False, "raison": _raison_google(e)}

    try:
        _jeton(SCOPES_AGENDA, boite)
        resultat["agenda"] = {"ok": True}
    except Exception as e:  # noqa: BLE001
        resultat["agenda"] = {"ok": False, "raison": _raison_google(e)}

    admin = _reglage("google_admin_subject").lower()
    if admin:
        try:
            creds = _jeton(SCOPES_ANNUAIRE, admin)
            domaine = _domaine()
            build("admin", "directory_v1", credentials=creds, cache_discovery=False) \
                .users().list(domain=domaine or None,
                              customer=None if domaine else "my_customer",
                              maxResults=1).execute()
            resultat["annuaire"] = {"ok": True}
        except Exception as e:  # noqa: BLE001
            resultat["annuaire"] = {"ok": False, "raison": _raison_google(e)}

    # L'annuaire et l'agenda sont des conforts (sans l'annuaire, seuls les
    # comptes de l'application sont lus ; sans l'agenda, seul l'agenda manque) :
    # ils ne font pas échouer le test, ils s'affichent à part.
    resultat["ok"] = bool(resultat["lecture"]["ok"] and resultat["envoi"]["ok"])
    return resultat
