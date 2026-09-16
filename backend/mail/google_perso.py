"""
Connexion Google PERSONNELLE — la « sous-connexion » de chaque utilisateur.

LE BESOIN. L'accès aux boîtes passait par un compte de service à délégation
domaine : puissant, mais il suppose un Google Workspace, la console
d'administration, et quelqu'un pour s'en occuper. Ici chaque personne relie SA
boîte elle-même : Paramètres > Ma boîte Google > consentement chez Google, une
seule fois. Elle se connecte à l'application par lien magique comme avant ; la
boîte, elle, reste reliée — le refresh token rendu par Google ne périme pas de
lui-même.

⚠️ CONDITION CÔTÉ CONSOLE GOOGLE pour que « ça reste connecté très longtemps » :
l'application OAuth doit être « interne » (organisation Workspace) ou, si elle
est « externe », PUBLIÉE en production. Une application externe laissée « en
test » voit ses refresh tokens révoqués par Google au bout de SEPT JOURS — le
symptôme serait des reconnexions hebdomadaires inexpliquées.

LE BRANCHEMENT. `ingestion/connectors/gmail.py::_service` essaie D'ABORD la
connexion personnelle de la boîte demandée, puis retombe sur le compte de
service. Rien d'autre ne bouge : l'autorisation applicative
(`mail.authorization`) continue d'arbitrer qui a le droit de lire quelle boîte.

LE CACHE. `_service` est appelé dans des threads (`asyncio.to_thread`), où
aucune boucle asyncio ne tourne : impossible d'y interroger la base. Les
connexions vivent donc dans un cache mémoire — rafraîchi au démarrage, après
chaque connexion/déconnexion, et avant chaque lecture — le même schéma que
`llm/cles.py`, pour la même raison (une donnée saisie dans Paramètres doit
survivre au redéploiement ET être visible d'un contexte synchrone).
"""
from __future__ import annotations

import logging
import secrets
import time
import urllib.parse
from datetime import timedelta
from typing import Optional

from config import settings

logger = logging.getLogger("duret.mail.google_perso")

# Les gestes demandés à Google. Lecture pour les skills mail, envoi pour le
# jour où l'expéditeur sera la personne elle-même, openid/email pour savoir
# QUELLE adresse vient d'être reliée (confirmée par Google, pas déclarée).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    # L'AGENDA (11/09, Noa : « il faut que ça ait accès aussi à Calendar »). Un
    # compte Gmail PERSONNEL n'ouvre son agenda que par OAuth : le mot de passe
    # d'application ne vaut que pour IMAP/SMTP, et Google a fermé CalDAV à tout
    # sauf OAuth. `calendar.events` suffit aux trois gestes (lire une période,
    # en déduire les créneaux, poser un rendez-vous) sans ouvrir les réglages
    # de l'agenda lui-même.
    "https://www.googleapis.com/auth/calendar.events",
    "openid",
    "email",
]

# RELIER L'AGENDA SEUL (11/09, Noa : « pour les mails je veux le mot de passe
# d'application »). Quand les mails passent par IMAP, demander aussi Gmail à
# Google ne sert à rien — et Gmail est un droit « restreint » : l'écran de
# consentement d'une application non validée en devient plus inquiétant. La
# carte de la boîte mail ne demande donc que l'agenda, plus l'adresse (pour
# savoir QUEL compte a consenti).
DROITS_AGENDA = ("https://www.googleapis.com/auth/calendar.events", "openid", "email")

# Les droits d'API qu'un compte relié AVANT l'agenda a forcément accordés
# (voir `accorde`). Déduits de SCOPES pour ne pas tenir deux listes.
SCOPES_HISTORIQUES = tuple(x for x in SCOPES
                           if x.startswith("https://") and "/auth/calendar" not in x)

URL_AUTORISATION = "https://accounts.google.com/o/oauth2/v2/auth"
URL_JETON = "https://oauth2.googleapis.com/token"
URL_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
URL_REVOCATION = "https://oauth2.googleapis.com/revoke"

# L'usage inscrit dans le jeton d'état : un JWT de session volé ne doit pas
# pouvoir servir d'état OAuth, ni l'inverse.
USAGE_STATE = "connexion_google"

