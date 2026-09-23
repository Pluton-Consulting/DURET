"""
L'EXPLORATEUR DU NAS DANS LE TABLEAU DE BORD (23/09, Duret).

Demande de Noa : naviguer dans le serveur de fichiers directement depuis
l'application, en comparant deux options — un explorateur refait ici (ces
routes), et le site Synology officiel affiché dans un cadre (`/acces` ne fait
qu'en donner l'adresse). RÉSERVÉ AU SUPER_ADMIN le temps de la comparaison :
toute route répond 403 aux autres rôles, quel que soit l'écran.

RIEN DE NEUF CÔTÉ NAS : on réutilise les gestes de l'assistant, avec leurs
garde-fous — confinement aux dossiers ouverts (`nas.acces.verifier`), niveau
d'accès par dossier selon le rôle (`security.lecteur.au_nom_de`), catalogue
pour la recherche par nom. Un fichier ouvert se LIT EN FLUX (`/lien`, `/fichier`) :
il traverse le serveur sans jamais s'y poser. Aucun appel au modèle ; les seules
écritures sur le NAS sont la création d'un dossier et le dépôt d'un fichier.
"""
from __future__ import annotations

import logging
import posixpath
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from security.audit import log_action

logger = logging.getLogger("duret.routers.nas_explorateur")
router = APIRouter()


def _exiger(user: User) -> None:
    if (getattr(user, "role", "") or "").strip().lower() != "super_admin":
        raise HTTPException(status_code=403, detail="Réservé au super administrateur.")


def _refus(e: Exception) -> HTTPException:
    """Un refus du NAS se DIT (chemin hors périmètre, serveur injoignable)."""
    from nas.acces import NasIndisponible, NasRefuse
    if isinstance(e, HTTPException):
        return e
    if isinstance(e, NasRefuse):
        return HTTPException(status_code=403, detail=str(e) or "Chemin non autorisé.")
    if isinstance(e, NasIndisponible):
        return HTTPException(status_code=503, detail=str(e) or "Le NAS ne répond pas.")
    logger.warning("Explorateur NAS : %s", e)
    return HTTPException(status_code=502, detail=f"Le NAS n'a pas pu répondre ({type(e).__name__}).")


def _adresse_dsm() -> Optional[str]:
    """L'adresse du site Synology : l'adresse directe si elle est configurée,
    sinon QuickConnect."""
    from config import settings
    directe = (getattr(settings, "synology_base_url", None) or "").strip().rstrip("/")
    if directe:
        return directe + "/"
    qc = (getattr(settings, "synology_quickconnect_id", None) or "").strip()
    return f"https://{qc}.quickconnect.to/" if qc else None


@router.get("/acces")
async def acces(current_user: User = Depends(get_current_user)):
    """Sonde de l'écran : 200 = le composant s'affiche, 403 = rien."""
    _exiger(current_user)
    from nas.acces import dossiers_autorises
    return {"explorateur": bool(dossiers_autorises()), "dsm": _adresse_dsm()}


def _trier(entrees: list[dict]) -> list[dict]:
    return sorted(entrees, key=lambda e: (not e.get("dossier"), str(e.get("nom") or "").lower()))


@router.get("/lister")
async def lister(chemin: Optional[str] = Query(None), current_user: User = Depends(get_current_user)):
    """Le contenu d'un dossier, TOUTES ses entrées ; sans chemin, les racines ouvertes."""
    _exiger(current_user)
    from nas.acces import connexion, dossiers_autorises, _lister_ouvert
    from security.lecteur import au_nom_de
    if not (chemin or "").strip():
        racines = dossiers_autorises()
        return {"chemin": None, "total": len(racines), "racines": True,
                "entrees": [{"nom": posixpath.basename(r) or r, "chemin": r, "dossier": True}
                            for r in racines]}
    try:
        with au_nom_de(current_user):
            async with connexion() as (client, base, sid):
                lu = await _lister_ouvert(client, base, sid, chemin, tout=True)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    return {"chemin": lu["chemin"], "total": lu["total"], "entrees": _trier(lu["entrees"])}


@router.get("/chercher")
async def chercher(motif: str = Query(..., min_length=2), dossier: Optional[str] = Query(None),
                   current_user: User = Depends(get_current_user)):
    """Recherche par NOM (catalogue du NAS), dans un dossier ou partout."""
    _exiger(current_user)
    from outils.nas import chercher as chercher_nas
    from security.lecteur import au_nom_de
    try:
        with au_nom_de(current_user):
            trouve = await chercher_nas(motif.strip(), (dossier or "").strip() or None)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    resultats = [{"nom": r.get("nom"), "chemin": r.get("chemin"), "dossier": bool(r.get("dossier")),
                  "octets": r.get("octets"), "modifie": r.get("modifie")}
                 for r in (trouve.get("resultats") or [])]
    return {"motif": motif, "total": trouve.get("nombre", len(resultats)),
            "partiel": "INTERROMPU" in str(trouve.get("note") or ""),
            "resultats": resultats}


