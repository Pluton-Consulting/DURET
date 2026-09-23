"""
Client des API juridiques de l'État servies par le portail PISTE (DILA et Cour
de cassation) : Légifrance (textes en vigueur) et Judilibre (jurisprudence).

POURQUOI CES API ET PAS LE WEB. Une question de droit du BTP (décennale,
sous-traitance, retards de paiement, droit du travail) cherchée sur le web
rend des sites de vulgarisation, souvent périmés : un article cité de mémoire
ou recopié d'un blog peut avoir été modifié depuis. Légifrance donne la
version EN VIGUEUR avec sa date, Judilibre la décision elle-même : ce sont les
seules sources qu'on peut citer sans les vérifier ailleurs. Et elles sont
gratuites.

AUTHENTIFICATION. OAuth2 « client credentials » : un identifiant et un secret
créés dans une application du portail piste.gouv.fr, à laquelle on a SOUSCRIT
les deux API (sans la souscription, le jeton est délivré mais chaque appel rend
403 — c'est le piège le plus fréquent, d'où un message qui le nomme). Le jeton
vit une heure : on le garde en mémoire jusqu'à une minute avant son échéance,
pour ne pas payer un aller-retour d'authentification à chaque question.

LES IDENTIFIANTS passent par `llm.cles.valeur` (Paramètres → Clés API d'abord,
`.env` ensuite), comme toutes les clés de l'application. Le secret n'apparaît
JAMAIS dans un journal ni dans un message : les erreurs rendues au modèle et à
l'écran sont écrites ici, en français, et toute chaîne venue de l'extérieur est
nettoyée du secret avant de sortir (`_sans_secret`).

L'ENVIRONNEMENT (« production » par défaut, « sandbox » possible) est réglable :
PISTE délivre des identifiants DIFFÉRENTS pour le bac à sable, et un identifiant
de bac à sable présenté à la production est refusé — le message le rappelle.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("duret.outils.piste")

ENVIRONNEMENTS = {
    "production": ("https://oauth.piste.gouv.fr/api/oauth/token",
                   "https://api.piste.gouv.fr"),
    "sandbox": ("https://sandbox-oauth.piste.gouv.fr/api/oauth/token",
                "https://sandbox-api.piste.gouv.fr"),
}
LEGIFRANCE = "/dila/legifrance/lf-engine-app"
JUDILIBRE = "/cassation/judilibre/v1.0"

# Délais bornés : une API de l'État lente ne doit pas geler un tour de chat.
# 30 s couvrent une recherche plein texte Légifrance chargée ; au-delà, on le
# dit plutôt que d'attendre le plafond du tour.
DELAI_CONNEXION_S = 10.0
DELAI_TOTAL_S = 30.0
# Marge avant l'échéance du jeton : un jeton qui expire PENDANT l'appel rend
# 401, et ce 401 ressemblerait à des identifiants refusés.
MARGE_JETON_S = 60

CHEMIN_PARAMETRES = "Paramètres → Clés API"


class PisteErreur(Exception):
    """Échec d'un appel PISTE, avec un message déjà écrit pour la personne.

    `statut` garde le code HTTP (0 hors HTTP) : l'appelant peut décider de
    retenter autrement (une facette refusée en 400/500) sans analyser le texte.
    """

    def __init__(self, message: str, statut: int = 0):
        super().__init__(message)
        self.statut = statut


# ── Identifiants ─────────────────────────────────────────────────────

def _cle(nom: str) -> str:
    try:
        from llm.cles import valeur
        return str(valeur(nom) or "").strip()
    except Exception as e:  # noqa: BLE001 - sans la couche des clés, on dit « non configuré »
        logger.debug("Lecture de la clé %s impossible (%s)", nom, type(e).__name__)
        return ""


def environnement() -> str:
    brut = _cle("piste_environnement").lower()
    if brut in ("sandbox", "bac a sable", "bac à sable", "test", "essai"):
        return "sandbox"
    return "production"


def identifiants() -> tuple[str, str, str]:
    """(identifiant, secret, environnement) — lève PisteErreur s'il en manque un.

    Levée AVANT tout appel réseau : sans identifiants, il n'y a rien à tenter,
    et un appel sans secret rendrait une erreur d'OAuth incompréhensible.
    """
    client_id = _cle("piste_client_id")
    secret = _cle("piste_client_secret")
    env = environnement()
    if not client_id or not secret:
        manque = " et ".join(n for n, v in (("l'identifiant", client_id),
                                            ("le secret", secret)) if not v)
        raise PisteErreur(
            "Les API juridiques de l'État (Légifrance, Judilibre) ne sont pas encore "
            f"branchées : {manque} PISTE manque(nt). Un administrateur doit les saisir "
            f"dans {CHEMIN_PARAMETRES} (application créée sur piste.gouv.fr, avec les "
            "API Légifrance et Judilibre souscrites).")
    return client_id, secret, env


def _sans_secret(texte: str, *secrets: str) -> str:
    """Retire tout secret connu d'une chaîne venue de l'extérieur, et la borne."""
    t = str(texte or "")
    for s in secrets:
        if s and len(s) >= 4:
            t = t.replace(s, "•••")
    return t[:300]


# ── Client HTTP ──────────────────────────────────────────────────────

def fabrique_client():
    """Un client httpx borné. Point de substitution unique pour les bancs.

    httpx est importé ICI et pas en tête de module : le module reste
    importable (et le catalogue des skills entier avec lui) là où httpx
    manquerait, et le banc remplace cette fonction sans toucher au réseau.
    """
    import httpx
    return httpx.AsyncClient(timeout=httpx.Timeout(DELAI_TOTAL_S, connect=DELAI_CONNEXION_S))


def _est_delai(e: BaseException) -> bool:
    nom = type(e).__name__
    return "Timeout" in nom or isinstance(e, asyncio.TimeoutError)


def _message_statut(statut: int, api: str) -> str:
    if statut == 401:
        return (f"PISTE a refusé les identifiants pour {api} (401). Vérifiez l'identifiant "
                f"et le secret dans {CHEMIN_PARAMETRES}, et qu'ils correspondent à "
                "l'environnement choisi (production ou bac à sable : les identifiants "
                "diffèrent).")
    if statut == 403:
        return (f"Accès refusé à {api} (403) : l'application PISTE n'a probablement pas "
                "souscrit cette API, ou ses conditions d'utilisation n'ont pas été "
                "acceptées. Sur piste.gouv.fr, ouvrez l'application et cochez "
                f"l'API {api}.")
    if statut == 404:
        return f"{api} ne connaît pas ce document (404) : l'identifiant ou le numéro est inexact."
    if statut == 429:
        return (f"Quota de {api} atteint (429) : trop de requêtes en peu de temps. "
                "Réessayez dans une minute.")
    if statut >= 500:
        return f"{api} est indisponible pour le moment (erreur {statut} du service de l'État)."
    return f"{api} a refusé la requête (erreur {statut})."


# ── Jeton OAuth, gardé jusqu'à son échéance ─────────────────────────

# Clé = (environnement, empreinte de l'identifiant) : changer d'identifiant
# dans Paramètres ne doit pas resservir le jeton de l'ancien. L'empreinte
# évite de garder l'identifiant lui-même comme clé d'un dictionnaire global.
_JETONS: dict[tuple[str, str], tuple[str, float]] = {}
_VERROU: Optional[asyncio.Lock] = None


def _empreinte(client_id: str) -> str:
    return hashlib.sha256(client_id.encode()).hexdigest()[:16]


def oublier_jetons() -> None:
    """Vide le cache (bancs, ou après un 401 : le jeton a pu être révoqué)."""
    _JETONS.clear()


async def jeton(forcer: bool = False) -> tuple[str, str]:
    """(jeton d'accès, environnement). Un seul appel OAuth tant qu'il est valide."""
    global _VERROU
    client_id, secret, env = identifiants()
    cle = (env, _empreinte(client_id))
    garde = _JETONS.get(cle)
    if garde and not forcer and time.monotonic() < garde[1]:
        return garde[0], env
    if _VERROU is None:
        _VERROU = asyncio.Lock()
    # Le verrou évite que trois questions arrivées ensemble demandent trois
    # jetons : la deuxième relit celui que la première vient d'obtenir.
    async with _VERROU:
        garde = _JETONS.get(cle)
        if garde and not forcer and time.monotonic() < garde[1]:
            return garde[0], env
        url_jeton = ENVIRONNEMENTS[env][0]
        donnees = {"grant_type": "client_credentials", "client_id": client_id,
                   "client_secret": secret, "scope": "openid"}
        try:
            async with fabrique_client() as client:
                rep = await client.post(url_jeton, data=donnees,
                                        headers={"Accept": "application/json"})
        except Exception as e:  # noqa: BLE001 - toute panne réseau devient un message clair
            if _est_delai(e):
                raise PisteErreur("Le serveur d'authentification PISTE n'a pas répondu à "
                                  "temps. Réessayez dans un instant.") from None
            logger.warning("PISTE : authentification impossible (%s)", type(e).__name__)
            raise PisteErreur("Le serveur d'authentification PISTE est injoignable.") from None
        statut = int(getattr(rep, "status_code", 0) or 0)
        if statut != 200:
            code = ""
            try:
                code = str((rep.json() or {}).get("error") or "")
            except Exception:  # noqa: BLE001 - corps illisible : le statut suffit
                code = ""
            logger.warning("PISTE : jeton refusé (HTTP %s, %s, env=%s)", statut,
                           _sans_secret(code, secret, client_id), env)
            if statut in (400, 401, 403):
                raise PisteErreur(
                    "PISTE a refusé l'identifiant ou le secret (authentification "
                    f"« {_sans_secret(code, secret, client_id) or statut} »). Vérifiez-les "
                    f"dans {CHEMIN_PARAMETRES}, ainsi que l'environnement (production ou "
                    "bac à sable : les identifiants diffèrent).", statut)
            raise PisteErreur(_message_statut(statut, "l'authentification PISTE"), statut)
        try:
            corps = rep.json() or {}
            acces = str(corps["access_token"])
            duree = int(corps.get("expires_in") or 3600)
        except Exception:  # noqa: BLE001
            raise PisteErreur("PISTE a répondu sans jeton d'accès exploitable.") from None
        _JETONS[cle] = (acces, time.monotonic() + max(30, duree - MARGE_JETON_S))
        logger.info("PISTE : jeton obtenu (env=%s, valable %d s)", env, duree)
        return acces, env


# ── Appels ───────────────────────────────────────────────────────────

async def _appel(api: str, methode: str, chemin: str, *, corps: Any = None,
                 params: Optional[dict] = None) -> Any:
    base = LEGIFRANCE if api == "Légifrance" else JUDILIBRE
    for essai in (1, 2):
        acces, env = await jeton(forcer=(essai == 2))
        url = ENVIRONNEMENTS[env][1] + base + chemin
        entetes = {"Authorization": f"Bearer {acces}", "Accept": "application/json"}
        try:
            async with fabrique_client() as client:
                if methode == "POST":
                    rep = await client.post(url, json=corps, headers=entetes)
                else:
                    rep = await client.get(url, params=params, headers=entetes)
        except Exception as e:  # noqa: BLE001
            if _est_delai(e):
                raise PisteErreur(f"{api} n'a pas répondu dans les {int(DELAI_TOTAL_S)} s. "
                                  "Réessayez, ou resserrez la recherche.") from None
            logger.warning("PISTE %s %s : %s", api, chemin, type(e).__name__)
            raise PisteErreur(f"{api} est injoignable pour le moment.") from None
        statut = int(getattr(rep, "status_code", 0) or 0)
        # Un 401 sur l'API alors que le jeton était en cache : il a pu être
        # révoqué ou expirer plus tôt que prévu. UN nouvel essai avec un jeton
        # neuf ; si le second échoue aussi, ce sont bien les identifiants.
        if statut == 401 and essai == 1:
            oublier_jetons()
            continue
        if statut != 200:
            logger.warning("PISTE %s %s : HTTP %s (env=%s)", api, chemin, statut, env)
            raise PisteErreur(_message_statut(statut, api), statut)
        try:
            return rep.json()
        except Exception:  # noqa: BLE001
            raise PisteErreur(f"{api} a rendu une réponse illisible.") from None
    raise PisteErreur(_message_statut(401, api), 401)  # pragma: no cover - borne de la boucle


async def legifrance(chemin: str, corps: dict) -> Any:
    """POST JSON sur l'API Légifrance (lf-engine-app)."""
    return await _appel("Légifrance", "POST", chemin, corps=corps)


async def judilibre(chemin: str, params: dict) -> Any:
    """GET sur l'API Judilibre (paramètres en chaîne de requête, listes répétées)."""
    propres = {k: v for k, v in (params or {}).items() if v not in (None, "", [])}
    return await _appel("Judilibre", "GET", chemin, params=propres)
