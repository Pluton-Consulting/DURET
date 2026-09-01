"""
Les pièces jointes d'un mail : les RÉCUPÉRER, les rendre TÉLÉCHARGEABLES, les LIRE.

POURQUOI (31/08/2026). Noa, une fois le corps des mails enfin lu en entier :
« au niveau des pièces jointes, il doit être capable de les récupérer pour les
rendre téléchargeables dans l'interface et de les exploiter — PNG par OCR, PDF,
DWG — et pareil s'il y a des liens ». Jusqu'ici `lire_mail` ne rendait que le
NOM des pièces : un devis reçu en PDF, un plan en DWG, une photo de chantier
restaient hors de portée de l'assistant, qui les citait sans les avoir vus.

CE QUE FAIT CE MODULE, pour UNE pièce (octets + nom + type) :
  1. il la DÉPOSE là où l'écran sait la montrer — une image dans le dépôt des
     visuels (bloc `visuel`, aperçu + téléchargement), tout le reste dans
     l'atelier des documents (bloc `fichier` : téléchargement, et aperçu pour
     PDF / Word / Excel). Le fichier est servi par une route authentifiée, à
     la personne qui l'a demandé, et vit 24 h comme tout document produit ;
  2. il en tire un TEXTE, par le moyen qui convient :
       PDF        → couche texte, sinon OCR page à page (`ingestion.parsers`) ;
       Word/Excel/CSV/texte → les parseurs de l'ingestion ;
       image      → OCR (tesseract) ; si l'OCR ne rend presque rien (photo,
                    plan, schéma), le modèle de VISION la décrit ;
       DWG        → le format est binaire et propriétaire : on en extrait la
                    VIGNETTE que tout DWG embarque (BMP ou PNG), déposée comme
                    image — d'où l'aperçu et une lecture par la vision — et sa
                    version AutoCAD. Les entités elles-mêmes ne sont pas lues :
                    on le DIT, on ne fait pas semblant ;
       DXF        → ses textes (TEXT / MTEXT / ATTRIB), c'est ce qu'un plan
                    dit en toutes lettres (cotes, légendes, cartouche) ;
       archive    → la liste de ce qu'elle contient.
  3. il dit COMMENT il a lu (`methode`) et ce qu'il a coupé : un texte borné
     à MAX_TEXTE_PIECE, la coupure annoncée.

Tout est borné (taille, nombre, texte) parce qu'un mail peut porter 40 Mo de
photos, et qu'un tour n'est pas une synchronisation.

Les fonctions de bas niveau (`liens_du_texte`, `texte_dxf`, `vignette_dwg`,
`extension`) sont PURES : le banc les exerce sans réseau ni base.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
import struct
import zipfile
from typing import Optional

logger = logging.getLogger("symbiose.mail.pieces")

MAX_OCTETS_PIECE = 25 * 1024 * 1024   # au-delà, on la rend téléchargeable sans la lire
MAX_TEXTE_PIECE = 6000                # ce qu'on montre au modèle d'UNE pièce
MAX_PIECES_PAR_MAIL = 8               # lues d'un coup ; les autres restent listées
MAX_LIENS = 20
# Sous ce nombre de caractères, l'OCR n'a rien lu d'utile : une photo de
# chantier, un plan, un schéma — c'est la vision qui sait en parler.
OCR_MINIMUM = 40

EXT_IMAGE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic")
EXT_TEXTE = (".txt", ".md", ".log", ".json", ".xml", ".eml")
_MIME_EXT = {
    "application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
    "image/webp": ".webp", "image/bmp": ".bmp", "image/tiff": ".tif",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc", "application/vnd.ms-excel": ".xls",
    "text/csv": ".csv", "text/plain": ".txt", "application/zip": ".zip",
    "image/vnd.dwg": ".dwg", "application/acad": ".dwg", "application/x-dwg": ".dwg",
    "image/vnd.dxf": ".dxf", "application/dxf": ".dxf",
}
VERSIONS_DWG = {
    "AC1012": "AutoCAD R13", "AC1014": "AutoCAD R14", "AC1015": "AutoCAD 2000",
    "AC1018": "AutoCAD 2004", "AC1021": "AutoCAD 2007", "AC1024": "AutoCAD 2010",
    "AC1027": "AutoCAD 2013", "AC1032": "AutoCAD 2018",
}


# ── Fonctions pures ─────────────────────────────────────────────────────────

def extension(nom: str, mime: Optional[str] = None) -> str:
    """L'extension en minuscules, du NOM d'abord (il ment moins que le type
    MIME des messageries, souvent `application/octet-stream`), du type sinon."""
    n = (nom or "").strip().lower()
    if "." in n and 1 <= len(n.rsplit(".", 1)[1]) <= 5:
        return "." + n.rsplit(".", 1)[1]
    return _MIME_EXT.get((mime or "").split(";")[0].strip().lower(), "")


def est_image(nom: str, mime: Optional[str] = None) -> bool:
    return extension(nom, mime) in EXT_IMAGE or (mime or "").lower().startswith("image/")


_RE_LIEN = re.compile(r"https?://[^\s<>\"'()\[\]{}]+", re.I)


def liens_du_texte(texte: str, maximum: int = MAX_LIENS) -> list[str]:
    """Les adresses web d'un corps de mail, sans doublon ni ponctuation finale,
    dans l'ordre d'apparition. Les liens de désinscription et de suivi
    (« unsubscribe », « tracking ») sont écartés : ce ne sont pas des liens
    que la personne voudrait ouvrir."""
    vus, sortie = set(), []
    for brut in _RE_LIEN.findall(texte or ""):
        lien = brut.rstrip(".,;:!?»›")
        bas = lien.lower()
        if any(m in bas for m in ("unsubscribe", "desinscri", "désinscri", "/track", "tracking", "pixel")):
            continue
        cle = bas.rstrip("/")
        if cle in vus:
            continue
        vus.add(cle)
        sortie.append(lien)
        if len(sortie) >= maximum:
            break
    return sortie


def texte_dxf(brut: bytes, maximum: int = MAX_TEXTE_PIECE) -> str:
    """Les textes d'un DXF (ASCII) : entités TEXT, MTEXT, ATTRIB, DIMENSION —
    codes de groupe 1 (texte) et 3 (suite d'un MTEXT long). Les codes de
    formatage MTEXT (`\\P` saut de ligne, `{\\f…;}` police) sont retirés."""
    try:
        contenu = brut.decode("utf-8")
    except UnicodeDecodeError:
        contenu = brut.decode("latin-1", errors="replace")
    lignes = contenu.splitlines()
    textes, entite, i = [], None, 0
    while i + 1 < len(lignes):
        code, valeur = lignes[i].strip(), lignes[i + 1].strip()
        i += 2
        if code == "0":
            entite = valeur.upper()
            continue
        if entite in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF", "DIMENSION") and code in ("1", "3") and valeur:
            propre = re.sub(r"\\[A-Za-z][^;\\]*;|[{}]", "", valeur.replace("\\P", " ")).strip()
            if propre and propre not in textes:
                textes.append(propre)
    texte = "\n".join(textes)
    return texte[:maximum]


def vignette_dwg(brut: bytes) -> tuple[Optional[bytes], str, str]:
    """(image, type MIME, version) — la vignette qu'un DWG embarque, et sa version.

    Structure (R2000 et suivants) : les six premiers octets portent la version
    (« AC1032 »), l'entier à l'offset 0x0D pointe la section d'aperçu. Elle
    commence par 16 octets de sentinelle, un entier de taille, un octet de
    nombre d'images, puis pour chaque image : un code (2 = BMP sans en-tête
    de fichier, 6 = PNG depuis R2013), un début et une taille. Le BMP se
    rend lisible en lui rendant ses 14 octets d'en-tête. Rien ici ne touche
    aux entités du dessin : un DWG ne se « lit » pas sans AutoCAD ou l'ODA,
    et on ne fait pas semblant.
    """
    version = brut[:6].decode("ascii", errors="replace") if len(brut) >= 6 else ""
    nom_version = VERSIONS_DWG.get(version, f"format {version}" if version.startswith("AC") else "format inconnu")
    try:
        if len(brut) < 0x20 or not version.startswith("AC"):
            return None, "", nom_version
        debut = struct.unpack_from("<I", brut, 0x0D)[0]
        if debut <= 0 or debut + 21 > len(brut):
            return None, "", nom_version
        pos = debut + 16 + 4                      # sentinelle + taille globale
        nb = brut[pos]
        pos += 1
        for _ in range(nb):
            if pos + 9 > len(brut):
                break
            code = brut[pos]
            start, size = struct.unpack_from("<II", brut, pos + 1)
            pos += 9
            if size <= 0 or start + size > len(brut):
                continue
            donnees = brut[start:start + size]
            if code == 6 and donnees[:4] == b"\x89PNG":
                return donnees, "image/png", nom_version
            if code == 2 and len(donnees) >= 40:
                # BITMAPINFOHEADER seul : on recompose l'en-tête de fichier.
                taille_entete = struct.unpack_from("<I", donnees, 0)[0]
                bits = struct.unpack_from("<H", donnees, 14)[0] if taille_entete >= 16 else 24
                couleurs = struct.unpack_from("<I", donnees, 32)[0] if taille_entete >= 36 else 0
                palette = (couleurs or (1 << bits if bits <= 8 else 0)) * 4
                offset = 14 + taille_entete + palette
                entete = b"BM" + struct.pack("<IHHI", 14 + size, 0, 0, offset)
                return entete + donnees, "image/bmp", nom_version
    except (struct.error, IndexError):
        pass
    return None, "", nom_version


def lire_archive(brut: bytes, maximum: int = 60) -> str:
    """Ce qu'une archive zip contient : noms et tailles, sans rien extraire."""
    try:
        with zipfile.ZipFile(io.BytesIO(brut)) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            lignes = [f"{i.filename} ({i.file_size} octets)" for i in infos[:maximum]]
            if len(infos) > maximum:
                lignes.append(f"… et {len(infos) - maximum} autre(s) fichier(s)")
            return "\n".join(lignes)
    except zipfile.BadZipFile:
        return ""


