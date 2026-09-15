"""
Banc « ENREGISTRE-LE, MAIS REMPLACE STUDIO PAR SYMBIOSE PAYSAGE » — export
Langfuse du 14/09, 14:56, fil c9f5a00d (Symbiose, compte direction).

La personne a montré le dossier de présentation qu'elle veut rendre à ses
clients (« Dossier de conception paysagère - Mr et Mme Lavèze », un PDF du
Drive), puis : « tu peux l'enregistrer mais tu devras remplacer studio par
symbiose paysage dans la page de garde ». 3 min 21, neuf gestes, et ceci :
  1. `enregistrer_trame` par NOM → « pèse trop lourd pour un message. Envoie
     plutôt le lien de partage » : la limite d'une PIÈCE DE MAIL (20 Mo),
     appliquée à une trame, avec une raison fausse pour qui n'envoyait rien ;
  2. `enregistrer_trame` par l'IDENTIFIANT que `drive_ouvrir` venait de rendre
     → « Aucun fichier nommé « 1kX3oLMd… » » : seul le nom se résolvait ;
  3. et de toute façon, un PDF était refusé comme trame. Alors le modèle a
     FABRIQUÉ un Word de trois pages, l'a retenu sous le même nom, a rejoué
     quatre fois « STUDIO → Symbiose Paysage » sur ce Word qui ne contenait
     pas STUDIO (chaque essai rendait une copie conforme, et une carte de
     plus), puis a affirmé au tour suivant que « le modèle est enregistré
     avec la structure du dossier Lavèze ». Faux.

CE QUE CE BANC PROUVE (sans base, sans réseau, sans modèle) :
  · le moteur PDF (PyMuPDF, dans l'image) EXÉCUTÉ sur une page de garde
    fabriquée comme la vraie — photo pleine page, « STUDIO » dessiné TROIS
    fois pour le contour : la recherche voit « STUDIO », casse et accents
    ignorés en dernier recours ; le texte est remplacé À SA PLACE, la photo
    reste (aucun cache blanc), la page 2 aussi ; les textes proches se disent ;
  · la résolution d'une pièce prend le plafond de l'APPELANT, et la raison
    d'un refus ne parle plus de mail hors d'un mail ;
  · un identifiant de fichier du Drive déjà résolu pour CETTE identité se
    résout ; inconnu ou d'une autre identité, jamais ;
  · `enregistrer_trame` EXÉCUTÉ (base doublée) : un PDF est retenu APRÈS ses
    remplacements, et le dit ; une table qui ne trouve rien n'enregistre
    rien et nomme ce qui ressemble ;
  · `utiliser_trame` EXÉCUTÉ : zéro remplacement = un échec, aucune copie ;
  · `_trame_substituee` EXÉCUTÉ sur la séquence exacte de 14:56 : retenir le
    Word fabriqué après l'échec est refusé ; « crée un devis type et
    retiens-le » (sans échec préalable) passe.
Tombe sur la version d'avant (PDF refusé, plafond de mail, identifiant inconnu).

Usage : python backend/scripts/test_trame_pdf.py [backend]
         (PyMuPDF requis pour la partie moteur : venv jetable ou conteneur)
"""
import asyncio
import ast
import importlib
import io
import json
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:400]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


try:
    import fitz  # noqa: F401
    FITZ = True
except ImportError:
    FITZ = False
    print("  (PyMuPDF absent : la partie moteur est SAUTÉE — à jouer dans le conteneur ou un venv)")

trame = importlib.import_module("bureautique.trame")


