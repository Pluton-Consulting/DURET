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


def logo_du_pdf(octets: bytes, nom: str, place: str = "") -> tuple[bytes, str, str]:
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
        # PAS D'IMAGE INTÉGRÉE : ON DESSINE LA PAGE (15/09). Deux cas vus en prod,
        # refusés jusqu'ici : le logo de la maison livré en PDF VECTORIEL
        # (« SYMBIOSE Paysage coul.pdf » — des tracés, aucune image) et le devis
        # SCANNÉ dont on veut « récupérer l'en-tête et le pied de page ». La page
        # est rendue en image et recadrée : sur le logo, tout ce qui est encré ;
        # sur une page pleine, la bande du haut (en-tête) ou du bas (pied).
        return rendu_du_pdf(octets, nom, place)
    # La bande demandée d'abord (le pied pour un pied de page), puis la plus grande.
    voulue = "pied de page" if place == "pied" else "en-tête"
    candidats.sort(key=lambda c: (0 if c[3] == voulue else 1, -c[0]))
    _, donnees, mime, place_trouvee = candidats[0]
    return donnees, mime, f"{nom} ({place_trouvee})"


# Au-delà de cette part de la page, le contenu encré n'est pas un logo seul mais
# une page de document : on n'en garde que la bande demandée.
_PART_LOGO = 0.45
_BANDE_MAX = 0.24       # une bande d'en-tête ou de pied ne dépasse pas ce quart
_BLANC = 235            # au-dessus de ce gris, un pixel est du papier


