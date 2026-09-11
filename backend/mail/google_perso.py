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


def _scopes_pour(email: str) -> list[str]:
    """Les droits à demander au rafraîchissement : ceux accordés, sinon ceux
    d'avant l'agenda (un compte relié sans trace de ses droits les avait)."""
    return _SCOPES_PAR_EMAIL.get(_normaliser(email)) or list(SCOPES_HISTORIQUES)


def _redirect_uri() -> str:
    # L'API vit derrière le même domaine que l'écran : c'est le navigateur de
    # l'utilisateur qui suit cette redirection, Google n'a pas besoin de
    # joindre le serveur — le VPN ne gêne donc pas.
    return settings.app_url.rstrip("/") + "/api/google/retour"


def lien_autorisation(user_id: str, compte: Optional[str] = None) -> str:
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
    state = create_access_token({"sub": str(user_id), "usage": USAGE_STATE},
                                expires_delta=timedelta(minutes=10))
    params = {
        "client_id": _client()[0],
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
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


def verifier_state(state: str) -> str:
    """L'identifiant d'utilisateur porté par un state valide — lève sinon."""
    from auth.jwt_handler import decode_access_token
    donnees = decode_access_token(state)
    if not isinstance(donnees, dict) or donnees.get("usage") != USAGE_STATE:
        raise ValueError("state OAuth invalide")
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


async def enregistrer(user_id: str, email: str, refresh_token: str, scopes: str) -> None:
    """Retient (ou remplace) la connexion de cet utilisateur, cache compris."""
    from database.connection import get_db
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO connexions_google (user_id, email, refresh_token, scopes)
               VALUES ($1::uuid, $2, $3, $4)
               ON CONFLICT (user_id) DO UPDATE
                   SET email = $2, refresh_token = $3, scopes = $4, maj_le = NOW()""",
            user_id, _normaliser(email), refresh_token, scopes or "")
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
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(URL_REVOCATION, params={"token": jeton})
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
    _CACHE = {_normaliser(l["email"]): l["refresh_token"] for l in lignes}
    _SCOPES_PAR_EMAIL = {_normaliser(l["email"]): _scopes_accordes(l["scopes"]) for l in lignes}
    _PAR_USER = {str(l["user_id"]): {"email": _normaliser(l["email"]),
                                     "refresh_token": l["refresh_token"]}
                 for l in lignes}
    _CACHE_QUAND = time.monotonic()
    logger.info("Connexions Google : %d boîte(s) reliée(s)", len(_CACHE))


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