def page_de_garde() -> bytes:
    """Une page de garde comme celle de Lavèze : photo pleine page, titre à contour."""
    import fitz
    from PIL import Image
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    tampon = io.BytesIO()
    Image.new("RGB", (842, 595), (46, 104, 64)).save(tampon, "JPEG")
    page.insert_image(page.rect, stream=tampon.getvalue())
    page.insert_text((300, 180), "PRÉSENTATION PROJET", fontname="helv", fontsize=20, color=(1, 1, 1))
    page.insert_text((300, 220), "Mr et Mme Lavèze", fontname="helv", fontsize=16, color=(1, 1, 1))
    for dx in (0, 0.3, 0.6):   # le contour : trois fois le même mot
        page.insert_text((360 + dx, 320), "STUDIO", fontname="hebo", fontsize=30, color=(1, 1, 1))
    p2 = doc.new_page(width=842, height=595)
    p2.insert_text((50, 60), "Aménagement Paysager / Plan de masse", fontname="helv", fontsize=14)
    p2.insert_text((50, 90), "Document réalisé par STUDIO", fontname="helv", fontsize=10)
    return doc.tobytes()


# ── 1. Le moteur PDF ────────────────────────────────────────────────────────
print("1. Le PDF se remplit à sa place")
verifier("un PDF est un type de trame", trame.type_de("Dossier Lavèze.pdf") == "pdf"
         and trame.type_de("x", "application/pdf") == "pdf")
verifier("le plafond d'un PDF est le sien (dossier de présentation)",
         trame.plafond_octets("pdf") >= 50 * 1024 * 1024 and trame.plafond_octets("docx") == trame.MAX_OCTETS)
if FITZ:
    import fitz
    origine = page_de_garde()
    analyse = trame.analyser(origine, "pdf")
    verifier("l'analyse voit « STUDIO » une fois (contour regroupé)",
             analyse["textes"].count("STUDIO") == 1 and analyse["pages"] == 2, analyse["textes"])
    verifier("l'analyse compte la photo", analyse["images"] == 1, analyse)
    sortie, faits = trame.remplir(origine, "pdf", {"studio": "Symbiose Paysage",
                                                   "Mr et Mme Lavèze": "M. CAMP Nicolas"})
    rendu = fitz.open(stream=sortie, filetype="pdf")
    texte = "".join(p.get_text() for p in rendu)
    verifier("« studio » demandé remplace « STUDIO » imprimé (page de garde ET page 2)",
             faits == 3 and "STUDIO" not in texte and texte.count("Symbiose Paysage") == 2, (faits, texte))
    verifier("le nom du client est remplacé", "M. CAMP Nicolas" in texte and "Lavèze" not in texte, texte)
    verifier("la photo de fond est toujours là", len(rendu[0].get_images()) == 1)
    pix = rendu[0].get_pixmap(dpi=36)
    # Au centre de l'ancien mot, entre les lettres : la photo, pas un cache blanc.
    x, y = int(365 * 36 / 72), int(300 * 36 / 72)
    r, g, b = pix.pixel(x, y)[:3]
    verifier("aucun rectangle blanc là où était « STUDIO »", not (r > 240 and g > 240 and b > 240), (r, g, b))
    verifier("le texte intact ne bouge pas", "PRÉSENTATION PROJET" in texte)
    verifier("« Studio » trouve « STUDIO » parmi les proches",
             "STUDIO" in trame.textes_proches(analyse["textes"], "Studio"),
             trame.textes_proches(analyse["textes"], "Studio"))
    verifier("« Presentation projet » (sans accent) trouve le vrai titre",
             trame.textes_proches(analyse["textes"], "Presentation projet") == ["PRÉSENTATION PROJET"],
             trame.textes_proches(analyse["textes"], "Presentation projet"))

# ── 2. Le plafond est celui de l'appelant ───────────────────────────────────
print("2. La résolution d'une pièce")
vus = {}
# Le socle documentaire diverge par client : le Drive chez Symbiose, le NAS chez
# Duret. Le banc double celui qui existe, le contrôle est le même.
COTE_DRIVE = (BACKEND / "outils/drive.py").exists()
stockage = types.ModuleType("outils.drive" if COTE_DRIVE else "outils.nas")


