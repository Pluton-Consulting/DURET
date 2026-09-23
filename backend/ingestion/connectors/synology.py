"""
Connecteur Synology NAS (DSM FileStation) — lecture seule.

IMPORTANT — QuickConnect n'est PAS une API. C'est le service de traversée de NAT
de Synology : `quickconnect.to/<id>` ne fait que RÉSOUDRE une adresse joignable
pour le NAS. L'API réellement utilisée ici est **DSM FileStation**
(`/webapi/entry.cgi`), authentifiée par `SYNO.API.Auth` (login -> sid).

Deux façons de joindre le NAS, par ordre de préférence :

  1. `SYNOLOGY_BASE_URL` — adresse DIRECTE (IP locale, DDNS, ou IP du NAS sur le
     VPN Headscale déjà en place). **Fortement recommandé** : le relais
     QuickConnect est lent, limité en débit et peut couper sur un gros volume.
  2. `SYNOLOGY_QUICKCONNECT_ID` — résolution automatique via le service Synology.
     Pratique quand le NAS n'a pas d'adresse fixe, mais moins fiable.

Le texte des fichiers est extrait par `ingestion.parsers` : on bénéficie donc
d'Excel, Word, CSV, PDF et de l'OCR des scans, exactement comme pour l'import
manuel. L'identifiant d'ingestion est le CHEMIN du fichier : une resynchro
mettra à jour les documents au lieu de les dupliquer.

Sécurité : identifiants uniquement via .env, jamais journalisés. Créer sur le
NAS un compte de service DÉDIÉ, en LECTURE SEULE, restreint aux dossiers utiles.
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import quote

from config import settings
from ingestion.pipeline import ingest_document

logger = logging.getLogger("duret.ingestion.synology")

# Messages DSM utiles : le code brut n'aide personne à diagnostiquer.
_ERREURS = {
    400: "identifiant ou mot de passe incorrect",
    401: "compte désactivé",
    402: "permission refusée",
    403: "double authentification (2FA) exigée. Renseignez SYNOLOGY_OTP_CODE, "
         "ou créez un compte de service sans 2FA",
    404: "code de double authentification invalide",
    407: "adresse bloquée par le NAS (Auto Block). Débloquez l'IP dans DSM",
    408: "mot de passe expiré",
    409: "mot de passe expiré, changement obligatoire",
    410: "mot de passe doit être changé",
    119: "session invalide ou expirée",
}


class SynologyError(RuntimeError):
    """Erreur DSM lisible (jamais de mot de passe dans le message)."""


# Codes COMMUNS à toutes les API DSM (100-119).
_ERREURS_COMMUNES = {
    100: "erreur inconnue",
    101: "paramètre d'API manquant",
    102: "cette API n'existe pas sur ce NAS",
    103: "cette méthode n'existe pas",
    104: "version d'API non supportée par ce NAS",
    105: "la session n'a pas la permission pour cette opération",
    106: "session expirée",
    107: "session interrompue par une connexion en double",
    119: "session invalide (SID introuvable)",
}

# Codes de FILESTATION. Ils RÉUTILISENT la plage 400+ des codes
# d'authentification avec un sens TOTALEMENT DIFFÉRENT : 408 vaut « mot de passe
# expiré » à la connexion et « ce fichier n'existe pas » ici. Traduire avec le
# mauvais dictionnaire produit un message parfaitement crédible et parfaitement
# faux — vécu : « le mot de passe a expiré » alors que le dossier demandé
# n'existait simplement pas, ce qui a envoyé chercher pendant une heure du côté
# des identifiants.
_ERREURS_FICHIERS = {
    400: "paramètre invalide pour cette opération de fichier",
    401: "erreur inconnue de l'opération de fichier",
    402: "système trop occupé",
    403: "cet utilisateur n'a pas le droit d'effectuer cette opération",
    404: "ce groupe n'a pas le droit d'effectuer cette opération",
    405: "utilisateur et groupe sans droit sur cette opération",
    406: "informations de compte illisibles",
    407: "opération non autorisée",
    408: "ce dossier ou fichier N'EXISTE PAS sur le NAS "
         "(vérifiez le nom exact du partage dans File Station)",
    409: "système de fichiers non supporté",
    410: "connexion au système de fichiers distant impossible",
    411: "système de fichiers en lecture seule",
    414: "un fichier de ce nom existe déjà",
    416: "plus d'espace disponible sur le NAS",
    418: "nom ou chemin illégal",
    421: "ressource occupée",
    599: "cette tâche de fichier n'existe pas",
    # Création de dossier et téléversement (17/09) : ces codes tombaient sur « erreur DSM 1805 ».
    1100: "la création du dossier a échoué (droits du compte sur ce dossier, ou nom refusé)",
    1101: "trop de fichiers ou de dossiers dans le dossier parent",
    1800: "taille annoncée et taille reçue différentes (envoi interrompu)",
    1801: "délai dépassé pendant le téléversement",
    1802: "aucun nom de fichier dans l'envoi",
    1803: "téléversement annulé par le serveur",
    1804: "fichier trop volumineux pour ce système de fichiers",
    1805: "un fichier de ce nom existe déjà dans ce dossier (rien n'est jamais écrasé)",
}


def _message(code: int, contexte: str) -> str:
    """Traduit un code DSM avec le dictionnaire de SA famille d'API.

    Le contexte porte le nom de l'API (« SYNO.FileStation.List.list ») : c'est
    lui qui décide du dictionnaire. Sans cette distinction, un code de fichier
    était lu comme un code d'authentification.
    """
    if code in _ERREURS_COMMUNES:
        table = _ERREURS_COMMUNES
    elif "FileStation" in contexte:
        table = _ERREURS_FICHIERS
    else:
        table = _ERREURS
    return f"Synology ({contexte}) : {table.get(code, f'erreur DSM {code}')}"


async def _resoudre_quickconnect(client, qc_id: str) -> Optional[str]:
    """Demande à Synology l'adresse joignable derrière un ID QuickConnect.

    Endpoint public utilisé par les clients Synology. Non documenté
    officiellement : on l'essaie, et on retombe proprement si le format change.
    Renvoie une URL de base, ou None.
    """
    async def _interroger(commande: str) -> dict:
        r = await client.post(
            "https://global.quickconnect.to/Serv.php",
            json={"version": 1, "command": commande,
                  "stop_when_error": False, "stop_when_success": False,
                  "id": "dsm_portal_https", "serverID": qc_id},
            timeout=15,
        )
        return r.json() or {}

    try:
        data = await _interroger("get_server_info")
    except Exception as e:
        logger.warning("Résolution QuickConnect impossible : %s", e)
        return None

    service = data.get("service") or {}
    serveur = data.get("server") or {}

    # LE RELAIS SE DEMANDE, IL NE SE LIT PAS. `get_server_info` décrit le NAS ;
    # il ne rend un `relay_dn` que si un tunnel est DÉJÀ ouvert. Quand il n'y en
    # a pas — cas normal après quelques minutes d'inactivité — il faut en
    # réclamer un avec `request_tunnel`, comme le fait le client Synology.
    #
    # C'est ce qui explique un NAS joignable un jour et injoignable le lendemain
    # sans qu'on ait rien touché : le tunnel de la veille avait expiré. Et le
    # port change à CHAQUE allocation (44591 puis 32418 sur le même NAS), donc
    # une adresse retenue trop longtemps devient fausse d'elle-même.
    if not service.get("relay_dn"):
        try:
            tunnel = await _interroger("request_tunnel")
            if (tunnel.get("service") or {}).get("relay_dn"):
                service = tunnel["service"]
                serveur = tunnel.get("server") or serveur
                logger.info("QuickConnect %s : tunnel de relais demandé et obtenu", qc_id)
        except Exception as e:  # noqa: BLE001 - on gardera les autres candidats
            logger.info("QuickConnect %s : demande de tunnel refusée (%s)", qc_id, e)

    # CHAQUE ADRESSE A SON PROPRE PORT. C'est le piège : appliquer `https_port`
    # (5001, le port INTERNE) à l'adresse publique ou au relais donne des URL
    # qui ne répondront jamais. Observé sur un NAS réel : port interne 5001,
    # port externe 63358, port de relais 41061 — trois valeurs différentes.
    interne = service.get("https_port") or service.get("port") or 5001
    candidats: list[tuple[str, str]] = []

    ddns = (serveur.get("ddns") or "").strip()
    if ddns and ddns.lower() not in ("null", "none"):
        candidats.append(("DDNS", f"https://{ddns}:{interne}"))

    externe = (serveur.get("external") or {}).get("ip")
    if externe:
        candidats.append(("IP publique",
                          f"https://{externe}:{service.get('ext_port') or interne}"))

    # Le RELAIS Synology, celui que les clients officiels empruntent. Il vit dans
    # `relay_dn`/`relay_port` — pas dans `smartdns.host` ni `env.relay_region`,
    # qui ne sont pas des points d'entrée (le premier sert la page HTML, le
    # second n'est qu'un code de région).
    relais, port_relais = service.get("relay_dn"), service.get("relay_port")
    if relais and port_relais:
        candidats.append(("relais", f"https://{relais}:{port_relais}"))

    if not candidats:
        logger.warning("QuickConnect %s : aucune adresse exploitable", qc_id)
        return None

    # ON SONDE, ON NE DEVINE PAS. Classer par « qualité » puis rendre la première
    # sans vérifier menait droit au mur : un NAS derrière une box sans
    # redirection annonce une IP publique parfaitement inatteignable, et l'appel
    # suivant expirait sans que rien n'indique pourquoi.
    for nature, url in candidats:
        try:
            r = await client.get(f"{url}/webapi/query.cgi",
                                 params={"api": "SYNO.API.Info", "version": 1,
                                         "method": "query"},
                                 timeout=8)
            if r.status_code < 400 and (r.json() or {}).get("success"):
                logger.info("QuickConnect %s : %s joignable", qc_id, nature)
                return url
        except Exception:  # noqa: BLE001 - un candidat muet n'est pas une panne
            pass
        logger.info("QuickConnect %s : %s ne répond pas", qc_id, nature)

    logger.warning("QuickConnect %s : aucune des %d adresses ne répond "
                   "(DSM éteint, ou relais indisponible)", qc_id, len(candidats))
    return None


# Adresse résolue, gardée en mémoire. SANS ce cache, chaque appel de skill
# relançait une résolution complète : une requête chez Synology, puis jusqu'à
# trois sondages de 8 s. Deux consequences, et la seconde est la pire : c'était
# lent, et surtout le résolveur de Synology finissait par ne plus répondre —
# d'où un NAS joignable une fois sur deux, sans rien de changé entre les deux.
_CACHE_URL: dict = {"url": None, "expire": 0.0}
DUREE_CACHE_URL_S = 600.0


def oublier_adresse() -> None:
    """Invalide l'adresse mise en cache : le prochain appel la redemandera.

    Appelé quand le NAS cesse de répondre — son adresse a pu changer (bail DHCP,
    relais déplacé). Sans cette invalidation, on s'obstinerait dix minutes sur
    une adresse morte.
    """
    _CACHE_URL.update({"url": None, "expire": 0.0})


async def _base_url(client) -> str:
    """URL de base du NAS : adresse directe si fournie, sinon QuickConnect."""
    import time

    directe = (settings.synology_base_url or "").strip().rstrip("/")

    # Adresse déjà résolue et encore fraîche : on la réutilise. C'est ce qui
    # évite de redemander à Synology à chaque question.
    if not directe and _CACHE_URL["url"] and time.monotonic() < _CACHE_URL["expire"]:
        return _CACHE_URL["url"]

    # PIÈGE COURANT. « https://mon-nas.quickconnect.to » est l'adresse que
    # Synology AFFICHE à l'utilisateur, donc la seule qu'on ait souvent sous la
    # main — mais ce n'est PAS un point d'entrée d'API : cet hôte sert une page
    # HTML dont le JavaScript va, lui, chercher la vraie adresse. Appeler
    # /webapi/entry.cgi dessus rend du HTML, et l'erreur qui en sort n'aide pas.
    #
    # Renseignée ici, elle court-circuiterait en plus la résolution QuickConnect
    # juste en dessous. On en extrait donc l'identifiant et on résout, plutôt que
    # de laisser échouer sur un message incompréhensible.
    if directe and "quickconnect.to" in directe.lower():
        hote = directe.split("//")[-1].split("/")[0]
        identifiant = hote.split(".")[0]
        logger.info("URL QuickConnect donnée comme adresse directe : résolution "
                    "de l'identifiant « %s »", identifiant)
        url = await _resoudre_quickconnect(client, identifiant)
        if url:
            return url
        raise SynologyError(
            f"« {directe} » est l'adresse d'affichage QuickConnect, pas un point "
            f"d'entrée d'API, et l'identifiant « {identifiant} » n'a pas pu être "
            "résolu. Renseignez SYNOLOGY_QUICKCONNECT_ID avec l'identifiant SEUL, "
            "ou mieux SYNOLOGY_BASE_URL avec l'adresse directe du NAS "
            "(https://<ip-du-nas>:5001).")

    if directe:
        return directe

    qc = (settings.synology_quickconnect_id or "").strip()
    if not qc:
        raise NotImplementedError(
            "Synology non configuré : renseignez SYNOLOGY_BASE_URL (recommandé : "
            "l'adresse du NAS sur le VPN ou en DDNS) ou SYNOLOGY_QUICKCONNECT_ID, "
            "plus SYNOLOGY_USER et SYNOLOGY_PASSWORD dans le .env."
        )
    url = await _resoudre_quickconnect(client, qc)
    if not url:
        raise SynologyError(
            f"QuickConnect « {qc} » n'a pas pu être résolu. Le service de "
            "résolution Synology n'a pas répondu, ou le NAS est hors ligne. "
            "Réessayez dans un instant, ou renseignez SYNOLOGY_BASE_URL "
            "(adresse directe du NAS, plus rapide et plus fiable)."
        )
    _CACHE_URL.update({"url": url, "expire": time.monotonic() + DUREE_CACHE_URL_S})
    logger.info("QuickConnect résolu, adresse gardée %d s", int(DUREE_CACHE_URL_S))
    return url


# UNE SESSION MORTE SE ROUVRE, ELLE NE CONDAMNE PAS LA DEMI-HEURE SUIVANTE (17/09).
# Mémoire technique de Noa : « Source distante devenue inaccessible : MEMOIRE Complet
# Vierge.docx » à chaque essai — DSM répondait « session invalide (SID introuvable) »
# et le serveur gardait ce SID partagé jusqu'à son expiration : TOUS les
# téléchargements étaient refusés, alors que le fichier était bien là.
_CODES_SESSION = {105, 106, 107, 119}


async def _nouvelle_session(client, base: str, ancien_sid: Optional[str]) -> Optional[str]:
    """Rouvre une session et la donne à la session PARTAGÉE (nas/acces) si c'est
    bien celle-là qui vient de mourir. Rend le nouveau SID, ou None."""
    try:
        neuf = await _login(client, base)
    except Exception as e:  # noqa: BLE001
        logger.warning("Réouverture de la session du NAS impossible : %s", str(e)[:120])
        return None
    try:
        from nas import acces
        partagee = getattr(acces, "_COURANTE", None)
        if partagee is not None and getattr(partagee, "sid", None) == ancien_sid:
            partagee.sid = neuf
    except Exception:  # noqa: BLE001
        pass
    logger.info("Session du NAS rouverte après un refus de session")
    return neuf


async def _appel(client, base: str, api: str, method: str, version: int,
                 sid: Optional[str] = None, _reessai: bool = False, **params) -> dict:
    """Appel DSM. Lève SynologyError sur `success: false`."""
    p = {"api": api, "method": method, "version": version, **params}
    if sid:
        p["_sid"] = sid
    r = await client.get(f"{base}/webapi/entry.cgi", params=p, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        code = (data.get("error") or {}).get("code", 0)
        if code in _CODES_SESSION and sid and not _reessai and api != "SYNO.API.Auth":
            neuf = await _nouvelle_session(client, base, sid)
            if neuf:
                return await _appel(client, base, api, method, version, sid=neuf, _reessai=True, **params)
        raise SynologyError(_message(code, f"{api}.{method}"))
    return data.get("data") or {}


async def _login(client, base: str) -> str:
    if not settings.synology_user or not settings.synology_password:
        raise NotImplementedError(
            "Synology non configuré : SYNOLOGY_USER et SYNOLOGY_PASSWORD manquants dans le .env."
        )
    params = {
        "account": settings.synology_user,
        "passwd": settings.synology_password,
        "session": "FileStation",
        "format": "sid",
    }
    if settings.synology_otp_code:
        params["otp_code"] = settings.synology_otp_code
    try:
        data = await _appel(client, base, "SYNO.API.Auth", "login", 6, **params)
    except SynologyError as e:
        # UN REFUS D'IDENTIFIANTS APRÈS UNE RÉSOLUTION RÉUSSIE a une signature
        # très particulière : le NAS joint répond, mais ce n'est pas celui où
        # vit ce compte. Un parc avec deux NAS suffit à s'y perdre — le mot de
        # passe « marche pourtant sur le web », parce qu'on l'essaie sur l'autre
        # machine. DSM ne peut pas le dire (son code 400 couvre aussi bien le
        # compte inconnu que le mot de passe faux), donc on le dit ici.
        qc = (settings.synology_quickconnect_id or "").strip()
        if qc and "incorrect" in str(e):
            raise SynologyError(
                f"{e}. Vérifiez aussi que l'identifiant QuickConnect « {qc} » "
                "désigne bien le NAS où existe ce compte : des identifiants "
                "valides sur un AUTRE NAS produisent exactement cette erreur."
            ) from e
        raise
    return data["sid"]


async def _logout(client, base: str, sid: str) -> None:
    try:
        await _appel(client, base, "SYNO.API.Auth", "logout", 1, sid=sid, session="FileStation")
    except Exception:
        pass          # une session non fermée expire d'elle-même


async def _telecharger_ou_raison(client, base: str, sid: str, chemin: str, _reessai: bool = False) -> tuple:
    """(octets, raison). Les octets, ou None ET la raison lisible du refus.

    08/09, 11:40 : « affiche ça <nom exact d'un fichier listé> » → « Fichier
    introuvable ou vide sur le NAS ». Le refus de DSM (un JSON avec son code :
    408 inexistant, 407 non autorisé…) partait dans le journal et le chat ne
    recevait qu'une phrase passe-partout. La raison remonte désormais.
    """
    # Le tableau JSON est formé HORS de la f-string : une barre oblique dans
    # une expression de f-string n'est admise qu'à partir de Python 3.12, et
    # les bancs tournent aussi sur un 3.9.
    chemin_json = quote('["' + chemin + '"]')
    url = (f"{base}/webapi/entry.cgi?api=SYNO.FileStation.Download&version=2"
           f"&method=download&mode=download&_sid={sid}"
           f"&path={chemin_json}")
    try:
        r = await client.get(url, timeout=180)
        r.raise_for_status()
        # DSM renvoie du JSON (et non le fichier) quand l'appel échoue.
        if r.headers.get("content-type", "").startswith("application/json"):
            code = 0
            try:
                code = int(((r.json() or {}).get("error") or {}).get("code") or 0)
            except Exception:  # noqa: BLE001 — JSON illisible : le code reste inconnu
                pass
            if code in _CODES_SESSION and not _reessai:
                neuf = await _nouvelle_session(client, base, sid)
                if neuf:
                    return await _telecharger_ou_raison(client, base, neuf, chemin, _reessai=True)
            raison = _message(code, "SYNO.FileStation.Download.download") if code else "refus sans code"
            logger.warning("Téléchargement refusé : %s (%s)", chemin, raison)
            return None, raison
        if not r.content:
            return None, "le serveur a rendu un fichier VIDE (0 octet)"
        return r.content, ""
    except Exception as e:
        logger.warning("Téléchargement de %s échoué : %s", chemin, e)
        return None, f"le téléchargement a échoué ({type(e).__name__} : {str(e)[:80]})"


async def _telecharger(client, base: str, sid: str, chemin: str) -> Optional[bytes]:
    """Les octets, ou None. Conservée pour la synchronisation et le lot."""
    octets, _ = await _telecharger_ou_raison(client, base, sid, chemin)
    return octets


# ── LA SYNCHRONISATION : ouvrir chaque fichier du NAS, une fois ─────────────
#
# CE QUI ÉTAIT FAUX (11/09, « enrichir le NAS ne marche pas »). La
# synchronisation descendait elle-même `SYNOLOGY_FOLDERS`, dossier par
# dossier, séquentiellement :
#   * une racine FANTÔME (`/Drive`, le vrai partage est `/home/Drive`) rendait
#     « dossier illisible » et zéro fichier, sans que l'écran le dise ;
#   * elle descendait la corbeille `#recycle` et les vignettes `@eaDir` ;
#   * elle s'arrêtait à 6 niveaux et ne lisait que les 1 000 premières
#     entrées d'un dossier ;
#   * elle retéléchargeait et ré-OCRisait TOUT à chaque passage, y compris les
#     photos sans texte, sans jamais dire où elle en était.
# Or le chat a, depuis le 08/09, un CATALOGUE de tout le serveur (`nas.acces`)
# qui règle déjà chacun de ces points. La synchronisation part donc de lui :
# une seule façon de voir le NAS, pas deux qui divergent.

import asyncio as _asyncio
import hashlib as _hashlib

# Quatre fichiers de front : assez pour ne pas attendre le réseau fichier par
# fichier, pas assez pour saturer le NAS ni l'OCR (CPU) du serveur.
SYNC_DE_FRONT = 4
# Le jour, un fichier dont la lecture dépasse une minute est remis à la NUIT
# (comme un scan) au lieu de tenir un lecteur trois minutes ; la nuit, il a ses
# trois minutes.
DELAI_LECTURE_JOUR_S = 60
# Un paquet de fichiers entre deux regards sur l'horloge du palier.
PAQUET = 8
ATTENTE_CHARGE_S = 15
ATTENTE_CHARGE_MAX_S = 600


def _charge() -> float:
    """La charge du serveur rapportée à ses cœurs (1.0 = tous occupés)."""
    import os
    try:
        return os.getloadavg()[0] / float(os.cpu_count() or 1)
    except (OSError, AttributeError):
        return 0.0


def _duree(secondes: float) -> str:
    secondes = int(max(0, secondes))
    h, m = divmod(secondes // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{max(1, m)} min"
# Un fichier pathologique (PDF de 400 pages scanné) ne bloque pas la
# synchronisation : passé ce délai, il est écarté et MÉMORISÉ.
DELAI_LECTURE_S = 180
# La colonne `documents.source_id` fait 255 caractères ; un chemin profond du
# NAS peut dépasser. Au-delà, l'identifiant garde une empreinte stable du
# chemin complet et sa FIN (le nom du fichier reste lisible).
MAX_SOURCE_ID = 255


def _niveau_nas(chemin: str) -> str:
    try:
        from nas.niveaux import niveau
        return niveau(chemin)
    except Exception:  # noqa: BLE001 — sans règles lisibles, le niveau du serveur
        return settings.synology_access_level


def _source_id(chemin: str) -> str:
    """`synology:<chemin>` — stable, donc resynchronisation idempotente."""
    import hashlib
    brut = f"synology:{chemin}"
    if len(brut) <= MAX_SOURCE_ID:
        return brut
    empreinte = hashlib.sha1(chemin.encode("utf-8")).hexdigest()[:16]
    reste = MAX_SOURCE_ID - len("synology:#") - len(empreinte) - 1
    return f"synology:#{empreinte}:{chemin[-reste:]}"


def _mtime(entree: dict):
    """La date de modification du NAS (secondes epoch) en datetime UTC, ou None."""
    from datetime import datetime, timezone
    try:
        v = int(entree.get("modifie") or 0)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(v, tz=timezone.utc) if v > 0 else None


def _inchange(entree: dict, derniere_ingestion) -> bool:
    """Le fichier n'a pas bougé depuis son ingestion. Fonction PURE (banc).
    Sans date d'un côté ou de l'autre, on relit : c'est la relecture qui est
    sans risque."""
    from datetime import timezone
    modifie = _mtime(entree)
    if modifie is None or derniere_ingestion is None:
        return False
    d = (derniere_ingestion if derniere_ingestion.tzinfo
         else derniere_ingestion.replace(tzinfo=timezone.utc))
    return d >= modifie


def _lire_ecartes() -> dict:
    """Les fichiers écartés et pourquoi. La mémoire vit dans le volume des
    documents (`nas/tri.py`) : elle survit au redéploiement, c'est tout son
    intérêt, et s'écrit atomiquement."""
    from nas import tri
    return tri.lire_ecartes()


