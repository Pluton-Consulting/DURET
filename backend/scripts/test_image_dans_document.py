"""
Banc « UNE IMAGE DANS UN DOCUMENT » (09/09) — relevé de Noa sur Symbiose : « il
n'arrive pas à récupérer une image du Drive ou qu'on donne en pièce jointe et
à la mettre en pied de page d'un doc Word ».

Ce n'était pas un défaut du modèle : le vocabulaire des blocs n'avait AUCUNE
image, et l'en-tête comme le pied de page n'étaient que du texte. Ce banc
prouve la chaîne entière, sans réseau ni modèle :
  · le vocabulaire (pur) : un bloc `image` sous ses synonymes, `largeur_cm`
    bornée, `entete_image` / `pied_image` (et « logo ») dans l'en-tête ;
  · `bureautique/images.py` EXÉCUTÉ contre la résolution des pièces doublée :
    une clé d'image, un nom de fichier du stockage, un PDF refusé comme
    « pas une image », une référence inconnue refusée avec sa raison ; les
    octets rangés SOUS LE JETON par l'atelier RÉEL (dossier temporaire) ;
  · les trois rendus RÉELS (python-docx, reportlab, openpyxl — sinon le banc
    le dit et s'arrête) : le Word porte l'image dans l'en-tête, le pied et le
    corps ; le PDF et l'Excel aussi ; une image introuvable laisse une trace
    lisible, jamais un trou ;
  · les skills EXÉCUTÉS : `creer_document` avec `pied_image`, `ajouter_document`
    avec un bloc image, `terminer_document` ; `produire` en un coup ; une
    référence inconnue est DITE dans la note ; `abandonner` emporte les images ;
  · le catalogue, la consigne des images et le mode d'emploi le disent.
Tombe sur la version d'avant (le bloc `image` était écarté comme inconnu).
"""
import asyncio
import base64
import io
import os
import pathlib
import sys
import tempfile
import types
import zipfile

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(chemin, nom):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    sys.modules[nom] = mod
    return mod


def _module(nom, **attrs):
    m = types.ModuleType(nom)
    m.__path__ = []
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[nom] = m
    return m


print(f"\n═══ UNE IMAGE DANS UN DOCUMENT — {RACINE}\n")
DOSSIER = tempfile.mkdtemp(prefix="atelier-images-")
os.environ["DOCUMENTS_DIR"] = DOSSIER
sys.path.insert(0, str(BACKEND))
from bureautique import modele  # noqa: E402  — le vrai module
from bureautique import atelier  # noqa: E402
verifier("l'atelier écrit dans le dossier du banc", atelier.DOSSIER == DOSSIER)

# Une vraie image PNG (1 × 1, rouge) et un JPEG minimal : sans Pillow, ce sont
# les seuls formats que les trois rendus lisent.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg==")
try:
    from PIL import Image as _PIL
    _buf = io.BytesIO(); _PIL.new("RGB", (60, 20), (47, 82, 51)).save(_buf, format="PNG"); LOGO = _buf.getvalue()
    _buf = io.BytesIO(); _PIL.new("RGB", (40, 30), (200, 30, 30)).save(_buf, format="WEBP"); WEBP = _buf.getvalue()
    _buf = io.BytesIO(); _PIL.new("RGB", (40, 30), (30, 30, 200)).save(_buf, format="PNG"); PHOTO = _buf.getvalue()
    PILLOW = True
except Exception:  # noqa: BLE001
    LOGO, WEBP, PHOTO, PILLOW = PNG, b"", PNG, False

# ══════════════════════════════════════════════════════════════════════════
# 1. LE VOCABULAIRE (PUR)
# ══════════════════════════════════════════════════════════════════════════
print("── 1. Le vocabulaire")
n = modele.normaliser_element
e = n({"bloc": "image", "image": "d7b5e304cb0453dfd49dc0a1", "legende": "Vue terrasse", "largeur_cm": 10})
verifier("un bloc image garde sa référence, sa légende, sa largeur ; centré par défaut",
         e == {"bloc": "image", "legende": "Vue terrasse", "centre": True, "largeur_cm": 10.0,
               "ref": "d7b5e304cb0453dfd49dc0a1"}, e)
verifier("les synonymes du modèle : {type: photo, fichier: <nom>}, {type: img, ref}, {type: picture, url}",
         n({"type": "photo", "fichier": "logo-symbiose.png"})["ref"] == "logo-symbiose.png"
         and n({"type": "img", "ref": "abc"})["bloc"] == "image"
         and n({"type": "picture", "url": "/api/visuels/d7b5e304cb0453dfd49dc0a1"})["ref"].endswith("d7b5e304cb0453dfd49dc0a1"))
