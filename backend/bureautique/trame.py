"""
REPRODUIRE UN DOCUMENT À L'IDENTIQUE — Word et Excel.

DEMANDE DE NOA (02/09) : « concernant les docs Excel, Word, etc., il doit être
capable en analysant des docs de les reproduire à l'identique, soit en copiant
soit en téléchargeant une copie et en remplaçant le contenu ; et il doit être
capable d'enregistrer des trames qu'il reprend à chaque fois, que ce soit pour
des documents, logo, méthodes, process. »

POURQUOI CE MODULE NE RESSEMBLE PAS À `rendu.py`. Le rendu existant part d'un
document VIERGE (`Document()`, `Workbook()`) et repose un contenu à partir d'un
vocabulaire de blocs. C'est le bon outil pour fabriquer un document neuf, et
c'est le mauvais pour en reproduire un : il ne sait poser que ce que le
vocabulaire nomme, et le devis d'un client porte cent choses qu'aucun
vocabulaire ne nommera jamais — un logo à sa place exacte, une trame de
tableau, une police maison, un pied de page avec un numéro de TVA, des largeurs
de colonnes réglées à la main.

D'OÙ LE PRINCIPE, ET IL TIENT EN UNE PHRASE : ON N'ÉCRIT PAS LE DOCUMENT, ON
OUVRE L'ORIGINAL ET ON N'EN CHANGE QUE LE TEXTE. Tout ce qu'on ne touche pas
reste par construction — styles, en-têtes, images, mise en page, formules. Ce
n'est pas « presque à l'identique », c'est le fichier lui-même.

LE PIÈGE DE WORD, ET C'EST LE CŒUR DU MODULE. Dans un .docx, un paragraphe est
découpé en « runs », un par changement de mise en forme. Word en crée aussi
pour des raisons qui lui appartiennent : une correction orthographique, un
copier-coller, un retour de frappe. « Devis n° DEV-2025-014 » peut donc vivre
en cinq runs, et chercher « DEV-2025-014 » dans chacun d'eux ne trouve RIEN. Un
remplacement naïf échoue silencieusement sur les documents réels, précisément
ceux qui ont été retouchés à la main. On cherche donc dans le texte ENTIER du
paragraphe — mais on n'écrit que dans les fragments concernés.

⚠️ AVANT LE 16/09 (audit D-02), tout le paragraphe modifié était reposé dans le
PREMIER run et les autres vidés : un paragraphe « Client : **Martin** (en
rouge) » perdait son gras et sa couleur dès qu'on y changeait la date, et un
logo porté par un run réécrit pouvait disparaître. Désormais chaque occurrence
est reliée aux nœuds `w:t` qui la portent : le premier reçoit le texte de
remplacement (il en garde la mise en forme), les suivants ne perdent que la
partie remplacée, et tout ce qui entoure l'occurrence — fragments avant et
après, dessins, sauts, champs — reste tel quel. Les remplacements sont
appliqués SIMULTANÉMENT (jamais un remplacement dans le texte d'un autre), et
deux textes cherchés qui se chevauchent dans le document font refuser la table
plutôt que produire un mélange. Zones de texte, contrôles de contenu et
hyperliens sont parcourus ; le texte affiché par un CHAMP Word (date, numéro de
page) n'est jamais réécrit — Word le recalcule — et c'est dit.

CE QU'ON NE FAIT PAS, ET POURQUOI. On n'exécute jamais de code produit par un
modèle — même décision que `modele.py` : le modèle fournit une TABLE de
remplacements (texte → texte), rien d'autre. Il ne choisit ni les styles, ni la
structure, ni les fichiers ouverts.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Optional

logger = logging.getLogger("duret.trame")

# Un document dont on n'extrait aucun texte n'est pas une trame exploitable :
# c'est un scan, un PDF déguisé, ou un fichier qu'on ne sait pas lire. On le
# dit plutôt que de l'enregistrer et de le voir échouer au premier usage.
MIN_TEXTE_UTILE = 20

# Bornes de sûreté. Une trame vit en base : elle doit rester une trame, pas un
# dépôt de fichiers. 12 Mo couvre très largement un devis avec logo et photos.
MAX_OCTETS = 12 * 1024 * 1024
MAX_REMPLACEMENTS = 200

# Ce qu'on sait rouvrir et réécrire.
#
# LE PDF Y EST ENTRÉ LE 15/09, et l'ancien refus disait vrai sur un point : on
# ne RECONSTRUIT pas un PDF sans perdre ce qu'on voulait garder. On ne le
# reconstruit donc pas : on EFFACE le texte cherché à sa place exacte (une
# rédaction qui ne touche ni aux images ni aux tracés) et on REPOSE le nouveau
# texte au même endroit, à la même taille, de la même couleur. Le reste de la
# page — photos, plans, fonds, typographie de tout ce qu'on ne remplace pas —
# est l'original, octet pour octet.
#
# Relevé du 14/09 (fil c9f5a00d) : « tu peux l'enregistrer mais tu devras
# remplacer STUDIO par Symbiose Paysage dans la page de garde » sur un dossier
# de présentation en PDF. Refusé (« un PDF se garde comme pièce »), le modèle a
# FABRIQUÉ un Word de trois pages à la place, l'a enregistré comme trame, puis
# a affirmé au tour suivant que « le modèle est enregistré avec la structure du
# dossier ». La mise en page que la personne montrait n'a jamais été retenue.
TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
# Un dossier de présentation porte des photos pleine page : 12 Mo ne tiennent
# pas un seul d'entre eux. Le plafond d'un PDF est donc le sien.
MAX_OCTETS_PDF = 60 * 1024 * 1024


def plafond_octets(genre: Optional[str]) -> int:
    """Ce qu'une trame de ce type peut peser."""
    return MAX_OCTETS_PDF if genre == "pdf" else MAX_OCTETS


