"""
Banc des pièces jointes et des liens — « il doit pouvoir les récupérer, les
prévisualiser et les lire ».

POURQUOI. Noa, 31/08, le corps des mails enfin lu : « les pièces jointes, il doit
les récupérer pour les rendre téléchargeables dans l'interface et les exploiter :
PNG par OCR, PDF, DWG — et pareil s'il y a des liens ». `lire_mail` n'en
rendait que le nom.

CE QUE CE BANC PROUVE, sans réseau : les fonctions PURES de `mail/pieces.py`
(extension, liens, textes d'un DXF, vignette d'un DWG reconstituée octet par
octet, archive), la lecture par type sur des fichiers fabriqués ici, le geste
`lire_message(pieces=True)` et `lire_piece` sur un fournisseur doublé (refs
liées à la boîte, dépôt, blocs d'écran multiples), les blocs multiples côté
agent, et le câblage (skill, effet, catalogue, journal, atelier, MIME).
"""
import asyncio
import importlib.util
import io
import logging
import pathlib
import re
import struct
import sys
import types
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Optional

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel):
    try:
        return (BACKEND / rel).read_text(encoding="utf-8")
    except OSError:
        return ""


print(f"\n═══ PIÈCES JOINTES ET LIENS — {BACKEND.parent}\n")

# Le module `mail.pieces` n'importe rien du projet au chargement : on le charge tel quel.
pieces = None
if (BACKEND / "mail" / "pieces.py").exists():
    spec = importlib.util.spec_from_file_location("pieces_banc", BACKEND / "mail" / "pieces.py")
    pieces = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pieces)
verifier("mail/pieces.py existe", pieces is not None)