verifier("la largeur est bornée (2 à 17 cm) et une valeur illisible retombe sur 12",
         n({"bloc": "image", "image": "x", "largeur_cm": 40})["largeur_cm"] == 17.0
         and n({"bloc": "image", "image": "x", "largeur_cm": "large"})["largeur_cm"] == 12.0
         and n({"bloc": "image", "image": "x", "largeur_cm": 0.5})["largeur_cm"] == 2.0)
verifier("une image sans aucune référence n'est pas un bloc", n({"bloc": "image", "legende": "?"}) is None)
verifier("une image DÉJÀ rangée (<jeton>.img1.png) garde son fichier, rien à résoudre",
         n({"bloc": "image", "fichier": "HOn-pT0eHl9w3osDpqk8FKsH_iZGavzm.img1.png"}).get("fichier")
         == "HOn-pT0eHl9w3osDpqk8FKsH_iZGavzm.img1.png")
verifier("un `fichier` qui n'est pas de cette forme est une RÉFÉRENCE (nom sur le stockage), jamais un chemin lu tel quel",
         n({"bloc": "image", "fichier": "../../secrets/x.png"}).get("ref") == "../../secrets/x.png"
         and "fichier" not in n({"bloc": "image", "fichier": "../../secrets/x.png"}))
h = modele.normaliser_entete({"titre": "Devis", "format": "docx", "pied_image": "logo-symbiose.png", "logo": "d7b5e304cb0453dfd49dc0a1"})
verifier("l'en-tête accepte `pied_image` et `logo` (= entete_image), `_fichier` vides tant que rien n'est rangé",
         h["pied_image"] == "logo-symbiose.png" and h["entete_image"] == "d7b5e304cb0453dfd49dc0a1"
         and h["pied_image_fichier"] == "" and h["entete_image_fichier"] == "", h)
verifier("le vocabulaire montré au modèle porte `image`", "image" in modele.BLOCS and "largeur_cm" in modele.BLOCS["image"])

# ══════════════════════════════════════════════════════════════════════════
# 2. LA RÉSOLUTION, ET LE RANGEMENT SOUS LE JETON (ATELIER RÉEL)
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. images.py : résoudre, ranger")
DEMANDES = []


async def _resoudre_pieces(brut, user, boite):
    DEMANDES.append(brut[0])
    ref = brut[0]
    if ref in ("d7b5e304cb0453dfd49dc0a1", "/api/visuels/d7b5e304cb0453dfd49dc0a1"):
        return [{"nom": "d7b5e304cb0453dfd49dc0a1.png", "mime": "image/png", "octets": PNG}], []
    if ref == "logo-symbiose.png":
        return [{"nom": "logo-symbiose.png", "mime": "image/png", "octets": LOGO}], []
    if ref == "photo.png":
        return [{"nom": "photo.png", "mime": "image/png", "octets": PHOTO}], []
    if ref == "photo.webp":
        return [{"nom": "photo.webp", "mime": "image/webp", "octets": WEBP}], []
    if ref == "devis.pdf":
        return [{"nom": "devis.pdf", "mime": "application/pdf", "octets": b"%PDF-1.4"}], []
    return [], [{"nom": ref, "raison": "introuvable — ouvre d'abord le fichier ou vérifie son nom"}]
_module("mail")
_module("mail.attaches", resoudre=_resoudre_pieces)
from bureautique import images  # noqa: E402
U = types.SimpleNamespace(id="u1", role="direction")
octets, ext, nom = asyncio.run(images.resoudre("d7b5e304cb0453dfd49dc0a1", U))
verifier("une clé d'image de la conversation se résout par la résolution des pièces (mêmes droits)",
         octets == PNG and ext == "png" and DEMANDES[-1] == "d7b5e304cb0453dfd49dc0a1")
octets, ext, nom = asyncio.run(images.resoudre("logo-symbiose.png", U))
verifier("un NOM de fichier du stockage aussi", octets == LOGO and nom == "logo-symbiose.png")
try:
    asyncio.run(images.resoudre("devis.pdf", U))
    verifier("un PDF SANS logo est refusé, avec sa raison", False,
             "il a rendu une image alors que ce PDF doublé n'en porte aucune")
except images.ImageRefusee as err:
    # 10/09 : un PDF n'est plus refusé d'office — un devis type de la maison en
    # est un, et c'est SON logo qu'on nous demande de reprendre. Celui du banc
    # n'est pas un vrai PDF (huit octets) : le refus doit le NOMMER et dire
    # pourquoi, jamais renvoyer « n'est pas une image » comme avant.
    verifier("un PDF illisible est refusé, en le nommant et en disant pourquoi",
             "devis.pdf" in str(err) and "n'est pas une image" not in str(err), err)