def _ecrire_ecartes(ecartes: dict) -> None:
    from nas import tri
    tri.ecrire_ecartes(ecartes)


async def _dates_ingerees() -> dict:
    """source_id → date de la dernière ingestion (les morceaux sont réécrits à
    chaque ingestion : `created_at` la date donc). Illisible → tout sera relu."""
    try:
        from database.connection import get_db
        async with get_db() as conn:
            lignes = await conn.fetch(
                "SELECT source_id, MAX(created_at) AS d FROM documents "
                "WHERE source_type = $1 GROUP BY source_id",
                settings.synology_source_type)
        return {l["source_id"]: l["d"] for l in lignes}
    except Exception as e:  # noqa: BLE001
        logger.warning("NAS : dates d'ingestion illisibles (%s) — tout sera relu", e)
        return {}


def _sous(chemin: str, racines: list[str]) -> bool:
    return any(chemin == r or chemin.startswith(r + "/") for r in racines)


async def sync(dossiers: Optional[list[str]] = None, avancer=None,
               budget_s: Optional[float] = None) -> dict:
    """La synchronisation voit TOUT le NAS, même lancée depuis le geste d'un
    profil (« lance l'import des documents » dans le chat) : chaque fichier
    est rangé au niveau de SON dossier, c'est la recherche qui trie ensuite
    (13/09). Sans ceci, la tâche héritait des droits de la personne et les
    dossiers qui lui sont fermés n'étaient jamais importés pour les autres."""
    from security.lecteur import en_systeme
    with en_systeme():
        return await _sync(dossiers, avancer, budget_s)