def _en_png(octets: bytes) -> bytes:
    """Un BMP (vignette DWG) devient un PNG : le dépôt des visuels ne connaît
    que JPEG/PNG/WebP, et le navigateur affiche mieux un PNG."""
    from PIL import Image
    img = Image.open(io.BytesIO(octets)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# ── Lecture du contenu ──────────────────────────────────────────────────────

def texte_de(nom: str, mime: Optional[str], brut: bytes) -> dict:
    """Le texte d'une pièce, par le moyen qui convient — SYNCHRONE (à appeler
    hors de la boucle). Rend {texte, methode, vignette?, vignette_mime?,
    complement?} ; `texte` vide quand il n'y a rien à lire."""
    from ingestion import parsers
    ext = extension(nom, mime)
    try:
        if ext == ".pdf":
            return {"texte": parsers.lire_pdf(brut), "methode": "texte du PDF (OCR si scanné)"}
        if ext == ".docx":
            return {"texte": parsers.lire_docx(brut), "methode": "texte du document Word"}
        if ext in (".xlsx", ".xlsm", ".xls", ".csv"):
            colonnes, lignes = (parsers.lire_csv(brut) if ext == ".csv" else
                                parsers.lire_xls(brut) if ext == ".xls" else parsers.lire_excel(brut))
            rendu = [" | ".join(colonnes)] + [" | ".join(str(l.get(c, "") or "") for c in colonnes)
                                             for l in lignes[:200]]
            if len(lignes) > 200:
                rendu.append(f"… {len(lignes) - 200} ligne(s) de plus")
            return {"texte": "\n".join(rendu), "methode": f"tableau ({len(lignes)} lignes)"}
        if ext in EXT_TEXTE:
            return {"texte": parsers._decoder(brut), "methode": "texte brut"}
        if ext in EXT_IMAGE or (mime or "").startswith("image/"):
            texte = parsers.ocr_image(brut) if parsers.ocr_disponible() else ""
            return {"texte": texte, "methode": "OCR de l'image" if texte else "image (OCR sans résultat)"}
        if ext == ".dxf":
            return {"texte": texte_dxf(brut), "methode": "textes du plan DXF (cotes, légendes, cartouche)"}
        if ext == ".dwg":
            image, mime_img, version = vignette_dwg(brut)
            complement = (f"Plan {version}. Un DWG est un format binaire propriétaire : ses entités "
                          "ne sont pas lues ici — seule sa vignette intégrée est montrée et décrite. "
                          "Pour le contenu exact, demander le DXF ou le PDF du plan.")
            return {"texte": "", "methode": "vignette du DWG", "vignette": image,
                    "vignette_mime": mime_img, "complement": complement}
        if ext in (".zip",):
            return {"texte": lire_archive(brut), "methode": "contenu de l'archive"}
    except parsers.FichierNonSupporte as e:
        return {"texte": "", "methode": f"non lu ({e})"}
    except Exception as e:  # noqa: BLE001 — une pièce illisible n'est pas une panne
        logger.info("Pièce « %s » illisible : %s", nom, e)
        return {"texte": "", "methode": f"non lu ({type(e).__name__})"}
    return {"texte": "", "methode": "type non lu (téléchargeable seulement)"}


async def decrire_image(octets: bytes, mime: str, consigne: str) -> str:
    """Ce que le modèle de VISION lit dans une image (photo, plan, schéma) —
    même cascade que l'expert vision. Chaîne vide si aucun modèle ne répond."""
    import base64
    try:
        from llm.router import get_vision_candidates
        from langchain_core.messages import HumanMessage
    except Exception:  # noqa: BLE001
        return ""
    candidats = get_vision_candidates()
    if not candidats:
        return ""
    b64 = base64.b64encode(octets).decode("ascii")
    message = HumanMessage(content=[
        {"type": "text", "text": consigne},
        {"type": "image_url", "image_url": {"url": f"data:{mime or 'image/png'};base64,{b64}"}},
    ])
    for llm, label in candidats:
        try:
            reponse = await llm.ainvoke([message])
            texte = reponse.content if isinstance(reponse.content, str) else str(reponse.content)
            if texte and texte.strip():
                return texte.strip()
        except Exception as e:  # noqa: BLE001
            logger.info("Vision indisponible (%s) : %s", label, e)
    return ""


CONSIGNE_VISION = (
    "Tu lis une pièce jointe d'un mail professionnel (paysage / bâtiment). Décris "
    "précisément ce que l'image montre, et TRANSCRIS tout texte lisible (cotes, "
    "légendes, cartouche, montants, noms). Réponds en français, sans introduction. "
    "N'invente rien : ce qui est illisible est dit illisible.")

# LA TRANSCRIPTION, quand tesseract a déjà lu quelque chose : le modèle reçoit
# l'ébauche et l'image, et rend le texte FIDÈLE — accents, montants, tableaux,
# tout ce que l'OCR optique écorche (01/09, Noa : « l'OCR fait encore des
# erreurs »). L'ébauche n'est qu'un guide : la vérité est dans l'image.
CONSIGNE_OCR = (
    "Tu lis une pièce jointe d'un mail professionnel. TRANSCRIS fidèlement TOUT "
    "le texte de l'image, dans l'ordre de lecture ; les tableaux en lignes "
    "« colonne : valeur ». N'invente rien : ce qui est illisible est dit "
    "illisible. Réponds en français, sans introduction ni commentaire. Une "
    "première lecture optique, à corriger d'après l'image : {ebauche}")


async def analyser(nom: str, mime: Optional[str], brut: bytes, proprietaire: str) -> dict:
    """UNE pièce → déposée (téléchargeable, aperçu) et LUE. Ne lève jamais."""
    nom = nom or "piece-jointe"
    taille = len(brut or b"")
    fiche = {"nom": nom, "type": extension(nom, mime).lstrip(".") or (mime or "inconnu"),
             "taille": taille, "texte": "", "methode": "", "tronque": False, "bloc": None, "url": None}
    if not brut:
        fiche["methode"] = "pièce vide"
        return fiche

    # 1. Le dépôt — l'écran d'abord : même illisible, la pièce se télécharge.
    try:
        if est_image(nom, mime):
            from visuels.depot import deposer_octets
            octets_img, mime_img = brut, (mime or "image/png").split(";")[0]
            if mime_img not in ("image/jpeg", "image/png", "image/webp"):
                octets_img, mime_img = _en_png(brut), "image/png"
            cle = deposer_octets(octets_img, mime_img)
            if cle:
                fiche["url"] = f"/api/visuels/{cle}"
                fiche["bloc"] = {"type": "visuel", "titre": nom,
                                 "images": [{"cle": cle, "legende": nom}]}
        else:
            from bureautique.atelier import deposer_fichier
            jeton = deposer_fichier(nom, brut, proprietaire, origine="piece_jointe")
            if jeton:
                fiche["url"] = f"/api/documents/{jeton}"
                fiche["bloc"] = {"type": "fichier", "url": fiche["url"], "nom": nom,
                                 "titre": nom.rsplit(".", 1)[0], "format": fiche["type"], "octets": taille}
    except Exception as e:  # noqa: BLE001
        logger.warning("Dépôt de la pièce « %s » impossible : %s", nom, e)

    if taille > MAX_OCTETS_PIECE:
        fiche["methode"] = f"trop lourde pour être lue ({taille // (1024 * 1024)} Mo) — téléchargeable"
        return fiche

    # 2. La lecture.
    lu = await asyncio.to_thread(texte_de, nom, mime, brut)
    texte, methode = (lu.get("texte") or "").strip(), lu.get("methode") or ""
    complement = lu.get("complement") or ""

    # La vignette d'un DWG devient une image déposée, montrée et décrite.
    if lu.get("vignette"):
        try:
            from visuels.depot import deposer_octets
            png = lu["vignette"] if lu.get("vignette_mime") == "image/png" else _en_png(lu["vignette"])
            cle = deposer_octets(png, "image/png")
            if cle:
                fiche["vignette"] = {"cle": cle, "legende": f"Vignette de {nom}"}
                description = await decrire_image(png, "image/png", CONSIGNE_VISION)
                if description:
                    texte = description
                    methode = "vignette du DWG décrite par la vision"
        except Exception as e:  # noqa: BLE001
            logger.info("Vignette DWG non exploitable : %s", e)

    # LA VISION LIT D'ABORD (01/09, Noa : « l'OCR est bien mais fait encore des
    # erreurs »). Tesseract lit vite mais écorche — accents, montants, colonnes
    # de tableaux. Quand un modèle de vision répond, c'est LUI qui transcrit,
    # l'ébauche tesseract en guide ; sans réponse (pas de clé, panne réseau),
    # le texte tesseract reste, comme avant — le secours ne disparaît pas.
    if est_image(nom, mime):
        ocr_suffisant = len(texte) >= OCR_MINIMUM
        consigne = (CONSIGNE_OCR.format(ebauche=texte[:1500]) if ocr_suffisant
                    else CONSIGNE_VISION)
        description = await decrire_image(brut, (mime or "image/png").split(";")[0], consigne)
        if description:
            if ocr_suffisant:
                texte = description
                methode = "transcription par la vision (OCR en ébauche)"
            else:
                texte = (texte + "\n\n" + description).strip() if texte else description
                methode = ("OCR + description par la vision" if lu.get("texte")
                           else "description par la vision")

    if complement:
        texte = (complement + ("\n\n" + texte if texte else "")).strip()
    if len(texte) > MAX_TEXTE_PIECE:
        fiche["tronque"] = True
        texte = texte[:MAX_TEXTE_PIECE]
    fiche.update({"texte": texte, "methode": methode, "lisible": bool(texte)})
    return fiche