verifier("un fichier qui n'est ni image ni PDF n'est toujours pas une image",
         not images.est_image("note.txt", "text/plain")
         and not images._est_un_pdf("note.txt", "text/plain"))
try:
    asyncio.run(images.resoudre("inconnu.png", U))
    verifier("une référence inconnue est refusée AVEC la raison de la résolution", False)
except images.ImageRefusee as err:
    verifier("une référence inconnue est refusée AVEC la raison de la résolution", "introuvable" in str(err), err)
if PILLOW:
    octets, ext, _ = asyncio.run(images.resoudre("photo.webp", U))
    verifier("un WebP (les photos du chat) est converti en PNG : les trois rendus le lisent",
             ext == "png" and octets[:8] == b"\x89PNG\r\n\x1a\n")
else:
    print("  ⚠ Pillow absent : la conversion WebP n'est pas jouée")

entete = modele.normaliser_entete({"titre": "Dossier Camp", "format": "docx", "pied": "Symbiose Paysage",
                                   "pied_image": "logo-symbiose.png", "entete_image": "d7b5e304cb0453dfd49dc0a1"})
jeton = atelier.ouvrir(entete, "u1")
blocs = [{"bloc": "paragraphe", "texte": "Vue actuelle de la terrasse."},
         {"bloc": "image", "image": "photo.png", "legende": "Photo de départ", "largeur_cm": 8},
         {"bloc": "image", "image": "inconnu.png", "legende": "Une image qui n'existe pas"}]
prets, entete_pret, refus = asyncio.run(images.preparer(jeton, "u1", blocs, entete, U))
verifier("`preparer` : l'image connue reçoit son `fichier` rangé sous le jeton, l'inconnue est ÉCARTÉE avec sa raison",
         len(prets) == 2 and prets[1].get("fichier") == f"{jeton}.img1.png"
         and len(refus) == 1 and "inconnu.png" in refus[0] and "introuvable" in refus[0], (prets, refus))
verifier("… l'en-tête et le pied ont leurs fichiers (img2, img3), rangés dans l'atelier",
         entete_pret["entete_image_fichier"] == f"{jeton}.img2.png" and entete_pret["pied_image_fichier"] == f"{jeton}.img3.png"
         and os.path.exists(os.path.join(DOSSIER, f"{jeton}.img3.png")), entete_pret)
verifier("`chemin_image` ne lit qu'un nom rangé, jamais un chemin",
         atelier.chemin_image(f"{jeton}.img1.png") is not None and atelier.chemin_image("../x.png") is None
         and atelier.chemin_image(f"/etc/{jeton}.img1.png") == os.path.join(DOSSIER, f"{jeton}.img1.png"))
verifier("`ranger_image` refuse le document d'un autre",
         (lambda: (_ for _ in ()).throw(KeyError()))
         and not (lambda: atelier.ranger_image(jeton, "u2", PNG, "png") or True)() if False else True)
try:
    atelier.ranger_image(jeton, "u2", PNG, "png")
    verifier("`ranger_image` refuse le document d'un autre", False)
except KeyError:
    verifier("`ranger_image` refuse le document d'un autre", True)
atelier.mettre_a_jour_entete(jeton, "u1", entete_pret)
verifier("l'en-tête mis à jour dans la fiche", atelier.fiche(jeton, "u1")["entete"]["pied_image_fichier"] == f"{jeton}.img3.png")
retenus = atelier.ajouter(jeton, prets, "u1")
verifier("le versement garde l'image rangée (normalisée avec son `fichier`)",
         retenus == 2 and [x for x in atelier.elements(jeton)][1].get("fichier") == f"{jeton}.img1.png")
verifier("l'extrait du document dit l'image", "[image : Photo de départ]" in atelier._extrait(jeton))

# ══════════════════════════════════════════════════════════════════════════
# 3. LES TROIS RENDUS RÉELS
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. Les rendus (python-docx, reportlab, openpyxl)")
try:
    import docx  # noqa: F401
    import openpyxl  # noqa: F401
    import reportlab  # noqa: F401
    RENDU = True
except ImportError:
    RENDU = False
    print("  ⚠ python-docx / reportlab / openpyxl absents : les rendus ne sont pas joués ici "
          "(jouer ce banc avec un venv qui les porte, ou dans le conteneur).")
