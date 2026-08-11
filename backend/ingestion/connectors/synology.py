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
    403: "double authentification (2FA) exigée — renseignez SYNOLOGY_OTP_CODE, "
         "ou créez un compte de service sans 2FA",
    404: "code de double authentification invalide",
    407: "adresse bloquée par le NAS (Auto Block) — débloquez l'IP dans DSM",
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


async def _appel(client, base: str, api: str, method: str, version: int,
                 sid: Optional[str] = None, **params) -> dict:
    """Appel DSM. Lève SynologyError sur `success: false`."""
    p = {"api": api, "method": method, "version": version, **params}
    if sid:
        p["_sid"] = sid
    r = await client.get(f"{base}/webapi/entry.cgi", params=p, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        code = (data.get("error") or {}).get("code", 0)
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


async def _lister_recursif(client, base: str, sid: str, dossier: str,
                           bilan: dict, profondeur: int = 0) -> list[dict]:
    """Fichiers d'un dossier et de ses sous-dossiers (bornés par settings).

    `bilan` accumule ce qui a été ÉCARTÉ pendant le parcours. Sans ça, un fichier
    trop volumineux ou un dossier trop profond disparaîtrait du compte-rendu :
    l'utilisateur croirait tout avoir synchronisé.
    """
    if profondeur > settings.synology_max_depth:
        logger.info("Profondeur maximale atteinte, sous-dossiers de %s ignorés", dossier)
        bilan["dossiers_trop_profonds"] = bilan.get("dossiers_trop_profonds", 0) + 1
        return []

    try:
        data = await _appel(client, base, "SYNO.FileStation.List", "list", 2, sid=sid,
                            folder_path=dossier, additional='["size"]', limit=1000)
    except SynologyError as e:
        logger.warning("Dossier %s illisible (%s)", dossier, e)
        bilan["dossiers_illisibles"] = bilan.get("dossiers_illisibles", 0) + 1
        return []

    fichiers: list[dict] = []
    for item in data.get("files", []):
        if item.get("isdir"):
            fichiers.extend(await _lister_recursif(client, base, sid, item["path"],
                                                   bilan, profondeur + 1))
            continue
        taille = (item.get("additional") or {}).get("size", 0)
        if taille and taille > settings.synology_max_file_mb * 1024 * 1024:
            logger.info("Fichier ignoré (%.1f Mo > %d Mo) : %s",
                        taille / 1024 / 1024, settings.synology_max_file_mb, item["path"])
            bilan["trop_volumineux"] = bilan.get("trop_volumineux", 0) + 1
            continue
        fichiers.append({"path": item["path"], "name": item["name"], "size": taille})
    return fichiers


async def _telecharger(client, base: str, sid: str, chemin: str) -> Optional[bytes]:
    url = (f"{base}/webapi/entry.cgi?api=SYNO.FileStation.Download&version=2"
           f"&method=download&mode=download&_sid={sid}"
           f"&path={quote('[\"' + chemin + '\"]')}")
    try:
        r = await client.get(url, timeout=180)
        r.raise_for_status()
        # DSM renvoie du JSON (et non le fichier) quand l'appel échoue.
        if r.headers.get("content-type", "").startswith("application/json"):
            logger.warning("Téléchargement refusé : %s", chemin)
            return None
        return r.content
    except Exception as e:
        logger.warning("Téléchargement de %s échoué : %s", chemin, e)
        return None


async def sync(dossiers: Optional[list[str]] = None) -> dict:
    """Parcourt les dossiers configurés et ingère les fichiers exploitables.

    Retourne un compte-rendu : fichiers vus, ingérés, ignorés, en erreur.
    """
    import httpx
    from ingestion.parsers import analyser, ligne_en_texte, famille, FichierNonSupporte

    cibles = dossiers or [d.strip() for d in (settings.synology_folders or "").split(",") if d.strip()]
    if not cibles:
        raise NotImplementedError(
            "Aucun dossier à synchroniser : renseignez SYNOLOGY_FOLDERS "
            "(ex. /Chantiers,/Devis) dans le .env."
        )

    # verify=False : les NAS utilisent très souvent un certificat auto-signé.
    # Acceptable ici car la liaison passe par le VPN ou le relais Synology ;
    # à repasser à True dès qu'un certificat valide (Let's Encrypt) est en place.
    async with httpx.AsyncClient(verify=settings.synology_verify_tls, follow_redirects=True) as client:
        base = await _base_url(client)
        sid = await _login(client, base)
        logger.info("Synology : session ouverte")

        try:
            bilan: dict = {}
            fichiers: list[dict] = []
            for dossier in cibles:
                fichiers.extend(await _lister_recursif(client, base, sid, dossier, bilan))

            vus = len(fichiers)
            ingeres = ignores = erreurs = 0

            for f in fichiers:
                if famille(f["name"]) is None:
                    ignores += 1               # format non exploitable (zip, exe, vidéo…)
                    continue

                brut = await _telecharger(client, base, sid, f["path"])
                if not brut:
                    erreurs += 1
                    continue

                try:
                    structure = analyser(f["name"], brut)
                except FichierNonSupporte as e:
                    logger.info("Ignoré (%s) : %s", e, f["path"])
                    ignores += 1
                    continue
                except Exception as e:         # noqa: BLE001 - un fichier ne doit pas tout arrêter
                    logger.warning("Lecture de %s impossible : %s", f["path"], e)
                    erreurs += 1
                    continue

                if structure["kind"] == "tabulaire":
                    texte = "\n\n".join(ligne_en_texte(l) for l in structure["rows"])
                else:
                    texte = structure["text"]
                if not texte or not texte.strip():
                    ignores += 1
                    continue

                # source_id = chemin sur le NAS : stable, donc resynchro idempotente.
                if await ingest_document(
                    text=texte,
                    source_type=settings.synology_source_type,
                    source_id=f"synology:{f['path']}",
                    source_filename=f["name"],
                    access_level=settings.synology_access_level,
                ):
                    ingeres += 1
                else:
                    erreurs += 1

            logger.info("Synology : %d vus, %d ingérés, %d ignorés, %d erreurs %s",
                        vus, ingeres, ignores, erreurs, bilan or "")
            # `bilan` remonte ce qui a été écarté AVANT le téléchargement (taille,
            # profondeur, dossier illisible) : le compte-rendu ne doit pas laisser
            # croire que tout a été traité.
            return {"fichiers": vus, "ingérés": ingeres, "ignorés": ignores,
                    "erreurs": erreurs, **bilan}
        finally:
            await _logout(client, base, sid)