if pieces:
    print("1. Fonctions pures")
    verifier("extension : du nom d'abord, du MIME sinon",
             pieces.extension("Plan-RDC.DWG", "application/octet-stream") == ".dwg"
             and pieces.extension("sans-extension", "application/pdf") == ".pdf"
             and pieces.extension("photo.jpeg") == ".jpeg")
    verifier("est_image : png/jpg/webp, ou MIME image", pieces.est_image("a.PNG") and pieces.est_image("x", "image/heic") and not pieces.est_image("devis.pdf"))
    corps = ("Bonjour, le devis est sur https://drive.google.com/file/d/abc. Voir aussi "
             "http://www.symbiose-paysage.fr/realisations, et https://drive.google.com/file/d/abc/ "
             "Désinscription : https://news.x.fr/unsubscribe?u=1 — merci.")
    liens = pieces.liens_du_texte(corps)
    verifier("liens : dédoublonnés, ponctuation retirée, désinscription écartée",
             liens == ["https://drive.google.com/file/d/abc", "http://www.symbiose-paysage.fr/realisations"], str(liens))
    dxf = "\n".join(["0", "SECTION", "2", "ENTITIES", "0", "TEXT", "8", "0", "1", "Terrasse bois 45 m2",
                      "0", "MTEXT", "1", "{\\fArial;Cote 12.50}\\PNiveau 0", "0", "LINE", "1", "pas un texte",
                      "0", "ATTRIB", "1", "CARTOUCHE : Villa Pereire", "0", "ENDSEC"])
    t = pieces.texte_dxf(dxf.encode("utf-8"))
    verifier("DXF : les textes des entités TEXT/MTEXT/ATTRIB, sans les codes de format, pas ceux d'une LINE",
             t.split("\n") == ["Terrasse bois 45 m2", "Cote 12.50 Niveau 0", "CARTOUCHE : Villa Pereire"], repr(t))

    # Un DWG fabriqué : en-tête AC1032, pointeur d'aperçu à 0x0D, une image PNG (code 6).
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    debut_apercu = 0x80
    entete = bytearray(b"AC1032" + b"\x00" * (debut_apercu - 6))
    struct.pack_into("<I", entete, 0x0D, debut_apercu)
    section = bytearray(b"\x1f\x25\x6d\x07\xd4\x36\x28\x28\x9d\x57\xca\x3f\x9d\x44\x10\x2b")  # sentinelle
    taille_img_start = debut_apercu + 16 + 4 + 1 + 9
    section += struct.pack("<I", 0) + bytes([1]) + bytes([6]) + struct.pack("<II", taille_img_start, len(png))
    dwg = bytes(entete) + bytes(section) + png
    image, mime, version = pieces.vignette_dwg(dwg)
    verifier("DWG : la vignette PNG est retrouvée à l'offset annoncé, et la version lue", image == png and mime == "image/png" and version == "AutoCAD 2018", f"{mime} {version}")
    # Une vignette BMP (code 2) : le BMP sans en-tête de fichier est recomposé.
    bih = struct.pack("<IiiHHIIiiII", 40, 4, 4, 1, 24, 0, 48, 0, 0, 0, 0) + b"\xff" * 48
    section2 = bytearray(section[:16]) + struct.pack("<I", 0) + bytes([1]) + bytes([2]) + struct.pack("<II", taille_img_start, len(bih))
    image2, mime2, _ = pieces.vignette_dwg(bytes(entete) + bytes(section2) + bih)
    verifier("DWG : une vignette BMP retrouve ses 14 octets d'en-tête (BM…)", image2 is not None and image2[:2] == b"BM" and mime2 == "image/bmp" and len(image2) == 14 + len(bih))
    verifier("un DWG sans aperçu ne casse rien", pieces.vignette_dwg(b"AC1027" + b"\x00" * 10) == (None, "", "AutoCAD 2013"))
    verifier("un fichier qui n'est pas un DWG : format inconnu, pas d'exception", pieces.vignette_dwg(b"pas un dwg")[2] == "format inconnu")
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("plans/RDC.pdf", b"x" * 10); zf.writestr("photo.jpg", b"y" * 5)
    verifier("archive : la liste de ce qu'elle contient", "plans/RDC.pdf (10 octets)" in pieces.lire_archive(z.getvalue()) and "photo.jpg" in pieces.lire_archive(z.getvalue()))
    verifier("une archive corrompue rend une chaîne vide", pieces.lire_archive(b"pas un zip") == "")

    print("\n2. Lecture par type (parseurs doublés)")
    faux_parsers = types.ModuleType("ingestion.parsers")
    class _NS(Exception): ...
    faux_parsers.FichierNonSupporte = _NS
    faux_parsers.lire_pdf = lambda b: "TEXTE DU PDF " + str(len(b))
    faux_parsers.lire_docx = lambda b: "TEXTE WORD"
    faux_parsers.lire_csv = lambda b: (["a", "b"], [{"a": "1", "b": "2"}])
    faux_parsers.lire_excel = lambda b: (["col"], [{"col": "v"}] * 250)
    faux_parsers.lire_xls = faux_parsers.lire_excel
    faux_parsers._decoder = lambda b: b.decode("utf-8", "replace")
    faux_parsers.ocr_disponible = lambda: True
    faux_parsers.ocr_image = lambda b: "OCR: " + b.decode("latin-1")[:8]
    paquet = types.ModuleType("ingestion"); paquet.__path__ = []
    sys.modules.update({"ingestion": paquet, "ingestion.parsers": faux_parsers})
    verifier("PDF → texte du PDF (OCR si scanné)", pieces.texte_de("devis.pdf", None, b"%PDF")["texte"].startswith("TEXTE DU PDF"))
    verifier("Word → texte", pieces.texte_de("cr.docx", None, b"PK")["texte"] == "TEXTE WORD")
    x = pieces.texte_de("liste.xlsx", None, b"PK")
    verifier("Excel → tableau borné à 200 lignes, et le reste est dit", x["texte"].count("\n") <= 202 and "50 ligne(s) de plus" in x["texte"] and "250 lignes" in x["methode"])
    verifier("CSV → tableau", pieces.texte_de("x.csv", "text/csv", b"a,b")["texte"] == "a | b\n1 | 2")
    verifier("image → OCR", pieces.texte_de("photo.png", "image/png", b"BONJOUR!")["texte"] == "OCR: BONJOUR!")
    verifier("DXF → textes du plan", "Terrasse bois 45 m2" in pieces.texte_de("plan.dxf", None, dxf.encode())["texte"])
    d = pieces.texte_de("plan.dwg", None, dwg)
    verifier("DWG → vignette + version, et le complément DIT que les entités ne sont pas lues", d["vignette"] == png and "AutoCAD 2018" in d["complement"] and "ne sont pas lues" in d["complement"])
    verifier("type inconnu → rien, téléchargeable seulement", pieces.texte_de("x.bin", None, b"\x00")["texte"] == "" and "téléchargeable" in pieces.texte_de("x.bin", None, b"\x00")["methode"])
    faux_parsers.lire_pdf = lambda b: (_ for _ in ()).throw(_NS("pdfplumber absent"))
    verifier("une dépendance absente se dit, sans exception", "non lu" in pieces.texte_de("devis.pdf", None, b"%PDF")["methode"])

    print("\n3. analyser() : dépôt + lecture, sur des dépôts doublés")
    depots = {"visuels": [], "fichiers": []}
    faux_visuels = types.ModuleType("visuels.depot")
    def _deposer_octets(octets, mime="image/png"):
        depots["visuels"].append((len(octets), mime)); return "cle" + str(len(depots["visuels"]))
    faux_visuels.deposer_octets = _deposer_octets
    faux_atelier = types.ModuleType("bureautique.atelier")
    def _deposer_fichier(nom, octets, proprietaire, origine=""):
        depots["fichiers"].append((nom, len(octets), proprietaire, origine)); return "jeton-" + nom
    faux_atelier.deposer_fichier = _deposer_fichier
    faux_llm = types.ModuleType("llm.router"); faux_llm.get_vision_candidates = lambda: []
    for n, m in (("visuels", faux_visuels), ("bureautique", faux_atelier), ("llm", faux_llm)):
        p = types.ModuleType(n); p.__path__ = []; sys.modules[n] = p
    sys.modules.update({"visuels.depot": faux_visuels, "bureautique.atelier": faux_atelier, "llm.router": faux_llm})
    faux_parsers.lire_pdf = lambda b: "Devis n°12 : terrasse bois 4 500 € HT"
    r = asyncio.run(pieces.analyser("devis.pdf", "application/pdf", b"%PDF-1.4", "u1"))
    verifier("un PDF est déposé à l'atelier (origine piece_jointe) et rend un bloc `fichier` avec URL",
             depots["fichiers"][-1][3] == "piece_jointe" and r["bloc"]["type"] == "fichier" and r["url"] == "/api/documents/jeton-devis.pdf" and r["bloc"]["format"] == "pdf")
    verifier("son texte est lu et la méthode dite", "4 500" in r["texte"] and "PDF" in r["methode"] and r["lisible"] is True)
    faux_parsers.ocr_image = lambda b: "SIRET 123 456 789 00012 — facture n°44 du 12/05"
    r = asyncio.run(pieces.analyser("scan.png", "image/png", b"\x89PNG" + b"\x00" * 20, "u1"))
    verifier("une image est déposée en visuel et rend un bloc `visuel` (aperçu + téléchargement)",
             depots["visuels"][-1][1] == "image/png" and r["bloc"]["type"] == "visuel" and r["bloc"]["images"][0]["cle"].startswith("cle"))
    verifier("sans modèle de vision, tesseract fait foi (le secours ne disparaît pas)",
             r["methode"] == "OCR de l'image" and "SIRET" in r["texte"])
    # LA VISION TRANSCRIT D'ABORD (01/09) : OCR suffisant + modèle disponible →
    # c'est la transcription du modèle qui fait foi, l'ébauche tesseract dans
    # la consigne — plus l'inverse.
    consignes_vues: list = []
    async def _transcrit(octets, mime, consigne):
        consignes_vues.append(consigne)
        return "FACTURE n°44 du 12/05 — SIRET 123 456 789 00012 — total 1 234,56 € TTC"
    pieces.decrire_image = _transcrit
    r = asyncio.run(pieces.analyser("scan2.png", "image/png", b"\x89PNG" + b"\x00" * 20, "u1"))
    verifier("OCR suffisant + vision disponible : la VISION transcrit, tesseract en ébauche",
             "1 234,56" in r["texte"] and "transcription par la vision" in r["methode"]
             and "TRANSCRIS" in consignes_vues[-1] and "SIRET 123 456 789 00012" in consignes_vues[-1])
    faux_parsers.ocr_image = lambda b: "x"
    async def _vision(octets, mime, consigne): return "Photo d'un jardin en pente avec une haie."
    pieces.decrire_image = _vision
    r = asyncio.run(pieces.analyser("chantier.jpg", "image/jpeg", b"\xff\xd8" + b"\x00" * 20, "u1"))
    verifier("l'OCR ne dit rien : la VISION décrit l'image", "jardin en pente" in r["texte"] and "vision" in r["methode"])
    r = asyncio.run(pieces.analyser("plan.dwg", None, dwg, "u1"))
    verifier("un DWG : fichier téléchargeable + vignette déposée en image + décrite par la vision",
             r["bloc"]["type"] == "fichier" and r.get("vignette", {}).get("cle") and "jardin" in r["texte"] and "AutoCAD 2018" in r["texte"])
    gros = b"x" * (pieces.MAX_OCTETS_PIECE + 1)
    r = asyncio.run(pieces.analyser("video.mp4", "video/mp4", gros, "u1"))
    verifier("trop lourde : déposée et téléchargeable, pas lue, et c'est dit", r["url"] and "trop lourde" in r["methode"] and r["texte"] == "")
    faux_parsers.lire_pdf = lambda b: "A" * 10000
    r = asyncio.run(pieces.analyser("long.pdf", None, b"%PDF", "u1"))
    verifier("le texte est borné et la coupure dite", len(r["texte"]) == pieces.MAX_TEXTE_PIECE and r["tronque"] is True)