def type_de(nom: str, mime: str = "") -> Optional[str]:
    """« docx », « xlsx », « pdf », ou None si ce n'est pas une trame remplissable."""
    n = (nom or "").lower().strip()
    if n.endswith(".docx") or "wordprocessingml" in (mime or ""):
        return "docx"
    if n.endswith((".xlsx", ".xlsm")) or "spreadsheetml" in (mime or ""):
        return "xlsx"
    if n.endswith(".pdf") or (mime or "").lower() == "application/pdf":
        return "pdf"
    return None


# ── Analyser : ce que le document contient, et ce qui s'y remplace ───────

# UNE VARIABLE SE RECONNAÎT, ELLE NE S'INVENTE PAS. Trois écritures couvrent ce
# qu'on rencontre en pratique : {client}, [[client]] et «client». On ne devine
# JAMAIS qu'un mot est une variable parce qu'il ressemble à un nom : remplacer
# « Dupont » partout dans un devis parce que c'est le client d'origine
# détruirait « rue Dupont » et « société Dupont & Fils ».
_VARIABLE = re.compile(r"\{\{?\s*([A-Za-zÀ-ÿ0-9_ .-]{1,40})\s*\}?\}"
                       r"|\[\[\s*([A-Za-zÀ-ÿ0-9_ .-]{1,40})\s*\]\]")


def _variables(textes: list[str]) -> list[str]:
    """Les noms de variables trouvés, dans l'ordre d'apparition, sans doublon."""
    vues: list[str] = []
    for t in textes:
        for m in _VARIABLE.finditer(t or ""):
            nom = (m.group(1) or m.group(2) or "").strip()
            if nom and nom not in vues:
                vues.append(nom)
    return vues


def _textes_docx(doc) -> list[str]:
    """Tous les textes d'un document Word, EN-TÊTES ET PIEDS COMPRIS.

    Les oublier serait passer à côté de ce qui porte le plus souvent l'identité
    du document : le logo, la raison sociale, le numéro de TVA, la pagination.
    """
    out: list[str] = []
    for p in doc.paragraphs:
        if p.text.strip():
            out.append(p.text)
    for t in doc.tables:
        for ligne in t.rows:
            for cellule in ligne.cells:
                if cellule.text.strip():
                    out.append(cellule.text)
    for section in doc.sections:
        for zone in (section.header, section.footer):
            if zone is None:
                continue
            for p in zone.paragraphs:
                if p.text.strip():
                    out.append(p.text)
    return out