# ── ÉCRIRE DEPUIS L'ONGLET FICHIERS (23/09) ─────────────────────────────────
# Deux gestes d'écriture, ceux que le NAS sait faire SANS RIEN PERDRE : créer un
# dossier (jamais en cascade, jamais par-dessus un fichier) et déposer un fichier
# (jamais d'écrasement). Renommer, déplacer, supprimer ne sont PAS proposés ici :
# l'écran donne le chemin à copier pour le faire dans l'explorateur de fichiers
# de l'ordinateur, là où la corbeille et l'annulation existent. Chaque écriture
# est tracée, avec le chemin, dans le journal.
TAILLE_MAX_DEPOT = 95 * 1024 * 1024


class CreerDossierBody(BaseModel):
    parent: str
    nom: str


@router.post("/creer-dossier")
async def creer_dossier(body: CreerDossierBody, current_user: User = Depends(get_current_user)):
    _exiger(current_user)
    from nas.acces import creer_dossier as creer
    from security.lecteur import au_nom_de
    try:
        with au_nom_de(current_user):
            r = await creer(body.parent, body.nom)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    await log_action(action="nas_explorateur_dossier", user_id=str(current_user.id),
                     success=bool(r.get("cree") or r.get("existait")),
                     metadata={"parent": body.parent[:300], "nom": body.nom[:120], "cree": bool(r.get("cree"))})
    return r


@router.post("/deposer")
async def deposer(dossier: str = Form(...), fichier: UploadFile = File(...),
                  current_user: User = Depends(get_current_user)):
    _exiger(current_user)
    from nas.acces import deposer as deposer_nas
    from security.lecteur import au_nom_de
    contenu = await fichier.read(TAILLE_MAX_DEPOT + 1)
    if len(contenu) > TAILLE_MAX_DEPOT:
        raise HTTPException(status_code=413, detail=(
            f"« {fichier.filename} » dépasse {TAILLE_MAX_DEPOT // (1024 * 1024)} Mo : déposez-le depuis "
            f"l'explorateur de fichiers de l'ordinateur, dans {dossier}."))
    try:
        with au_nom_de(current_user):
            r = await deposer_nas(dossier, fichier.filename or "fichier", contenu)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    await log_action(action="nas_explorateur_depot", user_id=str(current_user.id), success=bool(r.get("depose")),
                     metadata={"dossier": dossier[:300], "nom": (fichier.filename or "")[:160], "octets": len(contenu)})
    return r


# ── LIRE UN FICHIER EN FLUX, SANS LE COPIER (23/09, relevé de Noa) ──────────
# « Il n'affiche pas toutes les pages des PDF, un gros fichier c'est long, et il ne
# doit pas télécharger tout le NAS sur le serveur, ça va vite saturer. » `/ouvrir`
# téléchargeait le fichier ENTIER du NAS, l'écrivait dans l'atelier (jamais purgé
# avec la rétention par défaut), puis le navigateur le retéléchargeait : deux
# transferts à la suite et une copie de plus à chaque clic.
#
# Désormais le fichier TRAVERSE le serveur sans s'y poser : le NAS envoie, le
# serveur relaie morceau par morceau, rien n'est écrit sur le disque. Le navigateur
# l'affiche avec son propre lecteur (PDF : toutes les pages, recherche, zoom), et
# les plages d'octets (Range) sont relayées : un PDF ou une vidéo peut commencer
# avant la fin du transfert, là où le NAS les sert.
#
# Un cadre ou une balise <img> n'envoie pas d'en-tête Authorization : la route
# accepte un BILLET court (10 min), signé par le serveur, lié à la personne ET au
# chemin — il n'ouvre rien d'autre, et les droits sont revérifiés à la lecture.
import hashlib as _hashlib
import hmac as _hmac
import mimetypes as _mimetypes
import time as _time
from urllib.parse import quote as _quote

from fastapi import Header, Request
from fastapi.responses import StreamingResponse

DUREE_BILLET_S = 600
_TYPES_ACTIFS = {"html", "htm", "xhtml", "svg", "svgz", "xml", "xsl", "js", "mjs", "hta", "shtml"}


def _signature(uid: str, chemin: str, expire: int) -> str:
    from config import settings
    brut = f"{uid}|{chemin}|{expire}".encode("utf-8")
    return _hmac.new(str(settings.jwt_secret_key).encode(), brut, _hashlib.sha256).hexdigest()


def billet(uid: str, chemin: str, maintenant: float | None = None) -> str:
    expire = int((maintenant or _time.time()) + DUREE_BILLET_S)
    return f"{uid}.{expire}.{_signature(uid, chemin, expire)}"


def lire_billet(valeur: str, chemin: str, maintenant: float | None = None) -> str | None:
    """L'identifiant de la personne si le billet est valide POUR CE CHEMIN, sinon None."""
    try:
        uid, expire, signature = str(valeur or "").split(".", 2)
        if int(expire) < (maintenant or _time.time()):
            return None
        return uid if _hmac.compare_digest(signature, _signature(uid, chemin, int(expire))) else None
    except (ValueError, TypeError):
        return None