# email normalisé -> refresh_token. Voir « LE CACHE » ci-dessus.
_CACHE: dict[str, str] = {}
# DEUX ENTRÉES POUR LA MÊME LIGNE, parce que les deux socles ne posent pas la
# même question. Le mail demande « le jeton de CETTE boîte » ; le socle
# documentaire du jumeau demande « le jeton de la PERSONNE qui parle » — et son
# adresse Google peut différer de son compte applicatif. Chercher par email
# relierait le mauvais compte au premier salarié dont les deux adresses
# divergent. Inutilisé ici (Duret est sur NAS) : présent pour que le module ne
# diverge de celui du jumeau que par ses SCOPES.
_PAR_USER: dict[str, dict] = {}      # user_id -> {"email": …, "refresh_token": …}
_CACHE_QUAND: float = 0.0
_CACHE_TTL_S = 300


def _normaliser(adresse: Optional[str]) -> str:
    return (adresse or "").strip().lower()


# Les droits ACCORDÉS par compte, tels que Google les a rendus au consentement.
# Un compte relié AVANT l'ajout d'un droit ne l'a pas : le demander au
# rafraîchissement du jeton ferait échouer TOUT le reste (Google refuse un droit
# jamais accordé) — on ne demande donc que ce qui a été accordé, et l'on sait
# dire « reliez à nouveau » quand un geste réclame un droit absent.
_SCOPES_PAR_EMAIL: dict[str, list[str]] = {}


def _client() -> tuple[str, str]:
    """L'identifiant et le secret du client OAuth : Paramètres (table
    `cles_api`) d'abord, `.env` ensuite — même priorité que les clés (11/09)."""
    try:
        from llm.cles import valeur
        ident, secret = valeur("google_oauth_client_id"), valeur("google_oauth_client_secret")
    except Exception:  # noqa: BLE001 — sans cache de clés, le .env
        ident = getattr(settings, "google_oauth_client_id", None)
        secret = getattr(settings, "google_oauth_client_secret", None)
    return str(ident or "").strip(), str(secret or "").strip()


def configurable() -> bool:
    """Le client OAuth est-il renseigné ? Sans lui, l'écran explique quoi faire."""
    ident, secret = _client()
    return bool(ident and secret)


def _scopes_accordes(brut: Optional[str]) -> list[str]:
    """« a b c » (la chaîne rendue par Google) → les droits d'API, sans openid."""
    return [x for x in (brut or "").split() if x.startswith("https://")]


def accorde(boite: str, scope: str) -> Optional[bool]:
    """Ce compte a-t-il accordé ce droit ? None s'il n'est pas relié du tout.

    Un compte relié dont on ne connaît pas les droits (ligne ancienne, colonne
    vide) est présumé avoir accordé ce qui était demandé à l'époque — c'est-à-
    dire pas les droits ajoutés depuis : on répond donc selon SCOPES_HISTORIQUES.
    """
    email = _normaliser(boite)
    if email not in _CACHE:
        return None
    connus = _SCOPES_PAR_EMAIL.get(email)
    if not connus:
        return scope in SCOPES_HISTORIQUES
    return scope in connus


# CE QU'UN COMPTE RELIÉ PERMET RÉELLEMENT (16/09, audit D-19). Un compte
# autorisé à LIRE le Drive n'a pas pour autant le droit d'écrire un brouillon
# Gmail : les droits se lisent dans les scopes que Google a RENDUS au
# consentement, pas dans ceux qu'on avait demandés. Sans cette table, un geste
# partait, échouait chez Google, et rendait une erreur d'API à la personne.
CAPACITES = {
    "drive_lecture": ("https://www.googleapis.com/auth/drive",
                      "https://www.googleapis.com/auth/drive.readonly"),
    "drive_ecriture": ("https://www.googleapis.com/auth/drive",
                       "https://www.googleapis.com/auth/drive.file"),
    "gmail_lecture": ("https://www.googleapis.com/auth/gmail.readonly",
                      "https://mail.google.com/"),
    "gmail_envoi": ("https://www.googleapis.com/auth/gmail.send",
                    "https://mail.google.com/"),
    "gmail_brouillon": ("https://www.googleapis.com/auth/gmail.compose",
                        "https://mail.google.com/"),
    "agenda": ("https://www.googleapis.com/auth/calendar.events",
               "https://www.googleapis.com/auth/calendar"),
}