def analyser(octets: bytes, genre: str) -> dict:
    """Ce que porte le document : sa structure, son texte, ses variables.

    Sert à MONTRER une trame avant de l'enregistrer, et à dire ce qu'on saura
    y remplacer. Ne modifie rien.
    """
    if genre == "docx":
        import docx  # python-docx, déjà dans requirements

        doc = docx.Document(io.BytesIO(octets))
        textes = _textes_docx(doc)
        images = len(doc.inline_shapes)
        # `sections` porte les en-têtes ; on dit s'il y en a, parce que c'est
        # ce qui distingue un papier à en-tête d'une page blanche.
        entete = any((s.header is not None
                      and any(p.text.strip() for p in s.header.paragraphs))
                     for s in doc.sections)
        return {
            "genre": "docx",
            "paragraphes": len(doc.paragraphs),
            "tableaux": len(doc.tables),
            "images": images,
            "entete": entete,
            "textes": textes,
            "variables": _variables(textes),
        }

    if genre == "xlsx":
        from openpyxl import load_workbook

        classeur = load_workbook(io.BytesIO(octets), data_only=False)
        textes: list[str] = []
        feuilles = []
        for feuille in classeur.worksheets:
            lignes = feuille.max_row or 0
            colonnes = feuille.max_column or 0
            feuilles.append({"nom": feuille.title, "lignes": lignes,
                             "colonnes": colonnes})
            for ligne in feuille.iter_rows():
                for cellule in ligne:
                    v = cellule.value
                    if isinstance(v, str) and v.strip():
                        textes.append(v)
        return {
            "genre": "xlsx",
            "feuilles": feuilles,
            "textes": textes,
            "variables": _variables(textes),
        }

    if genre == "pdf":
        import fitz  # PyMuPDF, déjà dans requirements (rendu pour la vision)

        doc = fitz.open(stream=octets, filetype="pdf")
        try:
            textes: list[str] = []
            images = 0
            for page in doc:
                images += len(page.get_images(full=False))
                for ligne in _lignes_pdf(page):
                    t = "".join(g["c"] for g in ligne).strip()
                    if t and t not in textes:
                        textes.append(t)
            return {"genre": "pdf", "pages": doc.page_count, "images": images,
                    "textes": textes, "variables": _variables(textes)}
        finally:
            doc.close()

    raise ValueError(f"Type de trame non géré : {genre!r}")


# ── Le PDF, glyphe par glyphe ────────────────────────────────────────────
#
# LE PIÈGE DES LETTRES EN DOUBLE. Un titre de page de garde est souvent dessiné
# DEUX ou TROIS fois, décalé d'une fraction de point, pour épaissir le trait ou
# poser un contour : l'extraction du Drive rendait « SSSTTTUUUDDDIIIOOO » et
# « PPRROOJJEETT ». Chercher « STUDIO » dans ce texte ne trouve rien — le même
# silence que les runs de Word. On regroupe donc les glyphes identiques qui se
# CHEVAUCHENT (plus de la moitié de leur surface) en un seul, qui garde tous
# ses rectangles : la recherche voit « STUDIO », la rédaction efface les trois
# tracés.

def _chevauche(a, b) -> bool:
    import fitz
    ra, rb = fitz.Rect(a), fitz.Rect(b)
    inter = ra & rb
    if inter.is_empty:
        return False
    plus_petite = min(abs(ra.width * ra.height), abs(rb.width * rb.height)) or 1.0
    return abs(inter.width * inter.height) / plus_petite >= 0.5


def _lignes_pdf(page) -> list[list[dict]]:
    """Les lignes de la page, chacune une liste de glyphes UNIQUES :
    {c, rects, origine, taille, couleur, police}."""
    brut = page.get_text("rawdict")
    lignes: list[list[dict]] = []
    for bloc in brut.get("blocks", []):
        if bloc.get("type") != 0:
            continue
        for ligne in bloc.get("lines", []):
            glyphes: list[dict] = []
            for span in ligne.get("spans", []):
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    if not c:
                        continue
                    precedent = glyphes[-1] if glyphes else None
                    # Doublon interfolié (S S S T T T) : même lettre qui chevauche
                    # la précédente.
                    if precedent and precedent["c"] == c and _chevauche(precedent["rects"][0], ch["bbox"]):
                        precedent["rects"].append(ch["bbox"])
                        continue
                    glyphes.append({"c": c, "rects": [ch["bbox"]], "origine": ch.get("origin"),
                                    "taille": span.get("size", 11), "couleur": span.get("color", 0),
                                    "police": span.get("font", ""), "drapeaux": span.get("flags", 0)})
            if glyphes:
                lignes.append(glyphes)
    # Doublon en lignes entières (le titre dessiné trois fois comme trois
    # objets) : une ligne dont chaque glyphe chevauche celui d'une ligne déjà
    # vue, au même texte, est la même ligne.
    uniques: list[list[dict]] = []
    for ligne in lignes:
        texte = "".join(g["c"] for g in ligne)
        jumelle = next((u for u in uniques
                        if "".join(g["c"] for g in u) == texte
                        and all(_chevauche(a["rects"][0], b["rects"][0]) for a, b in zip(u, ligne))), None)
        if jumelle is not None:
            for a, b in zip(jumelle, ligne):
                a["rects"].extend(b["rects"])
            continue
        uniques.append(ligne)
    return uniques