async def _octets(nom, perimetres=None, identite=None, plafond=20 * 1024 * 1024):
    vus["plafond"] = plafond
    return b"%PDF" + b"0" * (25 * 1024 * 1024), "Dossier Lavèze.pdf", "application/pdf"
stockage.octets = _octets
stockage.perimetres_visibles = lambda role: [("racine", "all")]
outils_pkg = types.ModuleType("outils")
outils_pkg.__path__ = []
sys.modules["outils"], sys.modules[stockage.__name__] = outils_pkg, stockage
skills_outils = types.ModuleType("skills.outils")
skills_outils._identite = lambda user: str(user.id)
sys.modules["skills.outils"] = skills_outils
sys.modules.pop("mail.attaches", None)
attaches = importlib.import_module("mail.attaches")
user = types.SimpleNamespace(id="u-direction", email="direction@exemple-paysage.fr", role="direction")
pretes, refus = asyncio.run(attaches.resoudre(["Dossier Lavèze.pdf"], user, "direction@exemple-paysage.fr"))
verifier("pour un MAIL : 25 Mo refusés, avec la raison du mail",
         not pretes and refus and "mail" in refus[0]["raison"], refus)
pretes, refus = asyncio.run(attaches.resoudre(["Dossier Lavèze.pdf"], user, "x", plafond=60 * 1024 * 1024))
verifier("pour une TRAME : 25 Mo acceptés, et le plafond est transmis au Drive",
         pretes and vus.get("plafond") == 60 * 1024 * 1024, (refus, vus))
pretes, refus = asyncio.run(attaches.resoudre(["Dossier Lavèze.pdf"], user, "x", plafond=10 * 1024 * 1024))
verifier("hors mail, un refus ne parle pas de mail", refus and "mail" not in refus[0]["raison"], refus)
for m in ("outils", "outils.drive", "outils.nas", "skills.outils"):
    sys.modules.pop(m, None)

# ── 3. L'identifiant d'un fichier déjà ouvert ───────────────────────────────
print("3. L'identifiant rendu par drive_ouvrir" + ("" if COTE_DRIVE else " — sans objet ici (le NAS désigne par chemin)"))
src_drive = (BACKEND / "outils/drive.py").read_text(encoding="utf-8") if COTE_DRIVE else ""
arbre = ast.parse(src_drive)
espace = {"re": __import__("re"), "Optional": __import__("typing").Optional}
for n in arbre.body:
    cibles = (n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else [])
    if (isinstance(n, ast.FunctionDef) and n.name in ("_retenir_resolu", "fichier_resolu", "_cle_client")) or any(
            isinstance(t, ast.Name) and t.id in ("_RESOLUS", "_DUREE_RESOLU_S", "_MAX_RESOLUS", "RE_ID_DRIVE")
            for t in cibles):
        exec(compile(ast.Module(body=[n], type_ignores=[]), "drive", "exec"), espace)
if not COTE_DRIVE:
    nas_src = (BACKEND / "outils/nas.py").read_text(encoding="utf-8")
    verifier("le NAS prend aussi le plafond de l'appelant", "async def octets(nom_ou_chemin: str, plafond" in nas_src)
elif "fichier_resolu" not in espace:
    verifier("outils/drive.py retient les fichiers résolus", False, "fichier_resolu absent")
else:
    ID = "1kX3oLMd-6x22bfLZLM_zlSGg9Bg44YWm"
    espace["_retenir_resolu"]("u-direction", {"id": ID, "name": "Dossier Lavèze.pdf", "size": "31000000"})
    verifier("l'identifiant rendu à cette personne se résout",
             (espace["fichier_resolu"](ID, "u-direction") or {}).get("name") == "Dossier Lavèze.pdf")
    verifier("« drive:<id> » aussi", bool(espace["fichier_resolu"]("drive:" + ID, "u-direction")))
    verifier("le même identifiant, pour une AUTRE identité : rien",
             espace["fichier_resolu"](ID, "u-collegue") is None)
    verifier("un identifiant jamais rendu : rien",
             espace["fichier_resolu"]("1AbCdEfGhIjKlMnOpQrStUvWxYz012345", "u-direction") is None)
    verifier("`_resoudre_fichier` passe par les fichiers déjà résolus",
             "deja = fichier_resolu(nom, identite)" in src_drive and "_retenir_resolu(identite, fichier)" in src_drive)
    verifier("la carte d'un fichier ouvert n'a plus la limite d'un mail",
             "MAX_OCTETS_AFFICHAGE" in src_drive.split("async def _deposer_pour")[1][:900])

