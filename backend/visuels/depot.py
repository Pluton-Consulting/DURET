"""
LE DÉPÔT DES VISUELS GÉNÉRÉS — sur disque, parce qu'un tirage payé ne se perd pas.

Une image générée n'existe QUE dans la réponse de l'API, en base64 — et les
fournisseurs qui rendent une adresse de CDN la rendent signée et périssable.
La donner telle quelle au chat, c'est montrer une image qui meurt au bout de
quelques heures, et un rendu payé qui disparaît est un rendu payé deux fois.
Chaque image est donc rangée UNE fois par le backend,
dans le volume des documents produits (le même qui garde les Word), et servie
par une route authentifiée. Elle survit aux redémarrages, comme le devis
qu'elle illustre.

La clé est un condensé de l'adresse d'origine : re-déposer la même image rend
la même clé, sans doublon sur le disque.
"""
from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import threading

import httpx

logger = logging.getLogger("symbiose.visuels.depot")

DOSSIER = pathlib.Path(os.environ.get("DOCUMENTS_DIR", "/tmp/symbiose-documents")) / "visuels"

_MIMES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_EXT_PAR_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_OCTETS = 15 * 1024 * 1024


async def deposer_depuis_url(url: str) -> str | None:
    """Télécharge une image et rend sa clé. None si le téléchargement échoue —
    l'appelant garde alors l'adresse externe, on ne perd jamais le rendu."""
    if not url or not url.startswith("http"):
        return None
    cle = hashlib.sha256(url.split("?")[0].encode("utf-8")).hexdigest()[:24]
    existant = _chemin(cle)
    if existant:
        if proprietaires(cle) is not None:
            noter_proprietaire(cle)
        return cle
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            if len(r.content) > MAX_OCTETS:
                logger.warning("Visuel trop lourd (%d octets), garde en externe", len(r.content))
                return None
            mime = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
            ext = _EXT_PAR_MIME.get(mime, ".jpg")
        DOSSIER.mkdir(parents=True, exist_ok=True)
        noter_proprietaire(cle)
        (DOSSIER / f"{cle}{ext}").write_bytes(r.content)
        logger.info("Visuel déposé : %s (%d Ko)", cle, len(r.content) // 1024)
        return cle
    except Exception as e:  # noqa: BLE001 — un dépôt raté n'annule pas la génération
        logger.warning("Dépôt du visuel impossible (%s)", type(e).__name__)
        return None


def _chemin(cle: str) -> pathlib.Path | None:
    if not cle.isalnum():
        return None
    for ext in _MIMES:
        p = DOSSIER / f"{cle}{ext}"
        if p.exists():
            return p
    return None


def lire(cle: str) -> tuple[bytes, str] | None:
    """(octets, type MIME) d'un visuel déposé, ou None."""
    p = _chemin(cle)
    if not p:
        return None
    return p.read_bytes(), _MIMES.get(p.suffix, "image/jpeg")


# ── À QUI APPARTIENT UN VISUEL (16/09, audit D-03) ──────────────────────────
# La route vérifiait la connexion, pas le propriétaire : toute clé connue d'un
# compte ouvrait l'image d'un autre (une photo de chantier, une pièce d'un
# mail). Chaque dépôt fait pendant un geste note désormais son propriétaire
# dans un fichier voisin (`<clé>.acces`) — la clé est l'empreinte du contenu,
# deux personnes qui déposent la même image en sont toutes deux propriétaires.
# Un visuel déposé AVANT ce correctif n'a pas de propriétaire connu : il reste
# lisible (sinon toutes les conversations passées perdraient leurs images), et
# c'est journalisé pour une reprise administrative. Il n'est pas non plus
# RÉCLAMÉ par le premier qui redépose le même contenu : il disparaîtrait des
# conversations de ceux qui l'avaient déjà.
#
# Le propriétaire d'un NOUVEAU visuel est noté AVANT l'image : un second dépôt
# simultané du même contenu voit alors un visuel possédé (et s'y ajoute), jamais
# un visuel « ancien » qu'il laisserait sans lui.

_VERROU_ACCES = threading.Lock()


def _chemin_acces(cle: str) -> pathlib.Path | None:
    return DOSSIER / f"{cle}.acces" if (cle or "").isalnum() else None


def proprietaires(cle: str) -> list[str] | None:
    """Les propriétaires connus d'un visuel, ou None si aucun n'a été noté."""
    chemin = _chemin_acces(cle)
    if chemin is None or not chemin.exists():
        return None
    try:
        import json
        valeur = json.loads(chemin.read_text(encoding="utf-8") or "[]")
        return [str(v) for v in valeur if v] if isinstance(valeur, list) else None
    except Exception:  # noqa: BLE001 — un fichier abîmé ne vaut pas autorisation
        return []


def noter_proprietaire(cle: str, proprietaire: str | None = None) -> None:
    """Ajoute le propriétaire (ou la personne du geste en cours). Best-effort."""
    if proprietaire is None:
        try:
            from security.lecteur import id_lecteur
            proprietaire = id_lecteur()
        except Exception:  # noqa: BLE001
            proprietaire = None
    chemin = _chemin_acces(cle)
    if not proprietaire or chemin is None:
        return
    import json
    with _VERROU_ACCES:
        actuels = proprietaires(cle) or []
        if str(proprietaire) in actuels:
            return
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            temporaire = chemin.with_name(f"{chemin.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temporaire.write_text(json.dumps(actuels + [str(proprietaire)]), encoding="utf-8")
            temporaire.replace(chemin)
        except Exception as e:  # noqa: BLE001 — un dépôt ne casse jamais pour ça
            logger.warning("Propriétaire du visuel non noté (%s)", type(e).__name__)


def reserver_a_l_administration(cle: str) -> None:
    """Un visuel ancien dont personne n'a pu être établi propriétaire
    (`scripts/rattacher_visuels.py --fermer-indetermines`) : seul le
    super-administrateur le voit. Rien n'est supprimé ; un propriétaire noté
    plus tard (quelqu'un redépose la même image) le rouvre à cette personne."""
    chemin = _chemin_acces(cle)
    if chemin is None or not _chemin(cle):
        return
    with _VERROU_ACCES:
        if chemin.exists():
            return
        try:
            temporaire = chemin.with_name(f"{chemin.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            temporaire.write_text("[]", encoding="utf-8")
            temporaire.replace(chemin)
        except Exception as e:  # noqa: BLE001
            logger.warning("Visuel %s non réservé (%s)", cle[:12], type(e).__name__)


_SANS_PROPRIETAIRE_DIT: set = set()


def peut_lire(cle: str, user) -> bool:
    """Cette personne peut-elle voir ce visuel ? Le super-administrateur, oui ;
    sinon il faut en être propriétaire. Un visuel d'avant le 16/09 (aucun
    propriétaire noté) reste lisible, et c'est journalisé une fois."""
    if str(getattr(user, "role", "") or "").strip().lower() == "super_admin":
        return True
    liste = proprietaires(cle)
    if liste is None:
        if cle not in _SANS_PROPRIETAIRE_DIT:
            _SANS_PROPRIETAIRE_DIT.add(cle)
            logger.info("Visuel %s sans propriétaire connu (antérieur au 16/09) : lisible", cle[:12])
        return True
    return str(getattr(user, "id", "") or "") in liste


def deposer_octets(octets: bytes, mime: str = "image/png",
                   proprietaire: str | None = None) -> str | None:
    """Range une image reçue en OCTETS (Nano Banana rend l'image dans la
    réponse, pas une adresse). Clé = condensé du contenu : même image, même
    clé, pas de doublon."""
    if not octets or len(octets) > MAX_OCTETS:
        return None
    cle = hashlib.sha256(octets).hexdigest()[:24]
    if _chemin(cle):
        if proprietaires(cle) is not None:
            noter_proprietaire(cle, proprietaire)
        return cle
    ext = _EXT_PAR_MIME.get((mime or "").split(";")[0].strip(), ".png")
    try:
        DOSSIER.mkdir(parents=True, exist_ok=True)
        noter_proprietaire(cle, proprietaire)
        (DOSSIER / f"{cle}{ext}").write_bytes(octets)
        logger.info("Visuel déposé (octets) : %s (%d Ko)", cle, len(octets) // 1024)
        return cle
    except Exception as e:  # noqa: BLE001
        logger.warning("Dépôt du visuel impossible (%s)", type(e).__name__)
        return None


# ── La filiation d'une retouche (15/09) ─────────────────────────────────────
# « Mets le pied de la berlinoise au niveau du trait bleu » : le trait bleu,
# tracé par le client, n'existe QUE sur sa photo d'origine. Dès la première
# retouche il a disparu sous la berlinoise, et les suivantes partaient d'images
# où le repère n'était plus : le moteur ne pouvait pas le trouver. Chaque rendu
# retient donc la photo dont la chaîne est partie, dans un fichier voisin.

def noter_origine(cle: str, origine: str) -> None:
    """Retient que `cle` descend de la photo `origine` (best-effort)."""
    if not (cle or "").isalnum() or not (origine or "").isalnum() or cle == origine:
        return
    try:
        DOSSIER.mkdir(parents=True, exist_ok=True)
        (DOSSIER / f"{cle}.origine").write_text(origine, encoding="utf-8")
    except Exception as e:  # noqa: BLE001 — la filiation n'arrête jamais un rendu
        logger.info("Filiation du visuel non notée (%s)", type(e).__name__)


def origine_de(cle: str) -> str:
    """La photo d'origine dont `cle` descend, ou "" si `cle` en est une."""
    if not (cle or "").isalnum():
        return ""
    try:
        valeur = (DOSSIER / f"{cle}.origine").read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return ""
    return valeur if valeur.isalnum() and _chemin(valeur) else ""