def _sans_casse(texte: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return t.lower()


def _occurrences_pdf(lignes, cherche: str, approche: bool):
    """(ligne, début, fin) de chaque occurrence ; `approche` ignore casse et accents.

    L'approche reste sûre sur un PDF : on compare glyphe à glyphe, donc les
    indices trouvés désignent exactement les lettres à effacer.
    """
    trouves = []
    for ligne in lignes:
        if approche:
            # Normaliser lettre par lettre garde l'alignement des indices :
            # « É » donne « e », une seule lettre.
            texte = "".join((_sans_casse(g["c"]) or g["c"])[:1] for g in ligne)
            motif = "".join((_sans_casse(c) or c)[:1] for c in cherche)
        else:
            texte = "".join(g["c"] for g in ligne)
            motif = cherche
        depart = 0
        while motif:
            i = texte.find(motif, depart)
            if i < 0:
                break
            trouves.append((ligne, i, i + len(motif)))
            depart = i + len(motif)
    return trouves


def _police_pdf(glyphe: dict) -> str:
    """La police de base la plus proche : grasse ou non, empattée ou non."""
    nom = (glyphe.get("police") or "").lower()
    gras = bool(glyphe.get("drapeaux", 0) & 16) or any(m in nom for m in ("bold", "black", "heavy", "semibold"))
    empattee = any(m in nom for m in ("times", "serif", "garamond", "georgia", "roman")) and "sans" not in nom
    if empattee:
        return "tibo" if gras else "tiro"
    return "hebo" if gras else "helv"


def _remplir_pdf(octets: bytes, table: dict) -> tuple[bytes, int]:
    import fitz

    doc = fitz.open(stream=octets, filetype="pdf")
    faits = 0
    try:
        # Exact d'abord, dans tout le document ; l'approché (casse, accents)
        # seulement pour un texte introuvable tel quel — « studio » demandé,
        # « STUDIO » imprimé.
        par_page = [(_page, _lignes_pdf(_page)) for _page in doc]
        approche = {}
        for cherche in table:
            approche[cherche] = not any(_occurrences_pdf(l, cherche, False) for _, l in par_page)

        for page, lignes in par_page:
            poses = []
            for cherche, remplace in table.items():
                for ligne, debut, fin in _occurrences_pdf(lignes, cherche, approche[cherche]):
                    glyphes = ligne[debut:fin]
                    rect = fitz.Rect(glyphes[0]["rects"][0])
                    for g in glyphes:
                        for r in g["rects"]:
                            rect |= fitz.Rect(r)
                    toute_la_ligne = "".join(g["c"] for g in ligne).strip() == "".join(
                        g["c"] for g in glyphes).strip()
                    suivant = ligne[fin] if fin < len(ligne) else None
                    poses.append({"rect": rect, "texte": str(remplace), "modele": glyphes[0],
                                  "entiere": toute_la_ligne,
                                  "limite_droite": (fitz.Rect(suivant["rects"][0]).x0 if suivant
                                                    else page.rect.width - page.rect.width * 0.04)})
            if not poses:
                continue
            for p in poses:
                # `fill=False` : AUCUN rectangle blanc. Sur une page de garde
                # posée sur une photo, un cache blanc serait pire que le mot.
                page.add_redact_annot(p["rect"], fill=False)
            try:
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                      graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0))
            except TypeError:  # PyMuPDF plus ancien : pas de réglage des tracés
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            for p in poses:
                modele = p["modele"]
                taille = float(modele.get("taille") or 11)
                police = _police_pdf(modele)
                couleur = int(modele.get("couleur") or 0)
                rgb = (((couleur >> 16) & 255) / 255, ((couleur >> 8) & 255) / 255, (couleur & 255) / 255)
                origine = modele.get("origine") or (p["rect"].x0, p["rect"].y1)
                largeur = fitz.get_text_length(p["texte"], fontname=police, fontsize=taille)
                if p["entiere"]:
                    # Une ligne entière (titre de page de garde) garde son CENTRE :
                    # « Symbiose Paysage » est plus long que « STUDIO », et
                    # l'aligner à gauche décentrerait la page.
                    centre = (p["rect"].x0 + p["rect"].x1) / 2
                    marge = page.rect.width * 0.04
                    dispo = 2 * min(centre - marge, page.rect.width - marge - centre)
                    x = None
                else:
                    dispo = p["limite_droite"] - p["rect"].x0
                    x = p["rect"].x0
                if largeur > dispo > 0:
                    taille = max(taille * dispo / largeur, taille * 0.5)
                    largeur = fitz.get_text_length(p["texte"], fontname=police, fontsize=taille)
                if x is None:
                    x = (p["rect"].x0 + p["rect"].x1) / 2 - largeur / 2
                page.insert_text((x, origine[1]), p["texte"], fontname=police,
                                 fontsize=taille, color=rgb)
                faits += 1
        return doc.tobytes(garbage=3, deflate=True), faits
    finally:
        doc.close()