# ── 4. Les trames, exécutées ────────────────────────────────────────────────
print("4. enregistrer_trame / utiliser_trame")
if FITZ:
    base = {"trames": []}

    class Conn:
        async def fetchval(self, *a):
            return len(base["trames"])

        async def execute(self, sql, *a):
            if sql.lstrip().startswith("INSERT INTO trames"):
                base["trames"].append({"nom": a[0], "genre": a[1], "type_fichier": a[2],
                                       "nom_fichier": a[3], "contenu": a[4], "variables": a[7],
                                       "actif": True})

        async def fetch(self, sql, *a):
            return [t for t in base["trames"] if t["nom"].lower() == str(a[0]).lower()]

    class Ctx:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *a):
            return False
    connexion = types.ModuleType("database.connection")
    connexion.get_db = lambda: Ctx()
    sys.modules["database"] = types.ModuleType("database")
    sys.modules["database.connection"] = connexion
    registre = types.ModuleType("skills.registre")
    registre.Declaration = lambda **k: k
    sys.modules["skills.registre"] = registre
    faux_attaches = types.ModuleType("mail.attaches")

    async def _resoudre(brut, user_, boite, plafond=None):
        return [{"nom": "Dossier de conception paysagère - Mr et Mme Lavèze.pdf",
                 "mime": "application/pdf", "octets": origine}], []
    faux_attaches.resoudre = _resoudre
    sys.modules["mail.attaches"] = faux_attaches
    atelier = types.ModuleType("bureautique.atelier")
    atelier.deposer_fichier = lambda nom, octets, proprio, origine="": "J" * 32
    sys.modules["bureautique.atelier"] = atelier
    import bureautique
    bureautique.atelier = atelier
    sys.modules.pop("skills.trames", None)
    trames = importlib.import_module("skills.trames")

    r = asyncio.run(trames.enregistrer_trame({
        "nom": "Dossier de conception paysagère", "genre": "document",
        "fichier": "1kX3oLMd-6x22bfLZLM_zlSGg9Bg44YWm",
        "remplacements": {"STUDIO": "Symbiose Paysage"}}, user))
    stocke = base["trames"][-1] if base["trames"] else {}
    texte_stocke = "".join(p.get_text() for p in fitz.open(stream=stocke.get("contenu") or b"", filetype="pdf")) \
        if stocke.get("contenu") else ""
    verifier("le PDF est retenu comme trame", r.get("enregistree") and stocke.get("type_fichier") == "pdf", r)
    verifier("ce qui est retenu porte DÉJÀ « Symbiose Paysage », plus « STUDIO »",
             "Symbiose Paysage" in texte_stocke and "STUDIO" not in texte_stocke, texte_stocke)
    verifier("le résultat dit le remplacement et ce qu'un PDF retenu sait faire",
             "Symbiose Paysage" in r["message_final"] and "images" in r["message_final"], r["message_final"])
    try:
        asyncio.run(trames.enregistrer_trame({
            "nom": "Autre", "fichier": "x.pdf", "remplacements": {"Studio Lavèze": "Symbiose"}}, user))
        verifier("une table qui ne trouve rien n'enregistre rien", False, "enregistré quand même")
    except trames.TrameInvalide as e:
        verifier("une table qui ne trouve rien n'enregistre rien",
                 "PAS été enregistrée" in str(e) and len(base["trames"]) == 1, e)
        verifier("… et dit de ne pas relancer la même table", "Ne relance PAS" in str(e), e)
    try:
        asyncio.run(trames.utiliser_trame({"trame": "Dossier de conception paysagère",
                                           "remplacements": {"STUDIO": "Symbiose Paysage"}}, user))
        verifier("utiliser_trame sans remplacement effectif : un ÉCHEC, aucune copie", False, "copie rendue")
    except trames.TrameInvalide as e:
        verifier("utiliser_trame sans remplacement effectif : un ÉCHEC, aucune copie",
                 "Aucun des textes cherchés" in str(e), e)
        verifier("… qui cite ce qui ressemble", "Symbiose Paysage" in str(e) or "rien d'approchant" in str(e), e)
    ok = asyncio.run(trames.utiliser_trame({"trame": "Dossier de conception paysagère",
                                            "remplacements": {"Mr et Mme Lavèze": "M. CAMP Nicolas"}}, user))
    verifier("reprendre la trame pour un autre client rend un PDF",
             ok.get("remplacements") == 1 and ok["fichier"].endswith(".pdf"), ok)