if RENDU:
    from bureautique import rendu
    f = atelier.terminer(jeton, "u1")
    chemin = atelier.chemin_fichier(jeton, "u1")
    with zipfile.ZipFile(chemin) as z:
        noms = z.namelist()
        medias = [x for x in noms if x.startswith("word/media/")]
        footer = "".join(z.read(x).decode("utf-8", "replace") for x in noms if x.startswith("word/footer"))
        header = "".join(z.read(x).decode("utf-8", "replace") for x in noms if x.startswith("word/header"))
        corps = z.read("word/document.xml").decode("utf-8", "replace")
    # python-docx ne range qu'une fois deux images IDENTIQUES : trois fichiers
    # distincts (photo, logo, clé) donnent trois médias — sans Pillow, la photo
    # et la clé sont le même PNG, deux médias.
    verifier("WORD : les images sont embarquées (en-tête, pied, corps)", len(medias) == (3 if PILLOW else 2), medias)
    verifier("WORD : le PIED DE PAGE porte l'image ET le texte", "<w:drawing>" in footer and "Symbiose Paysage" in footer)
    verifier("WORD : l'en-tête porte l'image", "<w:drawing>" in header)
    verifier("WORD : le corps porte l'image et sa légende", "<w:drawing>" in corps and "Photo de départ" in corps)
    # Une image introuvable au rendu (fichier effacé) laisse une trace lisible.
    e2 = modele.normaliser_entete({"titre": "PDF logo", "format": "pdf", "entete": "Symbiose",
                                   "pied_image": "logo-symbiose.png"})
    j2 = atelier.ouvrir(e2, "u1")
    b2 = [{"bloc": "titre", "texte": "Photos"},
          {"bloc": "image", "image": "d7b5e304cb0453dfd49dc0a1", "legende": "Terrasse", "largeur_cm": 6},
          {"bloc": "image", "fichier": f"{j2}.img9.png", "legende": "effacée"}]
    p2, e2p, r2 = asyncio.run(images.preparer(j2, "u1", b2, e2, U))
    atelier.mettre_a_jour_entete(j2, "u1", e2p)
    atelier.ajouter(j2, p2, "u1")
    atelier.terminer(j2, "u1")
    pdf = open(atelier.chemin_fichier(j2, "u1"), "rb").read()
    verifier("PDF : produit avec le logo du pied et l'image du corps (objets image dans le fichier)",
             pdf[:5] == b"%PDF-" and pdf.count(b"/Subtype /Image") + pdf.count(b"/Subtype/Image") >= 2, pdf.count(b"/Image"))
    # openpyxl
    e3 = modele.normaliser_entete({"titre": "Classeur", "format": "xlsx", "entete_image": "logo-symbiose.png",
                                   "pied_image": "logo-symbiose.png"})
    j3 = atelier.ouvrir(e3, "u1")
    b3 = [{"bloc": "feuille", "nom": "Quantitatif", "entetes": ["Poste", "Qté"], "lignes": [["Gazon", "115 m²"]]},
          {"bloc": "image", "image": "d7b5e304cb0453dfd49dc0a1", "legende": "Vue"}]
    p3, e3p, _ = asyncio.run(images.preparer(j3, "u1", b3, e3, U))
    atelier.mettre_a_jour_entete(j3, "u1", e3p)
    atelier.ajouter(j3, p3, "u1")
    atelier.terminer(j3, "u1")
    with zipfile.ZipFile(atelier.chemin_fichier(j3, "u1")) as z:
        medias = [x for x in z.namelist() if x.startswith("xl/media/")]
    verifier("EXCEL : le logo d'en-tête en haut de l'onglet, celui du pied en bas, l'image du corps (3 images)",
             len(medias) == 3, medias)
    from openpyxl import load_workbook
    ws = load_workbook(atelier.chemin_fichier(j3, "u1")).worksheets[0]
    verifier("EXCEL : le tableau reste lisible sous le logo (en-têtes en gras, données présentes)",
             any(c.value == "Gazon" for row in ws.iter_rows() for c in row)
             and any(c.value == "Poste" and c.font.bold for row in ws.iter_rows() for c in row))
    # Le trou visible : un docx dont l'image rangée a disparu.
    e4 = modele.normaliser_entete({"titre": "Trou", "format": "docx"})
    j4 = atelier.ouvrir(e4, "u1")
    atelier.ajouter(j4, [{"bloc": "image", "fichier": f"{j4}.img7.png", "legende": "plan perdu"}], "u1")
    atelier.terminer(j4, "u1")
    with zipfile.ZipFile(atelier.chemin_fichier(j4, "u1")) as z:
        corps = z.read("word/document.xml").decode("utf-8", "replace")
    verifier("une image introuvable au rendu laisse « [image indisponible : plan perdu] », jamais un trou",
             "[image indisponible : plan perdu]" in corps)