def textes_proches(textes: list[str], cherche: str, nombre: int = 3) -> list[str]:
    """Les textes du document qui ressemblent le plus à ce qui n'a pas été trouvé.

    « STUDIO » cherché, « Studio Lavèze » imprimé : sans cette liste, le modèle
    relance le même remplacement (quatre fois le 14/09) ; avec, il reprend
    l'orthographe exacte, ou dit que le texte n'existe pas.
    """
    from difflib import get_close_matches
    cle = _sans_casse(cherche).strip()
    if not cle:
        return []
    uniques = []
    for t in textes or []:
        t = " ".join(str(t).split())
        if t and t not in uniques:
            uniques.append(t)
    contenant = [t for t in uniques if cle in _sans_casse(t)]
    if contenant:
        return [t[:90] for t in contenant[:nombre]]
    par_cle = {_sans_casse(t)[:120]: t for t in uniques}
    proches = get_close_matches(cle, list(par_cle), n=nombre, cutoff=0.6)
    return [par_cle[p][:90] for p in proches]


def exploitable(analyse: dict) -> tuple[bool, str]:
    """Cette trame pourra-t-elle servir ? Et sinon, pourquoi ?"""
    texte = "".join(analyse.get("textes") or [])
    if len(texte.strip()) < MIN_TEXTE_UTILE:
        return False, ("Ce document ne contient presque aucun texte : c'est "
                       "probablement un scan ou une image. On ne pourra rien y "
                       "remplacer.")
    return True, ""


# ── Remplir : l'original, avec un autre contenu ──────────────────────────

class RemplacementsContradictoires(ValueError):
    """Deux textes cherchés se chevauchent dans le document : lequel l'emporte ?"""


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_XML_ESPACE = "{http://www.w3.org/XML/1998/namespace}space"


def _dans_ce_paragraphe(noeud, paragraphe) -> bool:
    """Le nœud appartient-il à CE paragraphe, et pas à un paragraphe imbriqué
    (zone de texte) ni au texte d'un champ Word ?"""
    parent = noeud.getparent()
    while parent is not None and parent is not paragraphe:
        if parent.tag in (_W + "p", _W + "txbxContent"):
            return False
        parent = parent.getparent()
    return parent is paragraphe


def _segments(paragraphe) -> tuple[list, bool]:
    """Les morceaux de texte du paragraphe, dans l'ordre : (nœud w:t ou None, texte).

    Une tabulation ou un saut de ligne compte dans le texte logique (comme
    `paragraph.text`) mais ne se remplace pas : son nœud vaut None. Le texte
    affiché par un champ (entre « separate » et « end ») est rendu None aussi :
    on le lit, on ne l'écrit pas. Rend aussi `champ_vu`.
    """
    morceaux, dans_resultat_champ, champ_vu = [], 0, False
    for el in paragraphe.iter():
        if el is paragraphe or not _dans_ce_paragraphe(el, paragraphe):
            continue
        tag = el.tag
        if tag == _W + "fldChar":
            genre = el.get(_W + "fldCharType")
            if genre == "separate":
                dans_resultat_champ += 1
                champ_vu = True
            elif genre == "end" and dans_resultat_champ:
                dans_resultat_champ -= 1
        elif tag == _W + "t":
            texte = el.text or ""
            if texte:
                champ_simple = any(a.tag == _W + "fldSimple" for a in el.iterancestors())
                morceaux.append((None if dans_resultat_champ or champ_simple else el, texte))
        elif tag == _W + "tab" and el.getparent() is not None and el.getparent().tag == _W + "r":
            morceaux.append((None, "\t"))
        elif tag in (_W + "br", _W + "cr"):
            morceaux.append((None, "\n"))
        elif tag == _W + "fldSimple":
            champ_vu = True
    return morceaux, champ_vu