print("\n4. lire_message(pieces=True) et lire_piece sur un fournisseur doublé (mail/lecture.py)")
src = lire("mail/lecture.py")
espace = {"Optional": Optional, "datetime": datetime, "timedelta": timedelta, "timezone": timezone, "__name__": "banc"}
try:
    tete = src[: src.index("def _domaine_entreprise(")]
    tete = re.sub(r"^from config import settings\n|^from mail\.collecte import fournisseur\n", "", tete, flags=re.M)
    exec(tete, espace)  # noqa: S102
    exec(src[src.index("def _kql_echapper("): src.index("async def _lire_outlook(")], espace)  # noqa: S102
    exec(src[src.index("# ── Les pièces jointes : une référence courte"):], espace)  # noqa: S102
    faux_pieces = types.ModuleType("mail.pieces")
    faux_pieces.liens_du_texte = pieces.liens_du_texte if pieces else (lambda t: [])
    faux_pieces.MAX_PIECES_PAR_MAIL = 8
    lus = []
    async def _analyser(nom, mime, brut, proprietaire):
        lus.append((nom, brut, proprietaire))
        return {"nom": nom, "type": "pdf", "taille": len(brut), "texte": "lu:" + nom, "methode": "PDF",
                "lisible": True, "url": "/api/documents/j-" + nom, "bloc": {"type": "fichier", "url": "/api/documents/j-" + nom, "nom": nom}}
    faux_pieces.analyser = _analyser
    pm = types.ModuleType("mail"); pm.__path__ = []
    sys.modules.update({"mail": pm, "mail.pieces": faux_pieces})
    telechargements = []
    async def _telecharger(boite, info):
        telechargements.append((boite, info["message"], info["id"])); return b"%PDF-" + info["id"].encode()
    espace["telecharger_piece"] = _telecharger
    async def _ouvrir(boite, identifiant):
        return {"ref": "r", "objet": "Devis terrasse", "de": "client@ext.fr", "a": "", "date": "", "date_iso": "",
                "lu": False, "apercu": "x", "corps": "Bonjour, le devis est joint. Voir https://drive.google.com/x. Cordialement",
                "pieces_jointes": [{"id": "ATT1", "nom": "devis.pdf", "taille": 1000, "type": "application/pdf"},
                                   {"id": "ATT2", "nom": "plan.dwg", "taille": 5000, "type": "application/octet-stream"}]}
    async def _lister(boite, dossier, limite, depuis, recherche=None, avant=None, apercu=None):
        return [{"ref": espace["_memoriser"]("MSG-1", boite), "objet": "Devis terrasse", "de": "client@ext.fr"}], None
    espace.update({"fournisseur": lambda: "outlook", "_ouvrir_outlook": _ouvrir, "_lire_outlook": _lister,
                   "logger": logging.getLogger("banc")})
    lire_message, lire_piece = espace["lire_message"], espace["lire_piece"]
    r = asyncio.run(lire_message("nath@x.fr"))
    verifier("sans `pieces` : les pièces portent une ref (16 hexa), pas l'identifiant Graph",
             all(re.fullmatch(r"[0-9a-f]{16}", p["ref"]) for p in r["pieces_jointes"]) and not any("id" in p for p in r["pieces_jointes"]))
    verifier("les liens du corps sont relevés", r["liens"] == ["https://drive.google.com/x"])
    verifier("la consigne dit comment récupérer les pièces et ouvrir les liens", "pieces: true" in r["a_faire"] and "ouvrir_page" in r["a_faire"])
    r = asyncio.run(lire_message("nath@x.fr", pieces=True, proprietaire="u1"))
    verifier("avec `pieces` : chaque pièce est téléchargée (boîte, message, id) puis lue pour la personne",
             [t[2] for t in telechargements] == ["ATT1", "ATT2"] and all(l[2] == "u1" for l in lus))
    verifier("les pièces lues portent texte et ref ; les blocs d'écran sont MULTIPLES (bloc_ui = liste)",
             [p["texte"] for p in r["pieces_lues"]] == ["lu:devis.pdf", "lu:plan.dwg"] and isinstance(r["bloc_ui"], list) and len(r["bloc_ui"]) == 2)
    verifier("la consigne dit que les cartes s'affichent seules", "s'affichent automatiquement" in r["a_faire"])
    ref_plan = r["pieces_lues"][1]["ref"]
    verifier("une ref de pièce ne s'ouvre pas dans une autre boîte", espace["piece_connue"](ref_plan, "eric@x.fr") is None and espace["piece_connue"](ref_plan, "NATH@x.fr") is not None)
    telechargements.clear()
    r = asyncio.run(lire_piece("nath@x.fr", ref=ref_plan, proprietaire="u1"))
    verifier("lire_piece par ref : une seule pièce, son bloc en `bloc_ui`, consigne « LUE »", telechargements == [("nath@x.fr", "MSG-1", "ATT2")] and r["bloc_ui"]["type"] == "fichier" and "LUE" in r["a_faire"])
    telechargements.clear()
    r = asyncio.run(lire_piece("nath@x.fr", nom="devis", proprietaire="u1"))
    verifier("lire_piece par nom, sans ref : le dernier message est ouvert, la pièce choisie par son nom", telechargements[-1][2] == "ATT1")
    try:
        asyncio.run(lire_piece("nath@x.fr", nom="inexistant.zip"))
        verifier("un nom inconnu : refus qui liste les pièces", False)
    except LookupError as e:
        verifier("un nom inconnu : refus qui liste les pièces", "devis.pdf" in str(e))
