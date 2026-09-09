"""
Les IMAGES d'un document produit : d'une référence que le modèle connaît aux
octets rangés à l'atelier, puis rendus dans le corps, l'en-tête ou le pied.

Relevé de Noa du 09/09 : « il n'arrive pas à récupérer une image du Drive ou
qu'on donne en pièce jointe et à la mettre en pied de page d'un doc Word ».
Rien ne manquait au modèle : le vocabulaire des blocs n'avait pas d'image, et
l'en-tête comme le pied n'étaient que du texte.

POURQUOI LE MODÈLE NE DÉSIGNE QUE CE QU'UN GESTE LUI A RENDU. Même règle que
les pièces jointes d'un mail (`mail/attaches.py`, dont on RÉUTILISE la
résolution) : une image se nomme par la clé du dépôt (photo jointe au chat,
image ouverte sur le stockage, tirage), par le jeton d'un document de
l'atelier, par la `ref` d'une pièce d'un mail ouvert, ou par le NOM d'un
fichier image du stockage — jamais par un chemin, qui ferait de ce geste un
moyen de lire n'importe quel fichier du serveur. Chaque forme porte sa propre
vérification de droits, appliquée par la fonction qui la résout.

Les octets sont rangés à l'atelier SOUS LE JETON du document
(`<jeton>.img<n>.png`) : ils suivent sa durée de vie, disparaissent avec lui,
et le rendu ne lit que ces fichiers-là. Un élément dont l'image ne se résout
pas est ÉCARTÉ avec sa raison, jamais inséré vide : un trou dans un document
se découvre une fois envoyé.
"""
from __future__ import annotations

import asyncio
import io
import logging

from bureautique.modele import CLES_IMAGE, RE_IMAGE_RANGEE, _TYPES

logger = logging.getLogger("duret.bureautique.images")

MAX_OCTETS_IMAGE = 15 * 1024 * 1024
EXTENSIONS_IMAGE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")
# Ce que les trois moteurs de rendu lisent sans conversion.
_NATIFS = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg"}


class ImageRefusee(Exception):
    """La référence ne donne pas une image utilisable ; le message dit pourquoi."""


def est_image(nom: str, mime: str | None = None) -> bool:
    return (str(mime or "").lower().startswith("image/")
            or str(nom or "").lower().endswith(EXTENSIONS_IMAGE))


def reference_de(brut: dict) -> str:
    """La référence écrite par le modèle, sous le nom de champ qu'il a choisi."""
    for cle in CLES_IMAGE:
        v = brut.get(cle)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def normaliser_octets(octets: bytes, mime: str | None) -> tuple[bytes, str]:
    """(octets, extension) — PNG et JPEG tels quels, le reste converti en PNG.

    Word, PDF et Excel lisent PNG et JPEG ; un WebP (les photos du chat sont
    souvent déposées ainsi), un GIF ou un BMP ne passeraient pas. Sans Pillow,
    la conversion est impossible et le refus le dit — on ne range jamais des
    octets que le rendu ne saura pas ouvrir.
    """
    mime = str(mime or "").split(";")[0].strip().lower()
    if mime in _NATIFS:
        return octets, _NATIFS[mime]
    try:
        from PIL import Image
    except ImportError as e:
        raise ImageRefusee("conversion d'image impossible sur ce serveur (Pillow absent)") from e
    try:
        img = Image.open(io.BytesIO(octets))
        img.load()
    except Exception as e:  # noqa: BLE001 — un fichier qui n'est pas une image
        raise ImageRefusee("le fichier n'est pas une image lisible") from e
    if img.format in ("PNG", "JPEG"):
        return octets, "png" if img.format == "PNG" else "jpg"
    sortie = io.BytesIO()
    (img.convert("RGBA") if img.mode in ("RGBA", "LA", "P") else img.convert("RGB")).save(sortie, format="PNG")
    return sortie.getvalue(), "png"


