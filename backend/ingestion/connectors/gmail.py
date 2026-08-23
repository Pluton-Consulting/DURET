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

    brut = (settings.google_sa_json or "").strip()
    if brut:
        try:
            return json.loads(brut)
        except ValueError as e:
            raise NotImplementedError(
                f"GOOGLE_SA_JSON illisible ({e}). Attendu : le contenu exact du "
                "fichier de clé du compte de service, sur UNE seule ligne.") from e

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
            f"dans GOOGLE_SA_JSON (une ligne) ou déposez-la dans "
            f"{settings.google_sa_file or 'GOOGLE_SA_FILE'}, puis autorisez la "
            "délégation domaine (console Admin > Sécurité > Contrôles des API > "
            f"Délégation à l'échelle du domaine) avec le scope {SCOPES[0]}."
        )
    creds = service_account.Credentials.from_service_account_info(
        infos, scopes=SCOPES, subject=boite         # subject = la boîte empruntée
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _service_annuaire():
    """Client Admin SDK, empruntant l'identité d'un ADMINISTRATEUR du domaine.

    Différence essentielle avec Gmail : là on emprunte chaque boîte, ici il faut
    une identité administrateur — l'annuaire n'est pas lisible par un compte
    ordinaire. D'où un réglage distinct, `GOOGLE_ADMIN_SUBJECT`.
    """
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    sujet = (settings.google_admin_subject or "").strip()
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

    domaine = (settings.gmail_domain or "").strip().lower()

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

    domaine = (settings.gmail_domain or "").strip().lower()
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