# ── 5. On ne retient pas à la place de ce qu'on a montré ─────────────────────
print("5. La substitution est refusée")
src = (BACKEND / "agents/agent1.py").read_text(encoding="utf-8")
arbre = ast.parse(src)
espace = {"_re_images": __import__("re")}
for n in arbre.body:
    if (isinstance(n, ast.FunctionDef) and n.name == "_trame_substituee") or (
            isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in (
                "_RE_JETON_ATELIER", "_GESTES_QUI_FABRIQUENT") for t in n.targets)):
        exec(compile(ast.Module(body=[n], type_ignores=[]), "agent1", "exec"), espace)
if "_trame_substituee" not in espace:
    verifier("agent1 refuse la trame substituée", False, "_trame_substituee absent")
else:
    FAB = "fItbeyH6BAp4jbu88WYdhj1av8OcuvBK"
    sequence = [
        {"skill": "enregistrer_trame", "ok": False,
         "args": {"fichier": "Dossier de conception paysagère - Mr et Mme Lavèze- 03-06-26.pdf"},
         "resultat_masque": "ERREUR : Je ne retrouve pas « Dossier … .pdf » : pèse trop lourd."},
        {"skill": "drive_ouvrir", "ok": True, "args": {"nom": "Dossier … .pdf"},
         "resultat_masque": json.dumps({"id": "1kX3oLMd-6x22bfLZLM_zlSGg9Bg44YWm"})},
        {"skill": "creer_document", "ok": True, "args": {"titre": "Modèle"},
         "resultat_masque": json.dumps({"document_id": FAB, "format": "docx"})},
        {"skill": "terminer_document", "ok": True, "args": {"document_id": FAB},
         "resultat_masque": json.dumps({"url": f"/api/documents/{FAB}"})},
    ]
    refus = espace["_trame_substituee"]({"nom": "Dossier", "fichier": f"/api/documents/{FAB}"}, sequence)
    verifier("retenir le Word fabriqué après l'échec est REFUSÉ, avec la vraie raison",
             refus and "FABRIQUÉ" in refus and "trop lourd" in refus and "Lavèze" in refus, refus)
    verifier("« crée un devis type et retiens-le » (aucun échec avant) passe",
             espace["_trame_substituee"]({"fichier": FAB}, sequence[2:]) is None)
    verifier("retenir le VRAI fichier après l'échec passe",
             espace["_trame_substituee"]({"fichier": "1kX3oLMd-6x22bfLZLM_zlSGg9Bg44YWm"}, sequence) is None)
    verifier("la garde est posée avant l'exécution dans tools_node",
             "_trame_substituee(args, resultats)" in src)

print()
if echecs:
    print(f"ÉCHEC : {len(echecs)} contrôle(s)")
    sys.exit(1)
print("Tous les contrôles passent." + ("" if FITZ else " (moteur PDF non joué)"))
