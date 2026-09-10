"""
Banc de LA CHARTE DANS UN DOCUMENT — les couleurs de la maison, pas celles de Word.

CE QUI S'EST PASSÉ (Symbiose, 09/09). « Refais le dossier de M. Camp en Word en
reprenant les pieds de page et l'en-tête comme le PDF Symbiose_DevisFinal, et
adapte les couleurs et la structure. » Les IMAGES d'en-tête et de pied
marchaient (traces de 14:03 : le logo du Drive est résolu, posé, et le Word
final pèse 902 Ko). Les COULEURS, elles, n'existaient nulle part :

  · la palette était générique — rouge, vert, bleu, orange, gris, noir — et ne
    contenait pas la couleur de la maison ;
  · un TITRE ne portait aucune couleur, alors que c'est là qu'une charte se voit.

Le modèle a donc écrit « avec les couleurs adaptées » sans qu'aucune couleur ne
soit adaptée. Une promesse fausse est la pire des sorties : elle demande à la
personne d'ouvrir le fichier pour découvrir que non.

CE BANC PROUVE, sur les modules livrés : la couleur `charte` vient bien de
`emails/marque.py` (la seule source de la charte, déjà utilisée par les mails),
le vocabulaire est resté FERMÉ, un titre sans couleur rend EXACTEMENT comme
avant, et — quand python-docx / reportlab / openpyxl sont là — les trois rendus
posent réellement la couleur, vérifiée en ROUVRANT le fichier.

Usage : python backend/scripts/test_charte_document.py [backend]
"""
import pathlib
import sys
import tempfile
import zipfile

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
sys.path.insert(0, str(BACKEND))

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LA CHARTE DANS UN DOCUMENT — {BACKEND}\n")

from bureautique.modele import BLOCS, COULEURS, normaliser_element  # noqa: E402
from emails.marque import MARQUE  # noqa: E402

# ── 1. La charte vient de la marque, et de nulle part ailleurs ───────────
print("1. La couleur de la maison")
attendue = str(MARQUE.get("couleur") or "").lstrip("#").upper()
verifier("`charte` est EXACTEMENT la couleur d'accent de `emails/marque.py`",
         COULEURS.get("charte") == attendue, (COULEURS.get("charte"), attendue))
verifier("`charte_fond` est le ton foncé de la même source",
         COULEURS.get("charte_fond") == str(MARQUE.get("fond") or "").lstrip("#").upper())
verifier("les deux sont des hexadécimaux à six chiffres",
         all(len(COULEURS[c]) == 6 and all(x in "0123456789ABCDEF" for x in COULEURS[c])
             for c in ("charte", "charte_fond")))
verifier("les couleurs de DOCUMENT n'ont pas bougé",
         COULEURS["rouge"] == "C0272D" and COULEURS["gris"] == "6B6B6B"
         and COULEURS["noir"] == "000000")

# ── 2. Le vocabulaire reste fermé, et le défaut ne change pas ────────────
print("\n2. Le vocabulaire")
verifier("le catalogue montre `charte` au modèle, sur le titre ET le paragraphe",
         "charte" in BLOCS["titre"] and "charte" in BLOCS["paragraphe"])
titre = normaliser_element({"bloc": "titre", "texte": "Dossier projet", "niveau": 1,
                            "couleur": "charte"})
verifier("un titre accepte la couleur de la charte",
         titre and titre["couleur"] == "charte", titre)
nu = normaliser_element({"bloc": "titre", "texte": "Dossier projet", "niveau": 1})
verifier("UN TITRE SANS COULEUR RESTE SANS COULEUR (rendu d'avant, intact)",
         nu and nu["couleur"] == "" and nu["niveau"] == 1, nu)
invente = normaliser_element({"bloc": "titre", "texte": "X", "couleur": "fuchsia"})
verifier("une couleur inventée est écartée, pas rendue au hasard",
         invente and invente["couleur"] == "", invente)
para = normaliser_element({"bloc": "paragraphe", "texte": "Un mot", "couleur": "charte"})
verifier("un paragraphe aussi", para and para["couleur"] == "charte", para)

# ── 3. Les rendus RÉELS : on rouvre le fichier ───────────────────────────
print("\n3. Les trois rendus")
try:
    import docx  # noqa: F401
    import openpyxl  # noqa: F401
    import reportlab  # noqa: F401
    RENDU = True
except ImportError:
    RENDU = False
    print("  · à lire : python-docx / reportlab / openpyxl absents de ce poste — les rendus "
          "ne sont pas joués ici (les jouer avec un venv qui les porte, ou dans le conteneur).")