async def resoudre(designation: str, user) -> tuple[bytes, str, str]:
    """(octets, extension, nom) d'une image désignée par le modèle.

    La résolution est CELLE DES PIÈCES JOINTES (`mail/attaches.resoudre`) :
    clé du dépôt, jeton d'atelier, `ref` de pièce, nom sur le stockage — avec
    les droits de chacune. Lève `ImageRefusee` avec la raison pour la personne.
    """
    from mail.attaches import resoudre as _resoudre_pieces

    designation = str(designation or "").strip()
    if not designation:
        raise ImageRefusee("aucune référence d'image")
    pretes, refusees = await _resoudre_pieces([designation], user, "")
    if not pretes:
        raison = (refusees[0].get("raison") if refusees else "") or "introuvable"
        raise ImageRefusee(raison)
    piece = pretes[0]
    nom, mime, octets = str(piece.get("nom") or ""), str(piece.get("mime") or ""), piece.get("octets") or b""
    if not est_image(nom, mime):
        raise ImageRefusee(f"« {nom} » n'est pas une image ({mime or 'type inconnu'}) : "
                           "seule une image (PNG, JPEG, WebP, GIF, BMP, TIFF) peut être insérée")
    if len(octets) > MAX_OCTETS_IMAGE:
        raise ImageRefusee(f"« {nom} » pèse {len(octets) // (1024 * 1024)} Mo : "
                           f"au-delà de {MAX_OCTETS_IMAGE // (1024 * 1024)} Mo, réduis-la d'abord")
    octets, ext = await asyncio.to_thread(normaliser_octets, octets, mime)
    return octets, ext, nom


def _est_un_bloc_image(e) -> bool:
    if not isinstance(e, dict):
        return False
    demande = str(e.get("bloc") or e.get("type") or e.get("kind") or "").strip().lower()
    return _TYPES.get(demande) == "image"


async def preparer(jeton: str, proprietaire: str, elements: list, entete: dict, user) -> tuple[list, dict, list]:
    """Résout et RANGE les images d'un versement : (éléments prêts, en-tête prêt, refus).

    Un bloc image dont la référence se résout reçoit son `fichier` (rangé
    sous le jeton) ; sinon il est ÉCARTÉ et la raison est rendue, pour que le
    modèle la dise. Même chose pour `entete_image` / `pied_image`. Un
    document inconnu ou fini ne range rien (l'atelier refusera l'ajout
    lui-même, avec son message habituel).
    """
    from bureautique.atelier import fiche, ranger_image

    refus: list[str] = []
    if fiche(jeton, proprietaire) is None:
        return list(elements or []), dict(entete or {}), refus

    async def _ranger(ref: str) -> str:
        octets, ext, _ = await resoudre(ref, user)
        return ranger_image(jeton, proprietaire, octets, ext)

    prets: list = []
    for e in (elements or []):
        if not _est_un_bloc_image(e) or RE_IMAGE_RANGEE.match(str(e.get("fichier") or "")):
            prets.append(e)
            continue
        ref = reference_de(e)
        if not ref:
            refus.append("un bloc image sans référence (champ `image`)")
            continue
        try:
            fichier = await _ranger(ref)
        except Exception as err:  # noqa: BLE001 — un refus est une donnée, pas un plantage
            refus.append(f"« {ref[:60]} » : {str(err)[:200]}")
            continue
        prets.append({**e, "bloc": "image", "fichier": fichier})

    entete = dict(entete or {})
    for cle in ("entete_image", "pied_image"):
        ref = str(entete.get(cle) or "").strip()
        if not ref or RE_IMAGE_RANGEE.match(str(entete.get(cle + "_fichier") or "")):
            continue
        try:
            entete[cle + "_fichier"] = await _ranger(ref)
        except Exception as err:  # noqa: BLE001
            refus.append(f"{'en-tête' if cle == 'entete_image' else 'pied de page'} « {ref[:60]} » : {str(err)[:200]}")
            entete[cle] = ""
    return prets, entete, refus


def note_refus(refus: list) -> str:
    """La phrase à rendre au modèle quand des images n'ont pas pu être insérées."""
    if not refus:
        return ""
    return (f" {len(refus)} image(s) NON insérée(s) — " + " ; ".join(refus)
            + ". Dis-le à la personne, ne prétends pas que l'image y est.")