def _occurrences(texte: str, table: dict) -> list[tuple[int, int, str]]:
    """Toutes les occurrences de toutes les clés, dans le texte D'ORIGINE.

    Lève `RemplacementsContradictoires` quand deux occurrences de clés
    différentes se chevauchent (« DEV-2025 » et « 2025-014 » dans
    « DEV-2025-014 ») : les appliquer l'une après l'autre dépendrait de l'ordre
    de la table, et produirait un mélange.
    """
    trouvees = []
    for cherche, remplace in table.items():
        depart = texte.find(cherche)
        while depart != -1:
            trouvees.append((depart, depart + len(cherche), remplace, cherche))
            depart = texte.find(cherche, depart + len(cherche))
    trouvees.sort()
    for (a0, a1, _, ka), (b0, b1, _, kb) in zip(trouvees, trouvees[1:]):
        if b0 < a1 and ka != kb:
            raise RemplacementsContradictoires(
                f"« {ka} » et « {kb} » se chevauchent dans « {texte[max(0, a0 - 20):b1 + 20]} » : "
                "garde un seul des deux textes cherchés (le plus long, en général).")
    return [(debut, fin, remplace) for debut, fin, remplace, _ in trouvees]


def _poser_texte(noeud, texte: str) -> None:
    # Les caractères de contrôle ne sont pas des instructions de mise en page
    # dans w:t. On remplace ce seul nœud, jamais le run et ses dessins/champs.
    import re
    morceaux = re.split(r"(\r\n|\r|\n|\t)", texte)
    noeud.text = morceaux[0]
    if morceaux[0] != morceaux[0].strip() or "  " in morceaux[0]:
        noeud.set(_XML_ESPACE, "preserve")
    precedent = noeud
    for morceau in morceaux[1:]:
        if not morceau:
            continue
        if morceau in ("\r\n", "\r", "\n", "\t"):
            suivant = noeud.makeelement(_W + ("tab" if morceau == "\t" else "br"))
        else:
            suivant = noeud.makeelement(_W + "t")
            suivant.text = morceau
            if morceau != morceau.strip() or "  " in morceau:
                suivant.set(_XML_ESPACE, "preserve")
        precedent.addnext(suivant)
        precedent = suivant


def _remplacer_dans_paragraphe(paragraphe, table: dict, limites: Optional[set] = None) -> int:
    """Remplace dans UN paragraphe Word en ne réécrivant que les fragments visés.

    Rend le nombre d'OCCURRENCES remplacées. `paragraphe` : un paragraphe
    python-docx ou un élément `w:p` brut. `limites` reçoit, le cas échéant, ce
    qui n'a pas pu être remplacé et pourquoi.
    """
    p = getattr(paragraphe, "_p", paragraphe)
    morceaux, champ_vu = _segments(p)
    texte = "".join(t for _, t in morceaux)
    if not texte or not any(k in texte for k in table):
        return 0
    occurrences = _occurrences(texte, table)
    # Position de départ de chaque morceau dans le texte logique.
    positions, curseur = [], 0
    for _, t in morceaux:
        positions.append(curseur)
        curseur += len(t)
    faits = 0
    # DE DROITE À GAUCHE : un remplacement ne décale pas les positions des
    # occurrences situées avant lui.
    for debut, fin, remplace in reversed(occurrences):
        touches = [i for i, (n, t) in enumerate(morceaux)
                   if positions[i] < fin and positions[i] + len(t) > debut]
        if not touches or any(morceaux[i][0] is None for i in touches):
            # L'occurrence traverse une tabulation, un saut ou le texte d'un
            # champ : la réécrire casserait ce qui la sépare. On la laisse.
            if limites is not None:
                limites.add("un texte cherché traverse une tabulation, un saut de ligne ou un "
                            "champ Word (date, numéro de page) : laissé tel quel")
            continue
        premier = touches[0]
        for rang, i in enumerate(touches):
            noeud, t = morceaux[i]
            local_debut = max(0, debut - positions[i])
            local_fin = min(len(t), fin - positions[i])
            if rang == 0:
                nouveau = t[:local_debut] + remplace + (t[local_fin:] if len(touches) == 1 else "")
            elif i == touches[-1]:
                nouveau = t[local_fin:]
            else:
                nouveau = ""
            # Les positions restent celles du texte initial pendant toute la
            # passe. La conversion des sauts est différée jusqu'à sa fin.
            morceaux[i] = (noeud, nouveau)
        faits += 1
    for noeud, nouveau in morceaux:
        if noeud is not None and nouveau != (noeud.text or ""):
            _poser_texte(noeud, nouveau)
    if champ_vu and limites is not None and faits:
        limites.add("le texte affiché par un champ Word (date, numéro de page…) n'est pas "
                    "réécrit : Word le recalcule à l'ouverture")
    return faits