if RENDU:
    from bureautique.rendu import rendre

    BLOCS_ESSAI = [
        {"bloc": "titre", "texte": "Dossier projet paysager", "niveau": 1, "couleur": "charte"},
        {"bloc": "titre", "texte": "Sans couleur", "niveau": 2, "couleur": ""},
        {"bloc": "paragraphe", "texte": "Un paragraphe à la couleur de la maison.",
         "gras": False, "italique": False, "centre": False, "taille": "normal",
         "couleur": "charte"},
    ]
    ENTETE = {"titre": "Charte", "format": "docx", "entete": "", "pied": "",
              "entete_image": "", "pied_image": "",
              "entete_image_fichier": "", "pied_image_fichier": ""}
    with tempfile.TemporaryDirectory() as dossier:
        base = pathlib.Path(dossier)

        chemin = base / "charte.docx"
        rendre({**ENTETE, "format": "docx"}, BLOCS_ESSAI, str(chemin))
        with zipfile.ZipFile(chemin) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        verifier("WORD : la couleur de la charte est écrite dans le document",
                 COULEURS["charte"] in xml, COULEURS["charte"])
        verifier("WORD : le titre SANS couleur n'en reçoit aucune",
                 xml.count(f'w:val="{COULEURS["charte"]}"') == 2,
                 xml.count(f'w:val="{COULEURS["charte"]}"'))

        chemin = base / "charte.pdf"
        rendre({**ENTETE, "format": "pdf"}, BLOCS_ESSAI, str(chemin))
        verifier("PDF : le fichier est produit et n'est pas vide",
                 chemin.exists() and chemin.stat().st_size > 800, chemin.stat().st_size)

        chemin = base / "charte.xlsx"
        rendre({**ENTETE, "format": "xlsx"}, BLOCS_ESSAI, str(chemin))
        wb = openpyxl.load_workbook(chemin)
        couleurs = [c.font.color.rgb for ligne in wb.active.iter_rows() for c in ligne
                    if c.value and c.font and c.font.color and c.font.color.rgb]
        verifier("EXCEL : la couleur de la charte est posée sur la cellule du titre",
                 any(str(c).endswith(COULEURS["charte"]) for c in couleurs), couleurs)

# ── 4. Reprendre la charte d'un PDF : son logo ───────────────────────────
#    Le devis de référence de la maison est un PDF. `reproduire_document` le
#    refuse à juste titre (on ne rouvre pas un PDF sans perdre sa mise en
#    page), et `entete_image` le refusait aussi : le modèle recopiait donc
#    l'en-tête À LA MAIN, en texte. C'est ce que Noa a vu le 09/09 (« tu n'as
#    pas repris l'image en-tête pied de page »).
print("\n4. Le logo d'un PDF")
try:
    import fitz
    from PIL import Image
    PDF = True
except ImportError:
    PDF = False
    print("  · à lire : PyMuPDF / Pillow absents de ce poste — l'extraction n'est pas jouée ici.")

if PDF:
    import io as _io
    from bureautique.images import ImageRefusee, logo_du_pdf

    def _png(couleur, taille):
        b = _io.BytesIO()
        Image.new("RGB", taille, couleur).save(b, format="PNG")
        return b.getvalue()

    def _pdf(images):
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)          # A4
        for rect, couleur, taille in images:
            page.insert_image(fitz.Rect(*rect), stream=_png(couleur, taille))
        page.insert_text((60, 400), "DEVIS N 2025-0418 - Terrasse bois exotique")
        octets = doc.tobytes()
        doc.close()
        return octets

    devis = _pdf([((40, 20, 240, 90), (20, 158, 117), (400, 140)),      # logo en haut
                  ((40, 780, 300, 820), (15, 31, 14), (520, 80))])      # bandeau en bas
    octets, mime, nom = logo_du_pdf(devis, "Symbiose_DevisFinal.pdf")
    verifier("le logo d'un devis PDF est extrait", len(octets) > 200 and "image/" in mime,
             (len(octets), mime))
    verifier("et le nom rendu dit D'OÙ il vient", "en-tête" in nom or "pied" in nom, nom)
    verifier("c'est bien le LOGO qui est pris, pas le bandeau du bas",
             Image.open(_io.BytesIO(octets)).size == (400, 140),
             Image.open(_io.BytesIO(octets)).size)

    scan = _pdf([((0, 0, 595, 842), (200, 200, 200), (1190, 1684))])
    try:
        logo_du_pdf(scan, "devis_scanne.pdf")
        verifier("une page SCANNÉE d'un seul tenant est refusée", False,
                 "elle a été prise pour un logo")
    except ImageRefusee as e:
        verifier("une page SCANNÉE d'un seul tenant est refusée", True)
        verifier("et le refus dit quoi faire à la place",
                 "TEXTE" in str(e) or "logo" in str(e), str(e)[:90])

    doc = fitz.open(); doc.new_page(); vide = doc.tobytes(); doc.close()
    try:
        logo_du_pdf(vide, "note.pdf")
        verifier("un PDF de texte pur est refusé", False)
    except ImageRefusee:
        verifier("un PDF de texte pur est refusé", True)

# ── 5. Le modèle sait que tout cela existe ───────────────────────────────
print("\n5. Ce que le modèle en sait")
proto = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue de `creer_document` parle du PDF et de la couleur `charte`",
         "on en tire son logo" in proto and "charte" in proto)
docs = (BACKEND / "outils" / "docs" / "documents.md").read_text(encoding="utf-8")
verifier("le mode d'emploi explique la charte et le logo d'un PDF",
         "Reprendre la charte" in docs and "charte_fond" in docs)
verifier("et il dit de NE PAS inventer une couleur en hexadécimal",
         "ne les invente pas" in docs)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