async def _sync(dossiers: Optional[list[str]] = None, avancer=None,
                budget_s: Optional[float] = None) -> dict:
    """Ouvre chaque fichier lisible du NAS et le range dans la mémoire.

    Les fichiers viennent du CATALOGUE (`nas.acces`) : toutes les racines
    ouvertes, sous-dossiers compris, sans la corbeille. `dossiers` restreint à
    une partie du serveur (essai sur un seul dossier). Incrémentale : un
    fichier inchangé depuis son ingestion n'est pas retéléchargé, un fichier
    sans texte ou trop lent n'est pas retenté tant qu'il ne change pas.

    `avancer(traites, total, etape)` est appelé au fil de l'eau quand le
    routeur en fournit un (la carte de l'écran montre la progression).
    """
    from ingestion.parsers import (analyser, ligne_en_texte, famille, FichierNonSupporte,
                                   OcrReporte, en_lecture)
    from nas import acces
    from nas import tri

    racines = acces.dossiers_autorises()
    if not racines:
        raise NotImplementedError(
            "Aucun dossier à synchroniser : renseignez SYNOLOGY_FOLDERS "
            "(ex. /home/Drive) dans le .env.")
    cibles = [acces.normaliser(d) for d in (dossiers or [])] or racines

    async def _prevenir(traites, total, etape):
        if avancer is None:
            return
        try:
            await avancer(traites, total, etape)
        except Exception as e:  # noqa: BLE001 — un compteur ne casse pas une ingestion
            logger.debug("NAS : avancement non enregistré : %s", e)

    # ÉTAPE 1 / 2 — LE RELEVÉ, DIT PENDANT QU'IL SE FAIT (14/09). Il dure
    # jusqu'à un quart d'heure sur le NAS de l'entreprise, et la carte restait
    # sur « 0 traité(s) » : rien ne se comptait avant l'ouverture des fichiers.
    await _prevenir(0, None, "je relève l'arborescence du NAS · démarrage du parcours")
    # RELEVÉ COMPLET, pas incrémental (18/09) : la synchronisation compare la date de chaque
    # FICHIER à son ingestion, et la date d'un dossier ne bouge pas quand un fichier est
    # modifié en place — un relevé incrémental lui cacherait les fichiers mis à jour.
    entrees, complet = await acces.catalogue_attendu(
        sur_progres=lambda texte: _prevenir(0, None, texte), relire_tout=True)

    # UNE RACINE QUI NE REND RIEN SE DIT. C'est la racine fantôme du .env :
    # silencieuse, elle faisait croire à un NAS vide.
    racines_vides = [r for r in cibles
                     if not any(_sous(str(e.get("chemin") or ""), [r]) for e in entrees)]

    fichiers = [e for e in entrees
                if not e.get("dossier") and e.get("chemin")
                and _sous(str(e["chemin"]), cibles)]
    total = len(fichiers)
    plafond = settings.synology_max_file_mb * 1024 * 1024

    connus = await _dates_ingerees()
    ecartes = _lire_ecartes()
    # UNE REPRISE DEMANDÉE À L'ÉCRAN (16/09, audit D-27) s'applique ici, avant
    # le tri : la synchronisation qui tournait pendant la demande l'aurait écrasée.
    repris = tri.appliquer_reprise(ecartes)
    empreintes = tri.lire_empreintes()
    index_empreintes = tri.index_des_empreintes(empreintes)
    # LE TRI AVANT LA LECTURE (15/09, `nas/tri.py`) : ce que l'administrateur a
    # validé (« à la demande », « ignorer ») n'est pas ouvert ; les photos et ce
    # qui a plus de `nas_tri_age_ans` ans non plus (sauf « toujours apprendre »).
    # Les PDF scannés attendent la nuit : l'OCR de jour a déjà mis l'application
    # à genoux.
    regles_tri, age_max, maintenant = tri.regles(), tri.age_ans(), __import__("time").time()
    index_tri = tri.index_des_regles(regles_tri)
    differes = tri.ocr_differe()
    de_nuit = tri.fenetre_de_nuit()
    bilan = {"format_non_lu": 0, "trop_volumineux": 0, "inchangés": 0,
             "déjà_écartés": 0, "sans_texte": 0, "trop_lents": 0,
             "à_la_demande": 0, "ignorés": 0, "photos": 0, "anciens": 0,
             "scans_remis_à_la_nuit": 0, "copies_possibles": 0, "copies_reconnues": 0,
             "retentés": 0, "repris_à_la_main": repris}
    a_lire = []
    for f in fichiers:
        nom = str(f.get("nom") or f["chemin"].rsplit("/", 1)[-1])
        decision = tri.decision_du_chemin(f["chemin"], regles_tri, index=index_tri)
        if decision == "demande":
            bilan["à_la_demande"] += 1
            continue
        if decision == "ignorer":
            bilan["ignorés"] += 1
            continue
        raison_tri = tri.ecarte_sans_ia(f, maintenant, tri.age_applicable(decision, age_max))
        if raison_tri:
            bilan["photos" if raison_tri == "photo" else "anciens"] += 1
            continue
        if not de_nuit and f["chemin"] in differes and differes[f["chemin"]] == f.get("modifie"):
            bilan["scans_remis_à_la_nuit"] += 1   # déjà repéré : il attend la nuit
            continue
        if famille(nom) is None:
            bilan["format_non_lu"] += 1           # zip, dwg, vidéo… : pas de texte à tirer
            continue
        if int(f.get("octets") or 0) > plafond:
            bilan["trop_volumineux"] += 1
            continue
        if _inchange(f, connus.get(_source_id(f["chemin"]))):
            bilan["inchangés"] += 1
            continue
        deja_ecarte = ecartes.get(f["chemin"])
        if tri.reste_ecarte(deja_ecarte, f.get("modifie"), maintenant):
            bilan["déjà_écartés"] += 1            # écarté, inchangé, son prochain essai n'est pas venu
            continue
        if deja_ecarte is not None and tri.fiche_ecartee(deja_ecarte).get("modifie") == f.get("modifie"):
            bilan["retentés"] += 1                # écarté pour un motif passager : son essai est venu
        a_lire.append((f, nom))
    # Les plus récents d'abord : une synchro interrompue a au moins lu les
    # affaires en cours. Les COPIES POSSIBLES (même nom, même taille qu'un
    # fichier plus récent) passent en dernier : l'original une fois lu, une
    # vraie copie se reconnaît à son empreinte et ne coûte qu'un téléchargement.
    copies = tri.copies_possibles([f for f, _ in a_lire])
    par_date = lambda fn: -float(fn[0].get("modifie") or 0)  # noqa: E731
    originaux = sorted((fn for fn in a_lire if fn[0]["chemin"] not in copies), key=par_date)
    copies_a_lire = sorted((fn for fn in a_lire if fn[0]["chemin"] in copies), key=par_date)
    bilan["copies_possibles"] = len(copies_a_lire)
    a_lire = originaux + copies_a_lire
    # DEUX GROUPES DE PAQUETS, jamais mélangés : quatre fichiers sont lus de
    # front, et une copie logée dans le même paquet que son original serait lue
    # en même temps que lui — elle ne pourrait pas reconnaître un contenu pas
    # encore rangé, et le travail serait fait deux fois.
    lots = ([originaux[i:i + PAQUET] for i in range(0, len(originaux), PAQUET)]
            + [copies_a_lire[i:i + PAQUET] for i in range(0, len(copies_a_lire), PAQUET)])

    logger.info("NAS : %d fichier(s) au catalogue, %d à lire (%s)", total, len(a_lire), bilan)
    # ÉTAPE 2 / 2 — LE TRI, puis l'ouverture : ce qui sera ouvert, et pourquoi
    # le reste ne l'est pas, dit AVANT le premier fichier.
    dans_la_file = ("copies_possibles", "copies_reconnues", "retentés", "repris_à_la_main")
    ecartes_txt = " · ".join(f"{n} {k.replace('_', ' ')}" for k, n in bilan.items()
                             if n and k not in dans_la_file)
    dont = [texte for texte, n in (
        (f"{bilan['copies_possibles']} copie(s) possible(s), lue(s) en dernier", bilan["copies_possibles"]),
        (f"{bilan['retentés']} fichier(s) écarté(s) retenté(s)", bilan["retentés"]),
        (f"{repris} fichier(s) repris à la demande de l'écran", repris)) if n]
    await _prevenir(0, len(a_lire),
                    f"{total} fichiers au catalogue · {len(a_lire)} à ouvrir"
                    + (f" (dont {' ; '.join(dont)})" if dont else "")
                    + (f" · {ecartes_txt}" if ecartes_txt else "")
                    + ("" if a_lire else " · rien de nouveau à ouvrir"))
    compte = {"traites": 0, "ingeres": 0, "erreurs": 0}
    porte = _asyncio.Semaphore(SYNC_DE_FRONT)
    import time as _time
    # OÙ PASSE LE TEMPS, mesuré : réseau du NAS, lecture, écriture en base.
    temps = {"telechargement": 0.0, "lecture": 0.0, "base": 0.0, "n": 0}
    debut_sync = _time.monotonic()
    pause_totale = [0.0]

    def _rythme() -> str:
        """« 12 fichiers/min · reste ~3 h 10 min » — sur le temps de TRAVAIL."""
        travail = max(1.0, _time.monotonic() - debut_sync - pause_totale[0])
        par_min = compte["traites"] / (travail / 60)
        if not compte["traites"]:
            return ""
        reste = len(a_lire) - compte["traites"]
        texte = f" · {par_min:.1f} fichier(s)/min"
        if reste > 0 and par_min > 0:
            texte += f" · reste ~{_duree(reste / par_min * 60)}"
        if temps["n"]:
            n = temps["n"]
            texte += (f" · moyenne : NAS {temps['telechargement'] / n:.1f} s, lecture "
                      f"{temps['lecture'] / n:.1f} s, base {temps['base'] / n:.1f} s")
        return texte

    async def _respirer():
        """Le jour, on n'ajoute pas une lecture à un serveur déjà chargé."""
        if tri.fenetre_de_nuit():
            return
        seuil = float(getattr(settings, "nas_charge_max", 0.75) or 0.75)
        attendu = 0.0
        while _charge() > seuil and attendu < ATTENTE_CHARGE_MAX_S:
            if attendu == 0:
                await _prevenir(compte["traites"], len(a_lire),
                                f"serveur chargé ({_charge():.0%}) : j'attends qu'il se libère · "
                                f"{compte['ingeres']} lu(s)")
            await _asyncio.sleep(ATTENTE_CHARGE_S)
            attendu += ATTENTE_CHARGE_S
        pause_totale[0] += attendu

    def _ecarter(f, raison):
        # Une FICHE, plus une simple date (audit D-27) : le motif, le compte des
        # essais et le prochain — un délai ponctuel n'écarte plus pour toujours.
        ecartes[f["chemin"]] = tri.noter_ecarte(ecartes.get(f["chemin"]), f.get("modifie"),
                                                raison, _time.time())

    async def _un(f, nom):
        async with porte:
            await _respirer()
            try:
                t0 = _time.monotonic()
                async with acces.connexion() as (client, base, sid):
                    brut, raison = await _telecharger_ou_raison(client, base, sid, f["chemin"])
                t1 = _time.monotonic()
                if not brut:
                    compte["erreurs"] += 1
                    logger.info("NAS : %s non téléchargé (%s)", f["chemin"], raison)
                    return
                source_id = _source_id(f["chemin"])
                empreinte = _hashlib.sha256(brut).hexdigest()
                origine = index_empreintes.get(empreinte)
                if origine and origine[0] != source_id:
                    # UNE VRAIE COPIE (16/09, audit D-27) : le même contenu qu'une
                    # source déjà lue. Elle garde SA source, SON nom et SON niveau
                    # d'accès — un même CCTP dans deux affaires ne fusionne pas
                    # leurs droits —, sans relecture ni nouvel embedding.
                    if origine[1] == tri.MOTIF_STABLE:
                        bilan["sans_texte"] += 1
                        bilan["copies_reconnues"] += 1
                        _ecarter(f, tri.MOTIF_STABLE)
                        tri.noter_empreinte(empreintes, index_empreintes, source_id, empreinte,
                                            tri.MOTIF_STABLE)
                        return
                    morceaux = 0
                    try:
                        from ingestion.pipeline import copier_document
                        morceaux = await copier_document(origine[0], settings.synology_source_type,
                                                         source_id, nom, _niveau_nas(f["chemin"]))
                    except Exception as e:  # noqa: BLE001 — une copie ratée se rattrape en relisant
                        logger.info("NAS : copie de %s non reprise (%s) — relecture", f["chemin"], e)
                    if morceaux:
                        compte["ingeres"] += 1
                        bilan["copies_reconnues"] += 1
                        ecartes.pop(f["chemin"], None)
                        differes.pop(f["chemin"], None)
                        tri.noter_empreinte(empreintes, index_empreintes, source_id, empreinte, "ingere")
                        return
                    # L'original n'a plus ses morceaux en base : l'index ne vaut
                    # plus rien pour ce contenu, on relit le fichier.
                    index_empreintes.pop(empreinte, None)
                try:
                    # `en_lecture`, pas `wait_for(to_thread(…))` (15/09) : l'ancienne
                    # forme abandonnait l'attente sans arrêter l'OCR, et les lectures
                    # fantômes ont occupé tout le serveur (voir `parsers.en_lecture`).
                    nuit = tri.fenetre_de_nuit()
                    structure = await en_lecture(analyser, nom, brut,
                                                 delai=DELAI_LECTURE_S if nuit else DELAI_LECTURE_JOUR_S,
                                                 ocr=nuit)
                    t2 = _time.monotonic()
                    differes.pop(f["chemin"], None)
                except OcrReporte:
                    bilan["scans_remis_à_la_nuit"] += 1
                    differes[f["chemin"]] = f.get("modifie")
                    return
                except (_asyncio.TimeoutError, TimeoutError):
                    if not nuit:
                        # Le jour, un fichier lourd attend la nuit : il n'est pas perdu.
                        bilan["lourds_remis_à_la_nuit"] = bilan.get("lourds_remis_à_la_nuit", 0) + 1
                        differes[f["chemin"]] = f.get("modifie")
                        return
                    bilan["trop_lents"] += 1
                    _ecarter(f, "trop_lent")
                    return
                except FichierNonSupporte:
                    bilan["sans_texte"] += 1          # image sans texte, PDF vide…
                    _ecarter(f, tri.MOTIF_STABLE)
                    tri.noter_empreinte(empreintes, index_empreintes, source_id, empreinte, tri.MOTIF_STABLE)
                    return
                if structure["kind"] == "tabulaire":
                    texte = "\n\n".join(ligne_en_texte(l) for l in structure["rows"])
                else:
                    texte = structure.get("text") or ""
                if not texte.strip():
                    bilan["sans_texte"] += 1
                    _ecarter(f, tri.MOTIF_STABLE)
                    tri.noter_empreinte(empreintes, index_empreintes, source_id, empreinte, tri.MOTIF_STABLE)
                    return
                if await ingest_document(
                        text=texte, source_type=settings.synology_source_type,
                        source_id=source_id, source_filename=nom,
                        # Le niveau de SON dossier (Paramètres, 13/09), plus un
                        # niveau unique pour tout le serveur.
                        access_level=_niveau_nas(f["chemin"])):
                    compte["ingeres"] += 1
                    ecartes.pop(f["chemin"], None)
                    tri.noter_empreinte(empreintes, index_empreintes, source_id, empreinte, "ingere")
                else:
                    compte["erreurs"] += 1
                temps["telechargement"] += t1 - t0
                temps["lecture"] += t2 - t1
                temps["base"] += _time.monotonic() - t2
                temps["n"] += 1
            except Exception as e:  # noqa: BLE001 — un fichier ne doit pas tout arrêter
                compte["erreurs"] += 1
                logger.warning("NAS : lecture de %s impossible : %s", f["chemin"], e)
            finally:
                compte["traites"] += 1
                await _prevenir(compte["traites"], len(a_lire),
                                f"j'ouvre {nom[:60]} · {compte['ingeres']} lu(s), "
                                f"{compte['erreurs']} en échec, "
                                f"{bilan['sans_texte'] + bilan['trop_lents']} sans texte"
                                + _rythme())

    try:
        # Par paquets : la mémoire des écartés est écrite au fil de l'eau — un
        # redémarrage au milieu ne fait pas tout reperdre.
        # PAR PALIERS : `nas_palier_minutes` de travail, puis `nas_pause_minutes`
        # de souffle (le jour seulement). La reprise continue où elle en était ;
        # un redémarrage entre deux paliers ne perd rien (lecture incrémentale).
        palier_s = max(1, int(getattr(settings, "nas_palier_minutes", 10) or 10)) * 60
        pause_s = max(0, int(getattr(settings, "nas_pause_minutes", 3) or 0)) * 60
        debut_palier, palier, faits = _time.monotonic(), 1, 0
        for lot in lots:
            await _asyncio.gather(*[_un(f, nom) for f, nom in lot])
            faits += len(lot)
            _ecrire_ecartes(ecartes)
            tri.ecrire_ocr_differe(differes)
            tri.ecrire_empreintes(empreintes)
            reste = len(a_lire) - faits
            # UN PALIER AUTOMATIQUE S'ARRÊTE À SON TEMPS (`budget_s`) : ce qui est
            # lu est déjà rangé en base, la suite viendra au palier suivant.
            if budget_s and reste > 0 and _time.monotonic() - debut_sync >= budget_s:
                bilan["reste_a_lire"] = reste
                break
            if (reste > 0 and pause_s and not tri.fenetre_de_nuit()
                    and _time.monotonic() - debut_palier >= palier_s):
                reprise = __import__("datetime").datetime.now() + __import__("datetime").timedelta(seconds=pause_s)
                await _prevenir(compte["traites"], len(a_lire),
                                f"palier {palier} terminé · {compte['ingeres']} lu(s) · pause de "
                                f"{pause_s // 60} min pour laisser le serveur au chat, reprise vers "
                                f"{reprise:%H:%M}" + _rythme())
                logger.info("NAS : palier %d terminé (%d traités), pause %d s", palier,
                            compte["traites"], pause_s)
                await _asyncio.sleep(pause_s)
                pause_totale[0] += pause_s
                debut_palier, palier = _time.monotonic(), palier + 1
    finally:
        # Un fichier DISPARU du NAS quitte les listes — mais seulement sur un
        # relevé COMPLET de tout le serveur (16/09, audit D-27) : un parcours
        # interrompu, ou restreint à un dossier, ne prouve aucune disparition.
        # (Avant, un essai sur un seul dossier vidait la liste de la nuit.)
        if complet and not dossiers:
            presents = {f["chemin"] for f in fichiers}
            sources_presentes = {_source_id(c) for c in presents}
            differes = {c: m for c, m in differes.items() if c in presents}
            ecartes = {c: v for c, v in ecartes.items() if c in presents}
            empreintes = {sid: v for sid, v in empreintes.items() if sid in sources_presentes}
        _ecrire_ecartes(ecartes)
        tri.ecrire_ocr_differe(differes)
        tri.ecrire_empreintes(empreintes)

    resultat = {"fichiers": total, "ouverts": compte["traites"],
                "ingérés": compte["ingeres"], "erreurs": compte["erreurs"],
                **{k: v for k, v in bilan.items() if v}}
    if temps["n"]:
        resultat["temps_moyen_s"] = {k: round(temps[k] / temps["n"], 2)
                                     for k in ("telechargement", "lecture", "base")}
    if bilan.get("reste_a_lire"):
        resultat["palier"] = True
        resultat["arret_anticipe"] = True
        resultat["raison_partielle"] = (
            f"palier terminé : {compte['ingeres']} fichier(s) intégré(s) en "
            f"{_duree(budget_s or 0)}, {bilan['reste_a_lire']} restent — la suite au "
            "prochain palier automatique")
    if racines_vides:
        resultat["racines_introuvables"] = ", ".join(racines_vides)
    if not complet:
        # Le catalogue s'est arrêté avant la fin (plafond de temps ou de
        # dossiers) : une partie du serveur n'a pas été vue. Dire « terminée »
        # là-dessus mentirait — l'écran affichera « Partielle ».
        resultat["arret_anticipe"] = True
        resultat["raison_partielle"] = ("le relevé du NAS s'est arrêté avant la fin (plafond de "
                                        "temps ou de dossiers) : une partie du serveur n'a pas "
                                        "été vue — relancer pour continuer")
    logger.info("NAS : synchronisation — %s", resultat)
    return resultat
