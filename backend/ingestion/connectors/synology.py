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


def _message(code: int, contexte: str) -> str:
    return f"Synology ({contexte}) : {_ERREURS.get(code, f'erreur DSM {code}')}"


async def _resoudre_quickconnect(client, qc_id: str) -> Optional[str]:
    """Demande à Synology l'adresse joignable derrière un ID QuickConnect.

    Endpoint public utilisé par les clients Synology. Non documenté
    officiellement : on l'essaie, et on retombe proprement si le format change.
    Renvoie une URL de base, ou None.
    """
    try:
        r = await client.post(
            "https://global.quickconnect.to/Serv.php",
            json={"version": 1, "command": "get_server_info",
                  "stop_when_error": False, "stop_when_success": False,
                  "id": "dsm_portal_https", "serverID": qc_id},
            timeout=15,
        )
        data = r.json()
    except Exception as e:
        logger.warning("Résolution QuickConnect impossible : %s", e)
        return None

    service = (data.get("service") or {})
    port = service.get("https_port") or service.get("port") or 5001

    # Par ordre de qualité : DDNS/hôte externe, puis IP externe, puis relais.
    serveur = data.get("server") or {}
    hote = (serveur.get("ddns") or "").strip()
    if hote and hote.lower() not in ("null", "none"):
        return f"https://{hote}:{port}"

    externe = (serveur.get("external") or {}).get("ip")
    if externe:
        return f"https://{externe}:{port}"

    relais = data.get("env", {}).get("relay_region") or data.get("smartdns", {}).get("host")
    if relais:
        return f"https://{relais}:{port}"

    logger.warning("QuickConnect %s : aucune adresse exploitable dans la réponse", qc_id)
    return None


async def _base_url(client) -> str:
    """URL de base du NAS : adresse directe si fournie, sinon QuickConnect."""
    directe = (settings.synology_base_url or "").strip().rstrip("/")
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
            f"QuickConnect « {qc} » n'a pas pu être résolu. Renseignez plutôt "
            "SYNOLOGY_BASE_URL (adresse directe du NAS)."
        )
    logger.info("QuickConnect résolu vers une adresse directe")
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
    data = await _appel(client, base, "SYNO.API.Auth", "login", 6, **params)
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