# Ce qu'il faut demander pour obtenir une capacité qui manque — ce n'est pas
# forcément le premier scope de la liste : on redemande le plus étroit qui
# suffit, jamais « tout Gmail » pour poser un brouillon.
DEMANDE_POUR = {
    "drive_lecture": "https://www.googleapis.com/auth/drive",
    "drive_ecriture": "https://www.googleapis.com/auth/drive",
    "gmail_lecture": "https://www.googleapis.com/auth/gmail.readonly",
    "gmail_envoi": "https://www.googleapis.com/auth/gmail.send",
    "gmail_brouillon": "https://www.googleapis.com/auth/gmail.compose",
    "agenda": "https://www.googleapis.com/auth/calendar.events",
}


def capacites(boite: str) -> Optional[set]:
    """Ce que ce compte relié permet, d'après les droits RENDUS par Google.

    None : le compte n'est pas relié du tout — ce n'est pas la même chose
    qu'un compte relié sans le droit demandé, et l'écran ne dit pas la même
    phrase dans les deux cas.
    """
    email = _normaliser(boite)
    if email not in _CACHE:
        return None
    accordes = set(_SCOPES_PAR_EMAIL.get(email) or SCOPES_HISTORIQUES)
    return {nom for nom, exigés in CAPACITES.items() if accordes & set(exigés)}


def peut(boite: str, capacite: str) -> bool:
    """Ce compte peut-il faire CE geste-là ? (fail-closed : non relié = non)"""
    acquises = capacites(boite)
    return bool(acquises and capacite in acquises)


def refus_de_capacite(boite: str, capacite: str) -> str:
    """Le message à rendre quand le droit manque — il dit quoi faire, pas
    seulement que c'est refusé."""
    acquises = capacites(boite)
    if acquises is None:
        return ("Ce compte Google n'est pas relié à l'assistant : Paramètres → "
                "Mon compte Google, puis « Relier mon compte ».")
    return (f"Le compte {boite} est relié, mais il n'a pas accordé le droit nécessaire "
            f"à ce geste ({capacite.replace('_', ' ')}). Reliez-le à nouveau depuis "
            "Paramètres → Mon compte Google : Google redemandera ce droit-là.")


def _scopes_pour(email: str) -> list[str]:
    """Les droits à demander au rafraîchissement : ceux accordés, sinon ceux
    d'avant l'agenda (un compte relié sans trace de ses droits les avait)."""
    return _SCOPES_PAR_EMAIL.get(_normaliser(email)) or list(SCOPES_HISTORIQUES)


def _redirect_uri() -> str:
    # L'API vit derrière le même domaine que l'écran : c'est le navigateur de
    # l'utilisateur qui suit cette redirection, Google n'a pas besoin de
    # joindre le serveur — le VPN ne gêne donc pas.
    return settings.app_url.rstrip("/") + "/api/google/retour"