except Exception as e:  # noqa: BLE001
    verifier("lire_message/lire_piece s'exécutent sur le doublé", False, repr(e))

print("\n5. Le câblage")
skills = lire("mail/skills.py")
verifier("skill `lire_piece_jointe` déclaré, effet lecture", 'SKILLS_NATIFS["lire_piece_jointe"]' in skills and re.search(r'"lire_piece_jointe":\s*"lecture"', skills))
verifier("lire_mail transmet `pieces` et le propriétaire (la personne connectée)", "pieces=" in skills and "proprietaire=str(user.id)" in skills)
protocole = lire("skills/protocol.py")
verifier("catalogue : lire_mail accepte pieces ; lire_piece_jointe existe avec ref/nom/mail",
         re.search(r'"lire_mail": \(.*?"pieces"', protocole, re.S) and re.search(r'"lire_piece_jointe": \(.*?\["ref", "nom", "mail", "mailbox"\]', protocole, re.S))
verifier("journal : « je lis la pièce jointe »", '"lire_piece_jointe"' in lire("agents/journal.py"))
atelier = lire("bureautique/atelier.py")
verifier("atelier : deposer_fichier (n'importe quelle extension), et les pièces jointes ne comptent pas comme documents produits",
         "def deposer_fichier(" in atelier and 'origine") == "piece_jointe"' in atelier)
verifier("téléchargement : le type MIME suit l'extension (png, dwg, zip…), pas seulement docx/xlsx/pdf", "mimetypes" in lire("routers/documents_produits.py"))
agent1 = lire("agents/agent1.py")
verifier("agent1 : plusieurs blocs par résultat (`_blocs_de`) dans le rendu de secours et les livrables",
         "def _blocs_de(" in agent1 and agent1.count("_blocs_de(") >= 3)
verifier("router : plusieurs blocs par action validée", "_blocs_de(" in lire("agents/router.py"))
verifier("le prompt nomme `lire_piece_jointe`", "lire_piece_jointe" in agent1)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