class LienBody(BaseModel):
    chemin: str


@router.post("/lien")
async def lien(body: LienBody, current_user: User = Depends(get_current_user)):
    """L'adresse de lecture en flux d'un fichier, pour le lecteur du navigateur."""
    _exiger(current_user)
    from nas.acces import verifier
    from security.lecteur import au_nom_de
    try:
        with au_nom_de(current_user):
            vise = verifier(body.chemin)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    nom = posixpath.basename(vise)
    url = f"/api/nas-explorateur/fichier?chemin={_quote(vise)}&t={billet(str(current_user.id), vise)}"
    return {"chemin": vise, "nom": nom, "url": url,
            "type": _mimetypes.guess_type(nom)[0] or "application/octet-stream",
            "extension": nom.rsplit(".", 1)[-1].lower() if "." in nom else ""}


async def _personne(uid: str):
    from database.connection import get_db
    async with get_db() as conn:
        ligne = await conn.fetchrow("SELECT id, role, email FROM users WHERE id = $1::uuid AND actif = true", uid)
    return ligne


@router.get("/fichier")
async def fichier(request: Request, chemin: str = Query(...), t: str = Query(""),
                  telecharger: bool = Query(False), authorization: str | None = Header(None)):
    """Le fichier, relayé du NAS au navigateur sans passer par le disque."""
    import types as _types
    uid = lire_billet(t, chemin)
    if not uid and authorization and authorization.lower().startswith("bearer "):
        from auth.jwt_handler import decode_access_token
        try:
            uid = str(decode_access_token(authorization.split(" ", 1)[1]).get("sub") or "") or None
        except Exception:  # noqa: BLE001
            uid = None
    ligne = await _personne(uid) if uid else None
    if not ligne:
        raise HTTPException(status_code=401, detail="Lien expiré : rouvrez le fichier depuis l'onglet Fichiers.")
    personne = _types.SimpleNamespace(id=str(ligne["id"]), role=ligne["role"], email=ligne["email"])
    _exiger(personne)
    from ingestion.connectors import synology as c
    from nas.acces import connexion, verifier
    from security.lecteur import au_nom_de
    try:
        with au_nom_de(personne):
            vise = verifier(chemin)
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    nom = posixpath.basename(vise)
    plage = request.headers.get("range")

    async def ouvrir_flux():
        """Ouvre la réponse DSM ; rend (contexte, session, réponse) ou lève."""
        ctx = connexion()
        client, base, sid = await ctx.__aenter__()
        chemin_json = _quote('["' + vise + '"]')
        url = (f"{base}/webapi/entry.cgi?api=SYNO.FileStation.Download&version=2&method=download"
               f"&mode=download&_sid={sid}&path={chemin_json}")
        req = client.build_request("GET", url, headers={"Range": plage} if plage else None, timeout=None)
        try:
            rep = await client.send(req, stream=True)
        except BaseException as e:
            await ctx.__aexit__(type(e), e, e.__traceback__)
            raise
        return ctx, rep

    try:
        ctx, rep = await ouvrir_flux()
    except Exception as e:  # noqa: BLE001
        raise _refus(e)
    if rep.status_code >= 400 or rep.headers.get("content-type", "").startswith("application/json"):
        try:
            corps = await rep.aread()
            import json as _json
            code = int(((_json.loads(corps or b"{}") or {}).get("error") or {}).get("code") or 0)
        except Exception:  # noqa: BLE001
            code = 0
        await rep.aclose()
        await ctx.__aexit__(None, None, None)
        raise HTTPException(status_code=502, detail=f"« {nom} » n'a pas pu être lu sur le NAS : "
                            + (c._message(code, "SYNO.FileStation.Download.download") if code else f"HTTP {rep.status_code}"))

    async def morceaux():
        try:
            async for bloc in rep.aiter_bytes(256 * 1024):
                yield bloc
        finally:
            await rep.aclose()
            await ctx.__aexit__(None, None, None)

    type_ = _mimetypes.guess_type(nom)[0] or "application/octet-stream"
    # UNE PAGE WEB DU NAS NE S'EXÉCUTE PAS CHEZ NOUS : affichée telle quelle depuis
    # l'adresse de l'application, un .html ou un .svg déposé par n'importe qui pourrait
    # lire la session. Ces types partent en téléchargement, jamais en affichage.
    if nom.lower().rsplit(".", 1)[-1] in _TYPES_ACTIFS or type_ in ("text/html", "image/svg+xml",
                                                                        "application/xhtml+xml", "text/xml",
                                                                        "application/xml", "application/javascript"):
        telecharger, type_ = True, "application/octet-stream"
    entetes = {"Content-Disposition": f"{'attachment' if telecharger else 'inline'}; filename*=UTF-8''{_quote(nom)}",
               "Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff"}
    for cle in ("content-length", "content-range", "accept-ranges"):
        if rep.headers.get(cle):
            entetes[cle.title()] = rep.headers[cle]
    return StreamingResponse(morceaux(), status_code=206 if rep.status_code == 206 else 200,
                             media_type=type_, headers=entetes)