def _paragraphes_de(racine):
    """Tous les paragraphes d'une partie Word : corps, tableaux imbriqués, zones de
    texte, contrôles de contenu. Les secours VML d'une zone de texte
    (`mc:Fallback`) sont inclus — ils portent le même texte, et un lecteur
    ancien les affiche — mais marqués pour ne pas compter deux fois."""
    for p in racine.iter(_W + "p"):
        parent, secours = p.getparent(), False
        while parent is not None:
            if parent.tag.endswith("}Fallback"):
                secours = True
                break
            parent = parent.getparent()
        yield p, secours


def _remplir_xlsx(octets: bytes, propre: dict, limites: set) -> tuple[bytes, int]:
    """Les textes des cellules d'un classeur, formules et styles INTACTS."""
    from openpyxl import load_workbook

    # `data_only=False` GARDE LES FORMULES. À True, openpyxl ne lirait que la
    # dernière valeur calculée par Excel et les écrirait en dur : le classeur
    # rendu serait mort, ses totaux figés.
    classeur = load_workbook(io.BytesIO(octets), data_only=False)
    faits = 0
    for feuille in classeur.worksheets:
        for ligne in feuille.iter_rows():
            for cellule in ligne:
                v = cellule.value
                if not isinstance(v, str):
                    continue
                if v.startswith("="):
                    # UNE FORMULE NE SE RÉÉCRIT PAS PAR REMPLACEMENT DE TEXTE
                    # (audit D-02) : « B3 » cherché dans « =B3*B4 » casserait le
                    # calcul. Elle reste telle quelle, et c'est dit.
                    if any(k in v for k in propre):
                        limites.add("une formule Excel contenait un texte cherché : elle n'a pas "
                                    "été modifiée (une formule ne se change que sur demande explicite)")
                    continue
                neuf = v
                for cherche, remplace in propre.items():
                    if cherche in neuf:
                        neuf = neuf.replace(cherche, remplace)
                if neuf != v:
                    # Écrire la cellule ne touche pas à son style : openpyxl les
                    # porte séparément de la valeur.
                    cellule.value = neuf
                    faits += 1
    sortie = io.BytesIO()
    classeur.save(sortie)
    return sortie.getvalue(), faits