def lien_autorisation(user_id: str, compte: Optional[str] = None,
                      droits: Optional[str] = None) -> str:
    """L'URL de consentement Google pour CET utilisateur.

    `state` est un JWT court (10 min) portant l'identité : au retour, c'est LUI
    qui dit à qui appartient le consentement — le navigateur revient sans
    en-tête d'authentification, et un state forgé serait rejeté à la
    vérification de signature.

    `prompt=consent` + `access_type=offline` : Google ne rend le refresh token
    qu'au consentement explicite — sans ces deux paramètres, une reconnexion
    rendrait un jeton sans refresh, donc une connexion qui meurt dans l'heure.
    """
    if not configurable():
        raise RuntimeError("Client OAuth Google non configuré "
                           "(Paramètres → Clés API, ou GOOGLE_OAUTH_CLIENT_ID / "
                           "GOOGLE_OAUTH_CLIENT_SECRET).")
    from auth.jwt_handler import create_access_token
    # UN ÉTAT NE SERT QU'UNE FOIS (16/09, audit D-19). Signé et daté, il l'était
    # déjà ; rejouable pendant dix minutes, il l'était aussi — un retour Google
    # capturé (historique du navigateur, journal d'un proxy) pouvait être
    # renvoyé. Le `nonce` est retenu à l'émission et CONSOMMÉ à la vérification.
    nonce = secrets.token_urlsafe(12)
    _nonce_emis(nonce)
    state = create_access_token({"sub": str(user_id), "usage": USAGE_STATE, "nonce": nonce},
                                expires_delta=timedelta(minutes=10))
    params = {
        "client_id": _client()[0],
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(DROITS_AGENDA if droits == "agenda" else SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    # LE COMPTE ATTENDU, PRÉSÉLECTIONNÉ (11/09). Pour relier la boîte de
    # l'entreprise, l'administrateur a souvent plusieurs comptes Google ouverts
    # dans son navigateur : choisir le mauvais relierait SA boîte à la place.
    # C'est une suggestion à Google, pas une garantie — l'adresse retenue reste
    # celle que Google confirme au retour.
    if compte and "@" in compte:
        params["login_hint"] = _normaliser(compte)
    return URL_AUTORISATION + "?" + urllib.parse.urlencode(params)


# Les états émis et pas encore consommés. Bornés en nombre et en temps : cette
# mémoire vit dans le processus, comme le flux OAuth qu'elle protège (dix
# minutes). Un redémarrage entre l'aller et le retour fait échouer le retour —
# c'est le bon sens du rejeu : on refuse ce qu'on ne peut pas prouver.
_NONCES: dict[str, float] = {}
_NONCE_TTL_S = 900
_MAX_NONCES = 2000


def _nonce_emis(nonce: str) -> None:
    maintenant = time.monotonic()
    for ancien, quand in list(_NONCES.items()):
        if maintenant - quand > _NONCE_TTL_S:
            _NONCES.pop(ancien, None)
    if len(_NONCES) >= _MAX_NONCES:
        _NONCES.clear()
    _NONCES[nonce] = maintenant


def _nonce_consomme(nonce: str) -> bool:
    """Vrai si ce nonce était bien en attente — et il ne l'est plus."""
    return _NONCES.pop(nonce, None) is not None


def verifier_state(state: str) -> str:
    """L'identifiant d'utilisateur porté par un state valide — lève sinon.

    Trois contrôles, dans cet ordre : la SIGNATURE et la date (le JWT),
    l'USAGE (un jeton de session ne vaut pas un état OAuth), et le REJEU (un
    état ne sert qu'une fois).
    """
    from auth.jwt_handler import decode_access_token
    donnees = decode_access_token(state)
    if not isinstance(donnees, dict) or donnees.get("usage") != USAGE_STATE:
        raise ValueError("state OAuth invalide")
    nonce = str(donnees.get("nonce") or "")
    if nonce and not _nonce_consomme(nonce):
        raise ValueError("state OAuth déjà utilisé")
    if not nonce:
        # État émis par une version d'avant ce correctif : signé, daté, lié à
        # une personne. On l'accepte le temps que les liens en vol s'éteignent.
        logger.info("État OAuth sans marque d'unicité (lien ouvert avant la mise à jour)")
    user_id = str(donnees.get("sub") or "")
    if not user_id:
        raise ValueError("state OAuth sans identité")
    return user_id


async def echanger_code(code: str) -> dict:
    """Échange le code d'autorisation : refresh token + adresse CONFIRMÉE.

    L'adresse vient de `userinfo`, pas d'une déclaration : c'est Google qui dit
    quelle boîte a consenti — indispensable, car c'est cette adresse qui
    autorisera ensuite le connecteur à lire LA bonne boîte.
    """
    import httpx

    async with httpx.AsyncClient(timeout=20) as client:
        ident, secret = _client()
        rep = await client.post(URL_JETON, data={
            "client_id": ident,
            "client_secret": secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri(),
        })
        rep.raise_for_status()
        jetons = rep.json()
        if not jetons.get("refresh_token"):
            # `prompt=consent` le garantit normalement ; si Google ne le rend
            # pas, enregistrer une connexion qui mourra dans l'heure serait un
            # mensonge — on préfère un échec franc et une nouvelle tentative.
            raise ValueError("Google n'a pas rendu de refresh token")
        infos = await client.get(URL_USERINFO, headers={
            "Authorization": f"Bearer {jetons['access_token']}"})
        infos.raise_for_status()
        email = _normaliser(infos.json().get("email"))
        if not email:
            raise ValueError("Google n'a pas confirmé l'adresse de la boîte")

    return {"email": email,
            "refresh_token": jetons["refresh_token"],
            "scope": jetons.get("scope", "")}


# L'usage du coffre pour ces jetons : il entre dans la dérivation de la clé.
USAGE_COFFRE = "google-refresh"


async def enregistrer(user_id: str, email: str, refresh_token: str, scopes: str) -> None:
    """Retient (ou remplace) la connexion de cet utilisateur, cache compris.

    LE JETON EST CHIFFRÉ AVANT D'ÊTRE ÉCRIT (16/09, audit D-19) : ce n'est pas
    un mot de passe qu'on change en cinq minutes, c'est une clé permanente vers
    la boîte de la personne. Une sauvegarde égarée ou un accès en lecture à la
    base ne doit pas la livrer.
    """
    from database.connection import get_db
    from security import coffre
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO connexions_google (user_id, email, refresh_token, scopes)
               VALUES ($1::uuid, $2, $3, $4)
               ON CONFLICT (user_id) DO UPDATE
                   SET email = $2, refresh_token = $3, scopes = $4, maj_le = NOW()""",
            user_id, _normaliser(email),
            coffre.chiffrer(refresh_token, USAGE_COFFRE),
            scopes or "")
    await rafraichir(force=True)


async def etat(user_id: str) -> Optional[dict]:
    """Ce que l'écran affiche : l'adresse reliée et depuis quand. JAMAIS le jeton."""
    from database.connection import get_db
    async with get_db() as conn:
        ligne = await conn.fetchrow(
            "SELECT email, connecte_le FROM connexions_google WHERE user_id = $1::uuid",
            user_id)
    return dict(ligne) if ligne else None


async def deconnecter(user_id: str) -> bool:
    """Oublie la connexion, et demande à Google de révoquer le jeton.

    La révocation est best-effort : Google injoignable ne doit pas empêcher la
    déconnexion locale — le jeton supprimé de la base ne servira plus de toute
    façon, et l'utilisateur peut aussi révoquer depuis son compte Google.
    """
    from database.connection import get_db
    async with get_db() as conn:
        jeton = await conn.fetchval(
            "DELETE FROM connexions_google WHERE user_id = $1::uuid RETURNING refresh_token",
            user_id)
    if jeton:
        try:
            import httpx

            from security import coffre
            # Le jeton sort du coffre pour être révoqué CHEZ GOOGLE : oublier la
            # ligne chez nous ne suffit pas, la clé resterait valable là-bas.
            en_clair = coffre.dechiffrer(jeton, USAGE_COFFRE)
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(URL_REVOCATION, params={"token": en_clair or jeton})
        except Exception as e:  # noqa: BLE001
            logger.info("Révocation Google non aboutie (connexion oubliée localement) : %s", e)
    await rafraichir(force=True)
    return bool(jeton)


async def rafraichir(force: bool = False) -> None:
    """Recharge le cache email -> refresh_token depuis la base."""
    global _CACHE, _PAR_USER, _CACHE_QUAND, _SCOPES_PAR_EMAIL
    if not force and (time.monotonic() - _CACHE_QUAND) < _CACHE_TTL_S:
        return
    from database.connection import get_db
    try:
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT user_id, email, refresh_token, scopes FROM connexions_google")
    except Exception as e:  # noqa: BLE001 - table absente (migration pas passée) : cache vide
        logger.info("Connexions Google non chargées : %s", e)
        return
    # LE COFFRE SE LIT ICI, ET NULLE PART AILLEURS : c'est le seul endroit qui
    # lit la table. Une ligne écrite AVANT le coffre est en clair — on la lit
    # telle quelle (les couper le jour du déploiement fermerait tous les comptes
    # reliés) et on la réécrit chiffrée : la rotation se fait à l'usage.
    from security import coffre
    clairs, a_reecrire = {}, []
    for l in lignes:
        jeton = coffre.dechiffrer(l["refresh_token"], USAGE_COFFRE)
        if jeton is None:
            logger.warning("Connexion Google illisible pour %s : clé de chiffrement changée",
                           _normaliser(l["email"]))
            continue
        clairs[str(l["user_id"])] = (_normaliser(l["email"]), jeton,
                                     _scopes_accordes(l["scopes"]))
        if coffre.a_rechiffrer(l["refresh_token"]):
            a_reecrire.append((str(l["user_id"]), jeton))
    _CACHE = {email: jeton for email, jeton, _ in clairs.values()}
    _SCOPES_PAR_EMAIL = {email: scopes for email, _, scopes in clairs.values()}
    _PAR_USER = {uid: {"email": email, "refresh_token": jeton}
                 for uid, (email, jeton, _) in clairs.items()}
    _CACHE_QUAND = time.monotonic()
    logger.info("Connexions Google : %d boîte(s) reliée(s)", len(_CACHE))
    for uid, jeton in a_reecrire:
        try:
            async with get_db() as conn:
                await conn.execute(
                    "UPDATE connexions_google SET refresh_token = $2 WHERE user_id = $1::uuid",
                    uid, coffre.chiffrer(jeton, USAGE_COFFRE))
        except Exception as e:  # noqa: BLE001 — la lecture a réussi : ce n'est pas bloquant
            logger.info("Jeton Google non rechiffré (%s) : %s", uid, e)
    if a_reecrire:
        logger.info("Jetons Google mis au coffre : %d", len(a_reecrire))


def emails_connectes() -> list[str]:
    """Les boîtes reliées (du cache) — la synchronisation les ajoute aux siennes."""
    return sorted(_CACHE.keys())


def credentials_pour_boite(boite: str):
    """Les identifiants OAuth de la boîte demandée, ou None si elle n'est pas reliée.

    Synchrone à dessein (appelé depuis les threads du connecteur) : ne lit QUE
    le cache. La bibliothèque google-auth rafraîchit elle-même l'access token à
    partir du refresh token, sans boucle asyncio.
    """
    jeton = _CACHE.get(_normaliser(boite))
    if not jeton or not configurable():
        return None
    from google.oauth2.credentials import Credentials
    ident, secret = _client()
    return Credentials(
        token=None,
        refresh_token=jeton,
        token_uri=URL_JETON,
        client_id=ident,
        client_secret=secret,
        scopes=_scopes_pour(boite),
    )


def compte_connecte(user_id: str) -> Optional[str]:
    """L'adresse Google reliée par cette personne, ou None. Lecture du cache."""
    entree = _PAR_USER.get(str(user_id or ""))
    return entree["email"] if entree else None


def credentials_pour_utilisateur(user_id: str):
    """Les identifiants OAuth de la PERSONNE qui demande, ou None.

    Rendre None n'est PAS une panne : c'est « elle n'a pas relié son compte »,
    et l'appelant décide. Synchrone, comme `credentials_pour_boite` : appelée
    depuis les threads du connecteur, où aucune boucle asyncio ne tourne.

    Le test `configurable()` est là pour la même raison qu'au-dessus : sans lui,
    un `.env` amputé produirait des `Credentials` sans `client_id`, et l'échec
    surviendrait au premier appel au lieu d'ici.
    """
    entree = _PAR_USER.get(str(user_id or ""))
    if not entree or not entree.get("refresh_token") or not configurable():
        return None
    from google.oauth2.credentials import Credentials
    ident, secret = _client()
    return Credentials(
        token=None,
        refresh_token=entree["refresh_token"],
        token_uri=URL_JETON,
        client_id=ident,
        client_secret=secret,
        scopes=_scopes_pour(entree["email"]),
    )