def _lignes_encrees(img) -> list[bool]:
    """Pour chaque ligne de pixels, porte-t-elle de l'encre ?"""
    largeur, hauteur = img.size
    donnees = img.load()
    pas = max(1, largeur // 400)
    return [any(donnees[x, y] < _BLANC for x in range(0, largeur, pas)) for y in range(hauteur)]


def _recadrer(img, boite, marge: int = 12):
    x0, y0, x1, y1 = boite
    return img.crop((max(0, x0 - marge), max(0, y0 - marge),
                     min(img.size[0], x1 + marge), min(img.size[1], y1 + marge)))


def rendu_du_pdf(octets: bytes, nom: str, place: str = "") -> tuple[bytes, str, str]:
    """(octets PNG, mime, nom) : la page 1 du PDF dessinée et recadrée.

    `place` : « pied » prend la bande du BAS d'une page pleine ; sinon celle du
    HAUT. Un logo seul (peu d'encre sur la page) est rendu en entier, recadré.
    """
    try:
        import fitz  # PyMuPDF
        from PIL import Image, ImageOps
    except ImportError as e:  # pragma: no cover — présents dans l'image
        raise ImageRefusee(f"« {nom} » est un PDF, et son rendu est indisponible sur ce serveur") from e
    import io
    try:
        doc = fitz.open(stream=octets, filetype="pdf")
        page = doc[0]
        pix = page.get_pixmap(dpi=200, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        doc.close()
    except Exception as e:  # noqa: BLE001
        raise ImageRefusee(f"« {nom} » ne se dessine pas comme un PDF") from e
    gris = ImageOps.grayscale(img)
    boite = ImageOps.invert(gris).point(lambda v: 255 if v > 255 - _BLANC else 0).getbbox()
    if not boite:
        raise ImageRefusee(f"« {nom} » : la première page est blanche")
    largeur, hauteur = img.size
    part = ((boite[2] - boite[0]) * (boite[3] - boite[1])) / float(largeur * hauteur)
    if part <= _PART_LOGO:
        sortie, ou = _recadrer(img, boite), "logo"
    else:
        lignes = _lignes_encrees(gris)
        limite = int(hauteur * _BANDE_MAX)
        ordre = range(hauteur - 1, -1, -1) if place == "pied" else range(hauteur)
        debut = fin = None
        vide = 0
        ferme = False
        saut = max(8, int(hauteur * 0.012))     # un blanc de ~1,2 % de page ferme la bande
        for n, y in enumerate(ordre):
            if n > limite:
                break
            if lignes[y]:
                if debut is None:
                    debut = y
                fin, vide = y, 0
            elif debut is not None:
                vide += 1
                if vide >= saut:
                    ferme = True
                    break
        bande_nom = "de pied" if place == "pied" else "d'en-tête"
        if debut is not None and not ferme:
            # Pas un blanc sous la bande : une page d'un seul tenant (un scan
            # grisé, une photo pleine page). Il n'y a pas d'en-tête distinct à
            # prendre, et coller une tranche de scan serait pire que rien.
            raise ImageRefusee(
                f"« {nom} » est une page d'un seul tenant, sans bande "
                f"{bande_nom} distincte : reprends son en-tête "
                "en TEXTE, ou donne le fichier du logo")
        if debut is None:
            raise ImageRefusee(f"« {nom} » : rien d'encré dans la bande "
                               f"{'du bas' if place == 'pied' else 'du haut'} de la première page")
        y0, y1 = sorted((debut, fin))
        bande = gris.crop((0, y0, largeur, y1 + 1))
        bx = ImageOps.invert(bande).point(lambda v: 255 if v > 255 - _BLANC else 0).getbbox() or (0, 0, largeur, 1)
        sortie = _recadrer(img, (bx[0], y0, bx[2], y1 + 1))
        ou = "pied de page" if place == "pied" else "en-tête"
    tampon = io.BytesIO()
    sortie.save(tampon, format="PNG", optimize=True)
    return tampon.getvalue(), "image/png", f"{nom} ({ou}, dessiné)"


async def resoudre(designation: str, user, place: str = "") -> tuple[bytes, str, str]:
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
            octets, mime, nom = await asyncio.to_thread(logo_du_pdf, octets, nom, place)
        else:
            raise ImageRefusee(f"« {nom} » n'est pas une image ({mime or 'type inconnu'}) : "
                               "seule une image (PNG, JPEG, WebP, GIF, BMP, TIFF) peut être insérée")
    if len(octets) > MAX_OCTETS_IMAGE:
        raise ImageRefusee(f"« {nom} » pèse {len(octets) // (1024 * 1024)} Mo : "
                           f"au-delà de {MAX_OCTETS_IMAGE // (1024 * 1024)} Mo, réduis-la d'abord")
    octets, ext = await asyncio.to_thread(normaliser_octets, octets, mime)
    return octets, ext, nom


def _est_un_bloc_image(e) -> bool:
    """Un bloc qui porte une image à résoudre : `image`, ou `colonnes` (texte + photo)."""
    if not isinstance(e, dict):
        return False
    demande = str(e.get("bloc") or e.get("type") or e.get("kind") or "").strip().lower()
    genre = _TYPES.get(demande)
    if genre == "colonnes":
        return any(isinstance(e.get(c), str) and e.get(c).strip() for c in ("image", "photo", "ref", "cle", "nom"))
    return genre == "image"


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

    async def _ranger(ref: str, place: str = "") -> str:
        octets, ext, _ = await resoudre(ref, user, place)
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
        genre = _TYPES.get(str(e.get("bloc") or e.get("type") or e.get("kind") or "").strip().lower())
        prets.append({**e, "bloc": "colonnes" if genre == "colonnes" else "image", "fichier": fichier})

    entete = dict(entete or {})
    for cle in ("entete_image", "pied_image", "image_couverture"):
        ref = str(entete.get(cle) or "").strip()
        if not ref or RE_IMAGE_RANGEE.match(str(entete.get(cle + "_fichier") or "")):
            continue
        try:
            entete[cle + "_fichier"] = await _ranger(ref, "pied" if cle == "pied_image" else "")
        except Exception as err:  # noqa: BLE001
            refus.append(f"{ {'entete_image': 'en-tête', 'pied_image': 'pied de page'}.get(cle, 'couverture') } « {ref[:60]} » : {str(err)[:200]}")
            entete[cle] = ""
    return prets, entete, refus


def note_refus(refus: list) -> str:
    """La phrase à rendre au modèle quand des images n'ont pas pu être insérées."""
    if not refus:
        return ""
    return (f" {len(refus)} image(s) NON insérée(s) — " + " ; ".join(refus)
            + ". Dis-le à la personne, ne prétends pas que l'image y est.")