def _controle():
    """Le module de contrôle, voisin de celui-ci — même chargé hors du paquet
    (les bancs chargent ce fichier seul)."""
    try:
        from bureautique import controle
        if hasattr(controle, "comparer_docx"):
            return controle
    except ImportError:
        pass
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "bureautique_controle", pathlib.Path(__file__).with_name("controle.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def remplir_detaille(octets: bytes, genre: str, table: dict) -> dict:
    """Comme `remplir`, avec le détail : {octets, remplacements, limites, controle}.

    Le contrôle structurel est propre à Word ; Excel et PDF disent leurs limites.
    """
    if genre == "xlsx":
        propre_x = {str(k): str(v) for k, v in (table or {}).items() if str(k).strip()}
        if not propre_x:
            raise ValueError("Aucun texte à chercher n'a été fourni.")
        if len(propre_x) > MAX_REMPLACEMENTS:
            raise ValueError(f"Trop de remplacements ({len(propre_x)}, plafond {MAX_REMPLACEMENTS}).")
        limites_x: set = set()
        produits, faits = _remplir_xlsx(octets, propre_x, limites_x)
        return {"octets": produits, "remplacements": faits, "limites": sorted(limites_x),
                "controle": None}
    if genre != "docx":
        produits, faits = remplir(octets, genre, table)
        # Un PDF n'a pas de structure éditable : le texte est effacé et reposé à
        # sa place (`_remplir_pdf`). Ce n'est pas un Word fidèle, et c'est dit.
        limites_p = (["PDF : le texte est effacé puis reposé à la même place, dans une police "
                      "proche ; ce n'est pas un document Word éditable"]
                     if genre == "pdf" and faits else [])
        return {"octets": produits, "remplacements": faits, "limites": limites_p, "controle": None}
    import docx

    propre = {str(k): str(v) for k, v in (table or {}).items() if str(k).strip()}
    if not propre:
        raise ValueError("Aucun texte à chercher n'a été fourni.")
    if len(propre) > MAX_REMPLACEMENTS:
        raise ValueError(f"Trop de remplacements ({len(propre)}, plafond {MAX_REMPLACEMENTS}).")
    doc = docx.Document(io.BytesIO(octets))
    limites: set = set()
    faits = 0
    # LE CORPS, PUIS CHAQUE EN-TÊTE ET PIED DE PAGE DISTINCT (première page,
    # pages paires comprises) : c'est là que vivent la date, la référence et le
    # nom du client. Une même partie partagée par plusieurs sections n'est
    # traitée qu'une fois.
    parties, vues = [doc.element.body], set()
    for section in doc.sections:
        for zone in (section.header, section.footer, section.first_page_header,
                     section.first_page_footer, section.even_page_header, section.even_page_footer):
            try:
                if zone is None or zone.is_linked_to_previous:
                    continue
                element = zone._element
            except Exception:  # noqa: BLE001 — une zone absente n'est pas une erreur
                continue
            if id(element) not in vues:
                vues.add(id(element))
                parties.append(element)
    for partie in parties:
        for p, secours in _paragraphes_de(partie):
            n = _remplacer_dans_paragraphe(p, propre, limites)
            if not secours:
                faits += n
    sortie = io.BytesIO()
    doc.save(sortie)
    produits = sortie.getvalue()
    textes_attendus = {part.partname.lstrip("/"): _controle().textes_xml(part.blob)
                       for part in doc.part.package.parts
                       if str(part.partname).startswith("/word/") and str(part.partname).endswith(".xml")
                       and hasattr(part, "element")}
    controle = _controle().comparer_docx(octets, produits, textes_attendus=textes_attendus)
    if not controle["ok"]:
        # UN FICHIER ABÎMÉ NE SORT PAS (audit D-02) : on garde l'original
        # intact et on dit ce qui a été détecté.
        raise ValueError("Le document produit ne passe pas le contrôle : "
                         + " ; ".join(controle["problemes"]) + ". L'original n'a pas été modifié.")
    return {"octets": produits, "remplacements": faits, "limites": sorted(limites),
            "controle": controle}


def remplir(octets: bytes, genre: str, table: dict) -> tuple[bytes, int]:
    """L'original, avec les textes de `table` remplacés. Rend (octets, nombre).

    Tout ce qui n'est pas dans la table reste STRICTEMENT intact : styles,
    en-têtes, pieds de page, images, largeurs de colonnes, formules Excel. On
    n'a rien reconstruit, on a modifié.
    """
    if not isinstance(table, dict) or not table:
        raise ValueError("Aucun remplacement demandé.")
    if len(table) > MAX_REMPLACEMENTS:
        raise ValueError(f"Trop de remplacements ({len(table)}, plafond "
                         f"{MAX_REMPLACEMENTS}).")
    # Les clés vides remplaceraient PARTOUT : on les écarte avant d'ouvrir quoi
    # que ce soit, plutôt que de découvrir le dégât dans le fichier rendu.
    propre = {str(k): str(v) for k, v in table.items() if str(k).strip()}
    if not propre:
        raise ValueError("Aucun texte à chercher n'a été fourni.")

    if genre == "docx":
        resultat = remplir_detaille(octets, genre, propre)
        return resultat["octets"], resultat["remplacements"]

    if genre == "xlsx":
        return _remplir_xlsx(octets, propre, set())

    if genre == "pdf":
        return _remplir_pdf(octets, propre)

    raise ValueError(f"Type de trame non géré : {genre!r}")
