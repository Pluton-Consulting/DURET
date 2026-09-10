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



def _est_un_pdf(nom: str, mime: str | None) -> bool:
    return (str(mime or "").lower().startswith("application/pdf")
            or str(nom or "").lower().endswith(".pdf"))


# Ce qui distingue un LOGO d'une page scannée : il vit dans la bande haute ou
# basse de la page, et il est petit devant elle. Les seuils sont larges — on
# cherche à écarter le scan pleine page, pas à faire de la mise en page.
_BANDE = 0.28          # le quart haut ou bas de la page
_PART_MAX = 0.35       # au-delà, ce n'est plus un logo mais une illustration


def _aire(rect) -> float:
    """L'aire d'un rectangle PyMuPDF, quelle que soit la version.

    `Rect.get_area()` n'existe pas partout (elle s'appelait `getArea`, et la
    propriété `.width`/`.height` est la seule constante) : on la calcule.
    """
    try:
        return abs(float(rect.width) * float(rect.height))
    except Exception:  # noqa: BLE001
        return 0.0


def logo_du_pdf(octets: bytes, nom: str) -> tuple[bytes, str, str]:
    """(octets, mime, nom) du logo d'un PDF : la plus grande image d'en-tête ou de pied.

    Lève `ImageRefusee` avec une raison lisible quand le PDF n'en porte pas —
    un PDF de texte pur, ou une page scannée d'un seul tenant.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:  # pragma: no cover — présent dans l'image
        # LE REFUS NOMME TOUJOURS LE FICHIER : sans son nom, la personne ne sait
        # pas lequel de ses trois documents a été écarté.
        raise ImageRefusee(f"« {nom} » est un PDF, et sa lecture est indisponible "
                           "sur ce serveur (PyMuPDF absent)") from e

    candidats = []
    try:
        doc = fitz.open(stream=octets, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise ImageRefusee(f"« {nom} » ne s'ouvre pas comme un PDF") from e
    try:
        # L'en-tête et le pied se répètent : la première page suffit, et deux
        # pages au plus bornent le travail sur un dossier de cent pages.
        for page in list(doc)[:2]:
            hauteur = float(page.rect.height) or 1.0
            aire_page = _aire(page.rect) or 1.0
            for info in page.get_images(full=True):
                xref = info[0]
                try:
                    rects = page.get_image_rects(xref)
                except Exception:  # noqa: BLE001
                    rects = []
                if not rects:
                    continue
                r = rects[0]
                haut = float(r.y1) <= hauteur * _BANDE
                bas = float(r.y0) >= hauteur * (1 - _BANDE)
                if not (haut or bas):
                    continue
                if _aire(r) > aire_page * _PART_MAX:
                    continue
                try:
                    brut = doc.extract_image(xref)
                except Exception:  # noqa: BLE001
                    continue
                donnees = brut.get("image") or b""
                if len(donnees) < 256:      # une puce, une ligne de séparation
                    continue
                candidats.append((_aire(r), donnees,
                                  f"image/{(brut.get('ext') or 'png').lower()}",
                                  "en-tête" if haut else "pied de page"))
    finally:
        doc.close()

    if not candidats:
        raise ImageRefusee(
            f"« {nom} » ne porte aucune image d'en-tête ou de pied de page "
            "exploitable (PDF de texte, ou page scannée d'un seul tenant). "
            "Reprends son en-tête en TEXTE, ou donne le fichier du logo.")
    candidats.sort(key=lambda c: -c[0])
    _, donnees, mime, place = candidats[0]
    return donnees, mime, f"{nom} ({place})"


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
        # UN DEVIS DE RÉFÉRENCE EST SOUVENT UN PDF, et c'est SON logo qu'on
        # nous demande de reprendre. On l'en extrait plutôt que de renvoyer le
        # modèle recopier l'en-tête à la main, en texte (09/09).
        if _est_un_pdf(nom, mime):
            octets, mime, nom = await asyncio.to_thread(logo_du_pdf, octets, nom)
        else:
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