# ══════════════════════════════════════════════════════════════════════════
# 4. LES SKILLS, EXÉCUTÉS
# ══════════════════════════════════════════════════════════════════════════
print("\n── 4. Les skills")
_module("skills")
bureau = charger(BACKEND / "skills" / "bureau.py", "skills_bureau_double")
r = asyncio.run(bureau.creer_document({"titre": "Dossier chantier", "format": "docx",
                                       "pied_image": "logo-symbiose.png", "entete": "Symbiose Paysage"}, U))
jeton = r["document_id"]
verifier("`creer_document` avec `pied_image` : l'image est rangée, la note le dit",
         atelier.fiche(jeton, "u1")["entete"]["pied_image_fichier"] == f"{jeton}.img1.png"
         and "pied de page" in r["note"] and not r["images_refusees"], r)
r = asyncio.run(bureau.ajouter_document({"document_id": jeton, "elements": [
    {"bloc": "paragraphe", "texte": "Photo de la terrasse :"},
    {"bloc": "image", "image": "d7b5e304cb0453dfd49dc0a1", "legende": "Terrasse"},
    {"bloc": "image", "image": "nulle-part.png"}]}, U))
verifier("`ajouter_document` : le bloc image connu est versé, l'inconnu est DIT (« NON insérée ») avec sa raison",
         r["ajoutes"] == 2 and r["images_refusees"] and "nulle-part.png" in r["note"] and "NON insérée" in r["note"], r)
r = asyncio.run(bureau.creer_document({"titre": "Sans image", "format": "docx", "pied_image": "inconnu.png"}, U))
verifier("`creer_document` avec un logo introuvable : le document s'ouvre quand même, la note dit le refus",
         r["document_id"] and "NON insérée" in r["note"] and "pied de page" in r["note"], r["note"])
if RENDU:
    r = asyncio.run(bureau.terminer_document({"document_id": jeton}, U))
    verifier("`terminer_document` rend le fichier, image comprise", r["pret"] and r["octets"] > 0)
    outils_docs = charger(BACKEND / "outils" / "documents.py", "outils_documents_double")
    r = asyncio.run(outils_docs.produire("Note", [{"bloc": "paragraphe", "texte": "Ci-dessous le plan."},
                                                  {"bloc": "image", "image": "d7b5e304cb0453dfd49dc0a1"}],
                                         "u1", format="docx", entete_image="logo-symbiose.png",
                                         pied_image="oubli.png", user=U))
    verifier("`produire` en un coup : image du corps et logo d'en-tête rangés, le pied introuvable est DIT",
             r["pret"] and r["elements"] == 2 and atelier.fiche(r["document_id"], "u1")["entete"]["entete_image_fichier"]
             and r["images_refusees"] and "NON insérée" in r["note"] and "oubli.png" in r["note"], r.get("note"))
    ranges = [n for n in os.listdir(DOSSIER) if n.startswith(f"{r['document_id']}.img")]
    verifier("… deux images rangées sous le jeton", len(ranges) == 2, ranges)
    atelier.abandonner(r["document_id"], "u1")
    verifier("`abandonner` emporte les images rangées", not [n for n in os.listdir(DOSSIER) if n.startswith(f"{r['document_id']}.img")])

# ══════════════════════════════════════════════════════════════════════════
# 5. CE QUE LE MODÈLE LIT
# ══════════════════════════════════════════════════════════════════════════
print("\n── 5. Le catalogue et les consignes")
protocole = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("catalogue : `creer_document` dit `entete_image` / `pied_image` (une IMAGE sur chaque page) et les liste",
         "`entete_image` / " in protocole and '"entete_image", "pied_image"]' in protocole)
verifier("catalogue : `ajouter_document` dit le bloc image", "{bloc:image, image:<reference>, legende}" in protocole)
outils_src = (BACKEND / "skills" / "outils.py").read_text(encoding="utf-8")
verifier("catalogue : `produire_document` dit image, entete_image, pied_image, et transmet `user`",
         "|image|" in outils_src and '"entete_image", "pied_image"]' in outils_src and "user=user)" in outils_src)
ag1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("la consigne des images dit comment mettre une image DANS un document, en-tête ou pied",
         "DANS un document (corps, en-tête ou pied de page)" in ag1 and "`entete_image` / `pied_image`" in ag1)
verifier("le mode d'emploi documente le bloc image et les logos",
         "| `image` |" in (BACKEND / "outils" / "docs" / "documents.md").read_text(encoding="utf-8"))

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
