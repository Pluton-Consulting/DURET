"""
Rendu d'un document : même description, trois formats.

Le flux d'éléments est parcouru UNE fois et écrit au fil de l'eau. Rien n'est
accumulé : c'est ce qui permet un document de plusieurs centaines de pages sans
rapport avec la mémoire disponible.

Chaque format honore ce qu'il sait faire :
  * .docx  en-tête et pied de section, numérotation par champ Word, styles de
           titre natifs (donc sommaire automatique possible côté Word).
  * .pdf   en-tête et pied dessinés sur CHAQUE page, numérotation calculée au
           tirage, tableaux qui se poursuivent d'une page à l'autre.
  * .xlsx  un onglet par « feuille », en-tête et pied d'impression, en-têtes de
           colonnes figées.

Un bloc qu'un format ne peut pas honorer est DÉGRADÉ, jamais ignoré : une
« feuille » dans un .docx devient un tableau précédé de son nom. Le lecteur voit
alors une mise en forme imparfaite plutôt qu'un trou, et un trou est ce qu'on ne
remarque qu'une fois le document envoyé.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("duret.bureautique.rendu")


def _image(e_ou_nom) -> str | None:
    """Le chemin de l'image rangée d'un bloc (ou d'un nom), ou None."""
    from bureautique.atelier import chemin_image
    nom = e_ou_nom.get("fichier") if isinstance(e_ou_nom, dict) else e_ou_nom
    return chemin_image(nom) if nom else None


def _dimensions(chemin: str) -> tuple[int, int]:
    """(largeur, hauteur) en pixels — Pillow, ou un carré si elle manque."""
    try:
        from PIL import Image
        with Image.open(chemin) as img:
            return img.size
    except Exception:  # noqa: BLE001
        return 100, 100


def _absente(e: dict) -> str:
    """Le texte qui tient la place d'une image introuvable : un trou se voit."""
    return "[image indisponible" + (f" : {e['legende']}" if e.get("legende") else "") + "]"


def rendre(entete: dict, elements, sortie: str) -> str:
    fmt = entete.get("format", "docx")
    if fmt == "xlsx":
        return _xlsx(entete, elements, sortie)
    if fmt == "pdf":
        return _pdf(entete, elements, sortie)
    return _docx(entete, elements, sortie)


# ── Word ──────────────────────────────────────────────────────────────
#
# UN WORD SOIGNÉ PAR DÉFAUT (15/09, Duret). Relevé de Noa sur un mémoire
# technique : « la mise en page est horrible, les phrases se chevauchent et il
# n'y a que des bullet points ». Le rendu partait du gabarit VIERGE de
# python-docx : aucune police nommée (des polices de THÈME, que chaque logiciel
# résout à sa façon — l'aperçu du chat et certains traitements de texte tassent
# alors les lignes les unes sur les autres), aucun interligne, aucune couleur,
# des tableaux nus, ni page de garde ni sommaire. On ne demande pas au modèle
# d'y penser : tout Word sort avec la mise en page de la maison.
#   * styles EXPLICITES (police, taille, interligne 1,15, espacements) — plus
#     aucune dépendance au thème ;
#   * titres à la couleur de la charte, qui ne restent jamais seuls en bas de page ;
#   * une PAGE DE GARDE (logo, titre, sous-titre, date) et un SOMMAIRE dès que
#     le document est long ; en-tête et pied discrets, pages numérotées ;
#   * tableaux habillés (en-tête à la couleur de la charte, répété à chaque page) ;
#   * un paragraphe qui contient des tirets en début de ligne devient une vraie
#     liste, et « **gras** » devient du gras — le modèle écrit souvent ainsi.
# Arial plutôt que Calibri : présente sur Windows, Mac ET dans le navigateur
# (l'aperçu du chat) — une police absente est remplacée, et c'est là que les
# lignes se tassaient.
POLICE = "Arial"
SEUIL_PAGE_DE_GARDE = 12   # éléments
SEUIL_SOMMAIRE = 5         # titres de niveau 1 ou 2
_RE_PUCE = __import__("re").compile(r"^\s*(?:[-–•*·▪]|\d{1,2}[.)])\s+")
_RE_GRAS = __import__("re").compile(r"\*\*(.+?)\*\*")
_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre")


def _police(style_ou_run, nom: str = POLICE) -> None:
    """Police nommée pour TOUS les jeux de caractères, attributs de thème retirés."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    element = style_ou_run.element
    rpr = element.get_or_add_rPr()
    polices = rpr.find(qn("w:rFonts"))
    if polices is None:
        polices = OxmlElement("w:rFonts")
        rpr.insert(0, polices)
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        polices.attrib.pop(qn(attr), None)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        polices.set(qn(attr), nom)


def _styles_maison(doc, charte: str, charte_fond: str) -> None:
    from docx.enum.text import WD_LINE_SPACING
    from docx.shared import Pt, RGBColor
    styles = doc.styles

    def regler(nom, taille, couleur="262626", gras=False, avant=0, apres=6, interligne=1.15,
               garder_avec_suivant=False):
        try:
            s = styles[nom]
        except KeyError:
            return None
        _police(s)
        s.font.size = Pt(taille)
        s.font.bold = gras
        s.font.italic = False
        s.font.color.rgb = RGBColor.from_string(couleur)
        f = s.paragraph_format
        f.space_before, f.space_after = Pt(avant), Pt(apres)
        f.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        f.line_spacing = interligne
        f.keep_with_next = garder_avec_suivant
        return s

    regler("Normal", 10.5)
    regler("Title", 24, charte_fond, gras=True, apres=4, interligne=1.0)
    regler("Subtitle", 13, "595959", apres=12)
    regler("Heading 1", 15, charte, gras=True, avant=18, apres=6, interligne=1.0, garder_avec_suivant=True)
    regler("Heading 2", 12.5, charte, gras=True, avant=12, apres=4, interligne=1.0, garder_avec_suivant=True)
    regler("Heading 3", 11, charte_fond, gras=True, avant=10, apres=3, interligne=1.0, garder_avec_suivant=True)
    regler("Heading 4", 10.5, "404040", gras=True, avant=8, apres=2, interligne=1.0, garder_avec_suivant=True)
    for nom in ("List Bullet", "List Number"):
        regler(nom, 10.5, apres=3)


def _ecrire_riche(paragraphe, texte: str, mise_en_forme: dict | None = None) -> None:
    """Écrit un texte en honorant « **gras** » ; la mise en forme du bloc s'applique à chaque morceau."""
    from docx.shared import Pt, RGBColor
    from bureautique.modele import COULEURS, TAILLES
    mise_en_forme = mise_en_forme or {}
    morceaux = _RE_GRAS.split(texte)
    for i, morceau in enumerate(morceaux):
        if not morceau:
            continue
        run = paragraphe.add_run(morceau)
        run.font.bold = bool(mise_en_forme.get("gras")) or (i % 2 == 1)
        run.font.italic = bool(mise_en_forme.get("italique"))
        if mise_en_forme.get("taille"):
            run.font.size = Pt(TAILLES.get(mise_en_forme["taille"], 10.5))
        if mise_en_forme.get("couleur"):
            run.font.color.rgb = RGBColor.from_string(COULEURS[mise_en_forme["couleur"]])


def _paragraphe_docx(doc, e: dict) -> None:
    """Un paragraphe du modèle : ses lignes à tiret deviennent une liste, le reste des paragraphes."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    lignes = [l for l in str(e.get("texte") or "").split("\n")]
    if len(lignes) == 1:
        lignes = [lignes[0]]
    for ligne in lignes:
        if not ligne.strip():
            continue
        puce = _RE_PUCE.match(ligne)
        if puce and len(lignes) > 1:
            numero = puce.group(0).strip()[:1].isdigit()
            p = doc.add_paragraph(style="List Number" if numero else "List Bullet")
            _ecrire_riche(p, ligne[puce.end():].strip(), e)
            continue
        p = doc.add_paragraph()
        _ecrire_riche(p, ligne.strip(), e)
        if e.get("centre"):
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _page_de_garde(doc, entete: dict, charte: str) -> None:
    import datetime
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    logo = _image(entete.get("entete_image_fichier"))
    haut = doc.add_paragraph()
    haut.paragraph_format.space_before = Pt(90 if not logo else 40)
    if logo:
        haut.alignment = WD_ALIGN_PARAGRAPH.CENTER
        haut.add_run().add_picture(logo, height=Cm(3))
        doc.add_paragraph().paragraph_format.space_after = Pt(60)
    titre = doc.add_paragraph(style="Title")
    # Un filet de la couleur de la maison sous le titre. L'ORDRE DES ÉLÉMENTS
    # COMPTE (schéma WordprocessingML : pStyle … pBdr … jc) : un filet posé
    # après l'alignement fait dire à Word « contenu illisible ». Il est donc
    # posé juste derrière le style, AVANT tout autre réglage du paragraphe.
    ppr = titre._p.get_or_add_pPr()
    bordure = OxmlElement("w:pBdr")
    bas = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "18"), ("w:space", "6"), ("w:color", charte)):
        bas.set(qn(k), v)
    bordure.append(bas)
    style_du_paragraphe = ppr.find(qn("w:pStyle"))
    if style_du_paragraphe is not None:
        style_du_paragraphe.addnext(bordure)
    else:
        ppr.insert(0, bordure)
    titre.alignment = WD_ALIGN_PARAGRAPH.LEFT
    titre.add_run(entete["titre"])
    if entete.get("sous_titre"):
        doc.add_paragraph(entete["sous_titre"], style="Subtitle")
    maintenant = datetime.date.today()
    bas_de_page = doc.add_paragraph()
    bas_de_page.paragraph_format.space_before = Pt(200)
    run = bas_de_page.add_run(" · ".join(x for x in (entete.get("entete"),
                                                    f"{_MOIS[maintenant.month - 1]} {maintenant.year}") if x))
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor.from_string("595959")
    doc.add_page_break()


def _sommaire(doc) -> None:
    """Un champ Word « table des matières » : Word le calcule à l'ouverture."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc.add_paragraph("Sommaire", style="Heading 1")
    p = doc.add_paragraph()
    run = p.add_run()
    debut = OxmlElement("w:fldChar"); debut.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-2" \\h \\z \\u '
    separe = OxmlElement("w:fldChar"); separe.set(qn("w:fldCharType"), "separate")
    run._r.append(debut); run._r.append(instr); run._r.append(separe)
    texte = p.add_run("Le sommaire se met à jour à l'ouverture dans Word (sinon : clic droit → Mettre à jour le champ).")
    texte.font.italic = True
    fin = OxmlElement("w:fldChar"); fin.set(qn("w:fldCharType"), "end")
    p.add_run()._r.append(fin)
    # Word propose de mettre les champs à jour en ouvrant le document.
    reglages = doc.settings.element
    maj = OxmlElement("w:updateFields"); maj.set(qn("w:val"), "true")
    # À SA PLACE dans l'ordre du schéma (avant hdrShapeDefaults, compat, rsids…).
    suivants = {qn("w:" + n) for n in (
        "hdrShapeDefaults", "footnotePr", "endnotePr", "compat", "docVars", "rsids",
        "attachedSchema", "themeFontLang", "clrSchemeMapping", "doNotIncludeSubdocsInStats",
        "doNotAutoCompressPictures", "forceUpgrade", "captions", "readModeInkLockDown",
        "smartTagType", "schemaLibrary", "shapeDefaults", "doNotEmbedSmartTags",
        "decimalSymbol", "listSeparator")} | {"{http://schemas.openxmlformats.org/officeDocument/2006/math}mathPr"}
    for enfant in reglages:
        if enfant.tag in suivants:
            enfant.addprevious(maj)
            break
    else:
        reglages.append(maj)
    doc.add_page_break()


def _docx(entete: dict, elements, sortie: str) -> str:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, Cm, RGBColor

    from bureautique.modele import COULEURS

    elements = list(elements)
    charte = COULEURS.get("charte") or "1F3864"
    charte_fond = COULEURS.get("charte_fond") or charte
    if charte in ("000000",):
        charte = "1F3864"
    doc = Document()
    _styles_maison(doc, charte, charte_fond)
    section = doc.sections[0]
    if entete.get("paysage"):
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    for marge in ("top_margin", "bottom_margin"):
        setattr(section, marge, Cm(2.2))
    for marge in ("left_margin", "right_margin"):
        setattr(section, marge, Cm(2.3))

    titres = sum(1 for e in elements if e.get("bloc") == "titre" and int(e.get("niveau") or 1) <= 2)
    garde = entete.get("page_de_garde")
    garde = (len(elements) >= SEUIL_PAGE_DE_GARDE) if garde is None else bool(garde)
    # La page de garde n'a ni en-tête ni pied : ils commencent à la page 2.
    section.different_first_page_header_footer = garde

    gris = RGBColor.from_string("7F7F7F")
    logo_haut, logo_bas = _image(entete.get("entete_image_fichier")), _image(entete.get("pied_image_fichier"))
    if entete.get("entete") or logo_haut:
        p = section.header.paragraphs[0]
        if logo_haut:
            p.add_run().add_picture(logo_haut, height=Cm(1.2))
        if entete.get("entete"):
            r = p.add_run(("   " if logo_haut else "") + entete["entete"])
            r.font.size, r.font.color.rgb = Pt(8.5), gris
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    if entete.get("pied") or entete.get("numeroter") or logo_bas:
        p = section.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if logo_bas:
            p.add_run().add_picture(logo_bas, height=Cm(1.0))
            if entete.get("pied") or entete.get("numeroter"):
                p.add_run("   ")
        if entete.get("pied"):
            r = p.add_run(entete["pied"] + ("   ·   " if entete.get("numeroter") else ""))
            r.font.size, r.font.color.rgb = Pt(8.5), gris
        if entete.get("numeroter"):
            # Champ Word : Word calcule la pagination à l'ouverture. Écrire un
            # numéro en dur donnerait « page 1 » sur toutes les pages.
            _champ_page(p)
            for r in p.runs:
                r.font.size, r.font.color.rgb = Pt(8.5), gris

    if garde:
        _page_de_garde(doc, entete, charte)
        sommaire = entete.get("sommaire")
        if (titres >= SEUIL_SOMMAIRE) if sommaire is None else sommaire:
            _sommaire(doc)
    else:
        doc.add_paragraph(entete["titre"], style="Title")
        if entete.get("sous_titre"):
            doc.add_paragraph(entete["sous_titre"], style="Subtitle")

    for e in elements:
        bloc = e["bloc"]
        if bloc == "titre":
            niveau = max(1, min(4, int(e.get("niveau") or 1)))
            titre = doc.add_heading(e["texte"], niveau)
            if e.get("couleur"):
                for run in titre.runs:
                    run.font.color.rgb = RGBColor.from_string(COULEURS[e["couleur"]])
        elif bloc == "paragraphe":
            _paragraphe_docx(doc, e)
        elif bloc == "liste":
            style = "List Number" if e["ordonnee"] else "List Bullet"
            for item in e["items"]:
                _ecrire_riche(doc.add_paragraph(style=style), str(item))
        elif bloc in ("tableau", "feuille"):
            if bloc == "feuille":
                doc.add_heading(e.get("nom") or "Feuille", 2)
            _tableau_docx(doc, e, charte)
            if e.get("legende"):
                p = doc.add_paragraph(e["legende"])
                p.runs[0].font.size = Pt(9)
                p.runs[0].font.italic = True
        elif bloc == "image":
            chemin = _image(e)
            if chemin:
                doc.add_picture(chemin, width=Cm(float(e.get("largeur_cm") or 12)))
                if e.get("centre", True):
                    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                if e.get("legende"):
                    p = doc.add_paragraph(e["legende"])
                    p.runs[0].font.size = Pt(9)
                    p.runs[0].font.italic = True
                    if e.get("centre", True):
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            else:
                p = doc.add_paragraph(_absente(e))
                p.runs[0].font.italic = True
                p.runs[0].font.color.rgb = RGBColor.from_string(COULEURS["gris"])
        elif bloc == "saut_page":
            doc.add_page_break()
        elif bloc == "separateur":
            doc.add_paragraph("―" * 30).alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.save(sortie)
    return sortie


def _champ_page(paragraphe) -> None:
    """Insère « page X sur Y » sous forme de champs Word."""
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    def champ(code: str):
        debut = OxmlElement("w:fldChar"); debut.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve")
        instr.text = code
        fin = OxmlElement("w:fldChar"); fin.set(qn("w:fldCharType"), "end")
        run = paragraphe.add_run()
        for e in (debut, instr, fin):
            run._r.append(e)

    champ(" PAGE ")
    paragraphe.add_run(" / ")
    champ(" NUMPAGES ")


def _tableau_docx(doc, e: dict, charte: str = "1F3864") -> None:
    """Un tableau habillé : en-tête à la couleur de la maison, répété à chaque page."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    entetes, lignes = e["entetes"], e["lignes"]
    colonnes = len(entetes) or (len(lignes[0]) if lignes else 0)
    if not colonnes:
        return
    table = doc.add_table(rows=1 if entetes else 0, cols=colonnes)
    try:
        table.style = "Table Grid"
    except Exception:  # noqa: BLE001 — un gabarit sans ce style garde le sien
        pass

    if entetes:
        ligne = table.rows[0]
        # L'en-tête se répète en haut de chaque page d'un long tableau.
        trpr = ligne._tr.get_or_add_trPr()
        repete = OxmlElement("w:tblHeader"); repete.set(qn("w:val"), "true")
        trpr.append(repete)
        for i, titre in enumerate(entetes):
            cellule = ligne.cells[i]
            cellule.text = ""
            run = cellule.paragraphs[0].add_run(str(titre))
            run.font.bold, run.font.size = True, Pt(9.5)
            run.font.color.rgb = RGBColor.from_string("FFFFFF")
            fond = OxmlElement("w:shd")
            for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", charte)):
                fond.set(qn(k), v)
            cellule._tc.get_or_add_tcPr().append(fond)
    for n, valeurs in enumerate(lignes):
        cellules = table.add_row().cells
        for i, valeur in enumerate(valeurs[:colonnes]):
            cellules[i].text = ""
            run = cellules[i].paragraphs[0].add_run(str(valeur))
            run.font.size = Pt(9.5)
            if n % 2 == 1:
                fond = OxmlElement("w:shd")
                for k, v in (("w:val", "clear"), ("w:color", "auto"), ("w:fill", "F2F2F2")):
                    fond.set(qn(k), v)
                cellules[i]._tc.get_or_add_tcPr().append(fond)
    # TOUTE LA LARGEUR DE LA PAGE, colonne par colonne (grille ET cellules, mise
    # en page fixe) : un tableau ajusté à son contenu se tassait dans un coin.
    section = doc.sections[-1]
    utile = section.page_width - section.left_margin - section.right_margin
    table.autofit = False
    for colonne in table.columns:
        colonne.width = int(utile / colonnes)          # la grille du tableau (tblGrid)
    for rangee in table.rows:
        for cellule in rangee.cells:
            cellule.width = int(utile / colonnes)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# ── PDF ───────────────────────────────────────────────────────────────
def _pdf(entete: dict, elements, sortie: str) -> str:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, PageBreak, HRFlowable,
                                    Image as ImageFlowable)

    format_page = landscape(A4) if entete.get("paysage") else A4
    styles = getSampleStyleSheet()
    petit = ParagraphStyle("petit", parent=styles["Normal"], fontSize=8,
                           textColor=colors.grey)
    legende = ParagraphStyle("legende", parent=petit, alignment=TA_CENTER)

    logo_haut, logo_bas = _image(entete.get("entete_image_fichier")), _image(entete.get("pied_image_fichier"))

    def _dessiner(canvas, chemin, x, y, hauteur_cible):
        """Une image à hauteur fixe, proportions gardées, en bas à gauche de (x, y)."""
        w, h = _dimensions(chemin)
        largeur_cible = hauteur_cible * (w / h if h else 1)
        canvas.drawImage(chemin, x, y, width=largeur_cible, height=hauteur_cible,
                         preserveAspectRatio=True, mask="auto")

    def decor(canvas, doc):
        """En-tête et pied DESSINÉS sur chaque page, numérotation au tirage.
        Le logo d'en-tête en haut à gauche, celui du pied en bas à gauche : le
        texte garde ses places (à droite en haut, centré en bas)."""
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        largeur, hauteur = format_page
        if logo_haut:
            _dessiner(canvas, logo_haut, 2 * cm, hauteur - 1.9 * cm, 1.2 * cm)
        if logo_bas:
            _dessiner(canvas, logo_bas, 2 * cm, 0.7 * cm, 1.0 * cm)
        if entete.get("entete"):
            canvas.drawRightString(largeur - 2 * cm, hauteur - 1.2 * cm, entete["entete"])
        bas = []
        if entete.get("pied"):
            bas.append(entete["pied"])
        if entete.get("numeroter"):
            bas.append(f"page {canvas.getPageNumber()}")
        if bas:
            canvas.drawCentredString(largeur / 2, 1.2 * cm, "   ·   ".join(bas))
        canvas.restoreState()

    doc = SimpleDocTemplate(sortie, pagesize=format_page,
                            topMargin=2.2 * cm, bottomMargin=2.2 * cm,
                            leftMargin=2 * cm, rightMargin=2 * cm,
                            title=entete["titre"])

    flux = [Paragraph(entete["titre"], styles["Title"])]
    if entete.get("sous_titre"):
        flux.append(Paragraph(entete["sous_titre"], styles["Italic"]))
    flux.append(Spacer(1, 0.6 * cm))

    for e in elements:
        bloc = e["bloc"]
        if bloc == "titre":
            flux.append(Spacer(1, 0.35 * cm))
            flux.append(Paragraph(_echapper(e["texte"]),
                                  _style_titre(e, styles)))
        elif bloc == "paragraphe":
            # Les retours à la ligne d'un paragraphe restent des retours (15/09).
            flux.append(Paragraph(_echapper(e["texte"]).replace("\n", "<br/>"), _style_paragraphe(e, styles)))
        elif bloc == "liste":
            for i, item in enumerate(e["items"], 1):
                puce = f"{i}." if e["ordonnee"] else "•"
                flux.append(Paragraph(f"{puce}&nbsp;&nbsp;{_echapper(item)}",
                                      styles["BodyText"]))
        elif bloc in ("tableau", "feuille"):
            if bloc == "feuille":
                flux.append(Paragraph(_echapper(e.get("nom") or "Feuille"),
                                      styles["Heading2"]))
            table = _tableau_pdf(e, styles, format_page)
            if table is not None:
                flux.append(table)
            if e.get("legende"):
                flux.append(Paragraph(_echapper(e["legende"]), legende))
            flux.append(Spacer(1, 0.35 * cm))
        elif bloc == "image":
            chemin = _image(e)
            if chemin:
                w, h = _dimensions(chemin)
                largeur_img = min(float(e.get("largeur_cm") or 12), 17) * cm
                hauteur_img = largeur_img * (h / w if w else 1)
                img = ImageFlowable(chemin, width=largeur_img, height=hauteur_img)
                img.hAlign = "CENTER" if e.get("centre", True) else "LEFT"
                flux.append(Spacer(1, 0.2 * cm))
                flux.append(img)
                if e.get("legende"):
                    flux.append(Paragraph(_echapper(e["legende"]), legende))
                flux.append(Spacer(1, 0.3 * cm))
            else:
                flux.append(Paragraph(_echapper(_absente(e)), petit))
        elif bloc == "saut_page":
            flux.append(PageBreak())
        elif bloc == "separateur":
            flux.append(Spacer(1, 0.25 * cm))
            flux.append(HRFlowable(width="100%", color=colors.lightgrey))
            flux.append(Spacer(1, 0.25 * cm))

    doc.build(flux, onFirstPage=decor, onLaterPages=decor)
    return sortie



def _style_titre(e: dict, styles):
    """Style PDF d'un titre : celui d'origine, teinté si une couleur est demandée."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle

    from bureautique.modele import COULEURS

    base = styles[f"Heading{min(e['niveau'], 4)}"]
    if not e.get("couleur"):
        return base
    style = ParagraphStyle(f"h{e['niveau']}{e['couleur']}", parent=base)
    style.textColor = colors.HexColor("#" + COULEURS[e["couleur"]])
    return style


def _style_paragraphe(e: dict, styles):
    """Style PDF d'un paragraphe, d'après sa mise en forme demandée.

    Un style est construit à la volée plutôt que puisé dans une table : les
    combinaisons (gras × taille × couleur × centré) sont trop nombreuses pour
    être toutes prévues, et un style manquant rendrait le texte silencieusement
    sans sa mise en forme.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.styles import ParagraphStyle

    from bureautique.modele import COULEURS, TAILLES

    taille = TAILLES.get(e.get("taille"), 11)
    style = ParagraphStyle(
        f"p{taille}{e.get('couleur','')}{e.get('gras')}{e.get('centre')}",
        parent=styles["BodyText"],
        fontSize=taille,
        # L'interligne doit suivre la taille, sinon un texte en 36 points se
        # chevauche d'une ligne à l'autre.
        leading=taille * 1.25,
        alignment=TA_CENTER if e.get("centre") else styles["BodyText"].alignment,
    )
    if e.get("couleur"):
        style.textColor = colors.HexColor("#" + COULEURS[e["couleur"]])
    gras, italique = e.get("gras"), e.get("italique")
    if gras and italique:
        style.fontName = "Helvetica-BoldOblique"
    elif gras:
        style.fontName = "Helvetica-Bold"
    elif italique:
        style.fontName = "Helvetica-Oblique"
    return style


def _echapper(texte: str) -> str:
    """Le texte va dans un moteur qui interprète des balises : on le neutralise."""
    return (texte.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _tableau_pdf(e: dict, styles, format_page):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Table, TableStyle

    entetes, lignes = e["entetes"], e["lignes"]
    if not entetes and not lignes:
        return None

    cellule = ParagraphStyle("cellule", parent=styles["BodyText"], fontSize=8, leading=10)
    entete_style = ParagraphStyle("entete", parent=cellule, textColor=colors.white)

    donnees = []
    if entetes:
        donnees.append([Paragraph(f"<b>{_echapper(c)}</b>", entete_style) for c in entetes])
    colonnes = len(entetes) or max((len(l) for l in lignes), default=0)
    for ligne in lignes:
        ligne = list(ligne) + [""] * (colonnes - len(ligne))
        donnees.append([Paragraph(_echapper(c), cellule) for c in ligne[:colonnes]])
    if not donnees:
        return None

    # Largeur répartie sur la place utile : sans cela, un tableau large déborde
    # de la page et les dernières colonnes sont invisibles à l'impression.
    utile = format_page[0] - 4 * cm
    table = Table(donnees, colWidths=[utile / colonnes] * colonnes,
                  repeatRows=1 if entetes else 0)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2F5233") if entetes else colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B0B0B0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F6F4")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


# ── Excel ─────────────────────────────────────────────────────────────
def _xlsx(entete: dict, elements, sortie: str) -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    from bureautique.modele import MAX_FEUILLES, COULEURS, TAILLES

    classeur = Workbook()
    classeur.remove(classeur.active)
    gras_blanc = Font(bold=True, color="FFFFFF")
    fond = PatternFill("solid", fgColor="2F5233")

    feuille = None
    ligne_courante = 1
    noms = set()
    logo_haut, logo_bas = _image(entete.get("entete_image_fichier")), _image(entete.get("pied_image_fichier"))

    def poser_image(chemin, hauteur_cm=None, largeur_cm=None):
        """Une image ancrée à la ligne courante, qui avance d'autant. Excel n'a pas
        d'image d'en-tête ou de pied : un logo demandé y est posé en haut de
        chaque onglet, ou en bas du dernier — dégradé, jamais ignoré."""
        nonlocal ligne_courante
        try:
            from openpyxl.drawing.image import Image as XLImage
            img = XLImage(chemin)
        except Exception as e:  # noqa: BLE001 — Pillow absent : la cellule le dit
            ecrire(["[image indisponible : " + str(e)[:60] + "]"])
            return
        w, h = float(img.width or 100), float(img.height or 100)
        px_cm = 37.8
        if hauteur_cm:
            img.height, img.width = hauteur_cm * px_cm, hauteur_cm * px_cm * (w / h if h else 1)
        elif largeur_cm:
            img.width, img.height = largeur_cm * px_cm, largeur_cm * px_cm * (h / w if w else 1)
        feuille.add_image(img, f"A{ligne_courante}")
        ligne_courante += int(img.height / 20) + 2

    def nouvelle(nom: str):
        nonlocal feuille, ligne_courante
        if len(classeur.worksheets) >= MAX_FEUILLES:
            return feuille
        # Excel refuse les doublons et certains caractères dans un nom d'onglet.
        propre = "".join(c for c in (nom or "Feuille") if c not in "[]:*?/\\")[:31] or "Feuille"
        base, n = propre, 2
        while propre in noms:
            propre = f"{base[:28]}_{n}"
            n += 1
        noms.add(propre)
        feuille = classeur.create_sheet(propre)
        if entete.get("entete"):
            feuille.oddHeader.right.text = entete["entete"]
        if entete.get("pied") or entete.get("numeroter"):
            bas = [entete.get("pied") or ""]
            if entete.get("numeroter"):
                bas.append("page &P / &N")
            feuille.oddFooter.center.text = "   ·   ".join(x for x in bas if x)
        ligne_courante = 1
        if logo_haut:
            poser_image(logo_haut, hauteur_cm=1.5)
        return feuille

    def ecrire(valeurs, gras=False):
        nonlocal ligne_courante
        for i, v in enumerate(valeurs, 1):
            c = feuille.cell(row=ligne_courante, column=i, value=v)
            if gras:
                c.font, c.fill = gras_blanc, fond
            c.alignment = Alignment(vertical="top", wrap_text=True)
        ligne_courante += 1

    def garantir():
        """Ouvre la feuille d'accueil, mais SEULEMENT si quelque chose y va.

        AVANT (relevé de Noa, 01/09) : « à chaque fois que je demande des Excel,
        il me fait toujours deux feuilles — une avec un titre qui est inutile et
        une autre avec les vraies infos ». La feuille d'accueil était créée
        d'office, puis chaque bloc `feuille` créait la sienne : un classeur avec
        un onglet ne portant qu'un titre, et un onglet de données à côté.

        Elle n'est donc plus ouverte qu'à la demande. Un document fait
        uniquement de blocs `feuille` — le cas de tous les exports de listes —
        n'en a plus du tout, et l'onglet porte directement le nom des données.
        """
        nonlocal ligne_courante
        if feuille is not None:
            return
        nouvelle(entete["titre"])
        ecrire([entete["titre"]], gras=False)
        feuille.cell(row=ligne_courante - 1, column=1).font = Font(bold=True, size=14)
        ligne_courante += 1

    for e in elements:
        bloc = e["bloc"]
        if bloc != "feuille":
            garantir()
        if bloc == "feuille":
            nouvelle(e.get("nom") or "Feuille")
            if e["entetes"]:
                ecrire(e["entetes"], gras=True)
                feuille.freeze_panes = "A2"     # les entêtes restent visibles
            for ligne in e["lignes"]:
                ecrire(ligne)
        elif bloc == "tableau":
            if e.get("legende"):
                ecrire([e["legende"]])
            if e["entetes"]:
                ecrire(e["entetes"], gras=True)
            for ligne in e["lignes"]:
                ecrire(ligne)
            ligne_courante += 1
        elif bloc == "titre":
            ecrire([e["texte"]])
            feuille.cell(row=ligne_courante - 1, column=1).font = Font(
                bold=True, size=max(14 - e["niveau"], 10),
                color=(COULEURS[e["couleur"]] if e.get("couleur") else None))
        elif bloc == "paragraphe":
            ecrire([e["texte"]])
            c = feuille.cell(row=ligne_courante - 1, column=1)
            c.font = Font(bold=e.get("gras", False), italic=e.get("italique", False),
                          size=TAILLES.get(e.get("taille"), 11),
                          color=(COULEURS[e["couleur"]] if e.get("couleur") else None))
            if e.get("centre"):
                c.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
        elif bloc == "liste":
            for i, item in enumerate(e["items"], 1):
                ecrire([f"{i}." if e["ordonnee"] else "•", item])
        elif bloc == "image":
            chemin = _image(e)
            if chemin:
                if e.get("legende"):
                    ecrire([e["legende"]])
                poser_image(chemin, largeur_cm=min(float(e.get("largeur_cm") or 12), 17))
            else:
                ecrire([_absente(e)])
        elif bloc in ("saut_page", "separateur"):
            ligne_courante += 1

    # Un classeur SANS AUCUNE feuille est un fichier qu'Excel refuse d'ouvrir :
    # si le document était vide, on ouvre la feuille d'accueil pour de bon.
    garantir()
    if logo_bas:
        ligne_courante = max(ligne_courante, feuille.max_row + 2)
        poser_image(logo_bas, hauteur_cm=1.2)

    # Largeurs : un classeur dont tout est tronqué à l'écran passe pour cassé.
    for ws in classeur.worksheets:
        for colonne in range(1, min(ws.max_column, 40) + 1):
            largeur = max((len(str(ws.cell(row=r, column=colonne).value or ""))
                           for r in range(1, min(ws.max_row, 200) + 1)), default=10)
            ws.column_dimensions[get_column_letter(colonne)].width = min(max(largeur + 2, 10), 60)

    classeur.save(sortie)
    return sortie
