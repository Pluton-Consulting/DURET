"""
Banc « DU SERVEUR AU DOCUMENT REPRODUIT » (08/09).

Demande de Noa : « assure-toi que Duret est capable de récupérer et
prévisualiser un document Word, mais surtout de recréer des documents sur la
base de la structure visuelle d'un document de leur Drive ».

LA CHAÎNE ENTIÈRE EST JOUÉE, avec de VRAIS fichiers Word et Excel : un
document est posé sur un serveur doublé, désigné par son chemin, résolu
(`mail/attaches.py` → `outils/nas.py` → la couche du serveur), ouvert,
analysé, rempli, puis ROUVERT pour vérifier que la mise en page a survécu.
C'est la seule preuve qui vaille : un contrôle sur le source dirait que le
code appelle `save()`, il ne dirait pas que le logo est encore là.

CE QUI MANQUAIT AVANT LE 08/09, et que ce banc fixe :
1. ouvrir un document du serveur ne rendait que du texte — aucune carte, donc
   aucun aperçu à l'écran (`garantir_fichier_lu`, corrigé le matin) ;
2. la recherche par nom du serveur ne trouvait rien (paramètre mal formé),
   donc désigner un document par son nom échouait ;
3. reprendre la présentation d'un document exigeait de l'ENREGISTRER comme
   trame — permanent, plafonné — alors que reprendre la mise en page d'un
   devis trouvé dans un dossier est un geste ordinaire : d'où
   `reproduire_document`, deux temps (la structure, puis le document).

Prérequis : python-docx et openpyxl (dans requirements.txt ; le conteneur les
a). Sans eux, le banc le DIT et s'arrête proprement.
"""
import asyncio
import io
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ DU SERVEUR AU DOCUMENT REPRODUIT — {BACKEND.parent}\n")

try:
    import docx
    from openpyxl import Workbook, load_workbook
except ImportError:
    print("  ⚠ python-docx / openpyxl absents de cette machine : banc non joué.")
    print("    (ils sont dans requirements.txt ; le conteneur les a)")
    sys.exit(0)

SERVEUR_NAS = (BACKEND / "nas" / "acces.py").exists()


# ── Un VRAI devis Word, avec ce qui casse en pratique ──────────────────────
def devis_word() -> bytes:
    d = docx.Document()
    section = d.sections[0]
    section.header.paragraphs[0].text = "DURETSOLS — 12 rue des Ateliers — TVA FR00 123456789"
    section.footer.paragraphs[0].text = "Page 1 — document type"
    titre = d.add_paragraph()
    r = titre.add_run("DEVIS")
    r.bold = True
    # Le piège des runs : la référence est ÉCLATÉE, comme dans un document
    # retouché à la main. Un remplacement naïf ne la trouverait jamais.
    p = d.add_paragraph()
    p.add_run("Devis n° ")
    p.add_run("DEV-2025")
    p.add_run("-014")
    p.add_run(" du 12 septembre 2026")
    d.add_paragraph("Client : Monsieur Dupont")
    d.add_paragraph("Chantier : {lieu}")
    t = d.add_table(rows=2, cols=3)
    t.cell(0, 0).text = "Poste"
    t.cell(0, 1).text = "Quantité"
    t.cell(0, 2).text = "Prix"
    t.cell(1, 0).text = "Résine de sol"
    t.cell(1, 1).text = "120 m2"
    t.cell(1, 2).text = "9 600 €"
    tampon = io.BytesIO()
    d.save(tampon)
    return tampon.getvalue()


def suivi_excel() -> bytes:
    w = Workbook()
    f = w.active
    f.title = "Suivi"
    f["A1"] = "Chantier"
    f["B1"] = "Montant"
    f["A2"] = "Monsieur Dupont"
    f["B2"] = 9600
    f["B3"] = "=SUM(B2:B2)"
    f.column_dimensions["A"].width = 42
    tampon = io.BytesIO()
    w.save(tampon)
    return tampon.getvalue()


DEVIS = devis_word()
SUIVI = suivi_excel()
CHEMIN = "/home/Drive/03-Appel d'offres etudes/AFF 00 Dossier Modèle/devis type.docx"
FICHIERS = {CHEMIN: (DEVIS, "devis type.docx"),
            "/home/Drive/03-Appel d'offres etudes/suivi.xlsx": (SUIVI, "suivi.xlsx"),
            "/home/Drive/03-Appel d'offres etudes/plan.pdf": (b"%PDF-1.4 rien", "plan.pdf")}


def _poser(nom, **attrs):
    mod = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nom] = mod
    return mod


# ── Le serveur de fichiers, doublé au plus bas : la résolution réelle est
#    exercée par-dessus (mail/attaches.py → outils/nas.py ou drive.py). ──
class NasRefuse(PermissionError):
    pass


DEPOSES = {}


def _deposer_fichier(nom, octets, proprietaire, origine="depot"):
    jeton = f"JETON{len(DEPOSES) + 1}"
    DEPOSES[jeton] = {"nom": nom, "octets": octets, "proprietaire": proprietaire,
                      "origine": origine}
    return jeton


paquet_bur = _poser("bureautique")
atelier_double = _poser("bureautique.atelier", deposer_fichier=_deposer_fichier,
                        fiche=lambda *a, **k: None, chemin_fichier=lambda *a, **k: None)
paquet_bur.atelier = atelier_double
# LE MOTEUR EST LE VRAI : c'est lui qui rouvre le document et n'en change que
# le texte. Le doubler ne prouverait rien de ce qui compte ici.
_chemin_moteur = BACKEND / "bureautique" / "trame.py"
moteur_reel = types.ModuleType("bureautique.trame")
moteur_reel.__dict__["__file__"] = str(_chemin_moteur)
exec(compile(_chemin_moteur.read_text(encoding="utf-8"), str(_chemin_moteur), "exec"),
     moteur_reel.__dict__)
sys.modules["bureautique.trame"] = moteur_reel
paquet_bur.trame = moteur_reel
_poser("visuels")
_poser("visuels.depot", deposer_octets=lambda *a, **k: "cle")
_poser("database")
_poser("database.connection", get_db=lambda: None, get_rls_db=lambda *a: None)
_poser("skills")


class _Decl:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.effet = kw.get("effet")
        self.libelle = kw.get("libelle")


_poser("skills.registre", Declaration=_Decl)
_poser("config", settings=types.SimpleNamespace(synology_folders="/home", google_drive_perimetres=""))

if SERVEUR_NAS:
    # La couche basse du NAS : téléchargement et recherche par nom.
    async def _appel(client, base, api, method, version, sid=None, **params):
        import json as _j
        if api == "SYNO.FileStation.Search" and method == "start":
            fp = params.get("folder_path")
            if not (isinstance(fp, str) and fp.startswith("[")):
                raise RuntimeError("paramètre invalide")   # la forme nue est refusée
            return {"taskid": "t"}
        if api == "SYNO.FileStation.Search" and method == "list":
            motif = "devis type.docx"
            return {"finished": True,
                    "files": [{"name": FICHIERS[CHEMIN][1], "path": CHEMIN, "isdir": False}]
                    if motif else []}
        return {}

    async def _telecharger(client, base, sid, chemin):
        f = FICHIERS.get(chemin)
        return f[0] if f else None

    _poser("ingestion")
    _poser("ingestion.connectors")
    _poser("ingestion.connectors.synology", _appel=_appel, _telecharger=_telecharger)

    class _Cnx:
        async def __aenter__(self):
            return (None, "http://nas", "sid")

        async def __aexit__(self, *a):
            return False

    def _verifier(chemin):
        c = "/" + (chemin or "").strip("/")
        if not (c == "/home" or c.startswith("/home/")):
            raise NasRefuse(f"« {chemin} » est hors du périmètre autorisé.")
        return c

    async def _chercher_ouvert(client, base, sid, motif, dossier=None):
        trouves = [{"nom": n, "chemin": c, "dossier": False}
                   for c, (_, n) in FICHIERS.items() if motif.lower() in n.lower()]
        return {"motif": motif, "nombre": len(trouves), "resultats": trouves}

    _poser("nas")
    _poser("nas.acces", connexion=lambda: _Cnx(), verifier=_verifier,
           _chercher_ouvert=_chercher_ouvert, NasRefuse=NasRefuse,
           dossiers_autorises=lambda: ["/home"], normaliser=lambda c: "/" + c.strip("/"))

    chemin_outils = BACKEND / "outils" / "nas.py"
    outils = types.ModuleType("outils.nas")
    outils.__dict__["__file__"] = str(chemin_outils)
    _poser("outils")
    exec(compile(chemin_outils.read_text(encoding="utf-8"), str(chemin_outils), "exec"),
         outils.__dict__)
    sys.modules["outils.nas"] = outils
else:
    # Côté Drive : on double `outils.drive.octets`, seul point utilisé par
    # `mail/attaches.py` pour un fichier du serveur documentaire.
    async def _octets(nom, perimetres=None, identite=None):
        for c, (o, n) in FICHIERS.items():
            if nom in (c, n):
                return o, n, ""
        raise PermissionError(f"« {nom} » est introuvable sur le Drive.")

    _poser("outils")
    # `mail/attaches.py` recalcule le périmètre à partir du rôle : on double
    # les deux entrées qu'il importe, pas seulement la lecture d'octets.
    _poser("outils.drive", octets=_octets, DriveRefuse=PermissionError,
           perimetres_visibles=lambda role: [])
    _poser("skills.outils", _identite=lambda user: None)

# ── La résolution RÉELLE (mail/attaches.py), exécutée ──
chemin_att = BACKEND / "mail" / "attaches.py"
att = types.ModuleType("mail.attaches")
att.__dict__["__file__"] = str(chemin_att)
_poser("mail")
exec(compile(chemin_att.read_text(encoding="utf-8"), str(chemin_att), "exec"), att.__dict__)
sys.modules["mail.attaches"] = att

# ── Le skill, exécuté ──
chemin_sk = BACKEND / "skills" / "trames.py"
sk = types.ModuleType("skills.trames")
sk.__dict__["__file__"] = str(chemin_sk)
exec(compile(chemin_sk.read_text(encoding="utf-8"), str(chemin_sk), "exec"), sk.__dict__)


class _Moi:
    id = "u-1"
    email = "eric@duret.fr"
    role = "direction"


# ── 1. La désignation d'un document du serveur remonte ses octets ──
pretes, refusees = asyncio.run(att.resoudre([CHEMIN], _Moi(), "eric@duret.fr"))
verifier("un document désigné par son CHEMIN sur le serveur est résolu (octets + nom)",
         len(pretes) == 1 and pretes[0]["octets"] == DEVIS and pretes[0]["nom"].endswith(".docx"),
         (len(pretes), refusees))
if SERVEUR_NAS:
    pretes_nom, _ = asyncio.run(att.resoudre(["devis type.docx"], _Moi(), "eric@duret.fr"))
    verifier("…et par son NOM seul (la recherche du serveur, réparée le 08/09)",
             len(pretes_nom) == 1 and pretes_nom[0]["octets"] == DEVIS, len(pretes_nom))
    _, refus_hors = asyncio.run(att.resoudre(["/homes/prive/secret.docx"], _Moi(), "eric@duret.fr"))
    verifier("un chemin hors du périmètre reste REFUSÉ, avec sa raison",
             len(refus_hors) == 1 and "périmètre" in refus_hors[0]["raison"], refus_hors)

# ── 2. Premier temps : la STRUCTURE, pas encore le document ──
verifier("le geste `reproduire_document` existe", callable(getattr(sk, "reproduire_document", None)))
if callable(getattr(sk, "reproduire_document", None)):
    DEPOSES.clear()
    r = asyncio.run(sk.reproduire_document({"fichier": CHEMIN}, _Moi()))
    verifier("sans remplacements : la structure est rendue, AUCUN document n'est produit",
             "structure" in r and not DEPOSES and "bloc_ui" not in r, (list(r), list(DEPOSES)))
    s = r["structure"]
    verifier("la structure dit le type, les paragraphes, les tableaux et l'en-tête",
             s["type"] == "docx" and s["tableaux"] == 1 and s["entete"] is True and s["paragraphes"] >= 4, s)
    verifier("la variable {lieu} du document est reconnue", s["variables"] == ["lieu"], s["variables"])
    textes = " | ".join(r["textes"])
    verifier("les textes réels sont montrés, en-tête et cellules comprises",
             "Monsieur Dupont" in textes and "TVA FR00 123456789" in textes
             and "Résine de sol" in textes, textes[:200])
    verifier("l'a_faire ordonne de rappeler CE geste avec la table, sans deviner",
             "remplacements" in r["a_faire"] and "JAMAIS de mémoire" in r["a_faire"])

    # ── 3. Second temps : le document, et la mise en page qui survit ──
    r2 = asyncio.run(sk.reproduire_document({
        "fichier": CHEMIN,
        "remplacements": {"Monsieur Dupont": "Madame Martin",
                          "DEV-2025-014": "DEV-2026-207",
                          "{lieu}": "Mérignac",
                          "9 600 €": "11 400 €"}}, _Moi()))
    verifier("le document est produit et compte ses remplacements", r2.get("remplacements") == 4, r2.get("remplacements"))
    bloc = r2.get("bloc_ui") or {}
    verifier("une carte `fichier` GARANTIE est rendue, au format docx (donc l'aperçu s'affiche)",
             r2.get("bloc_garanti") is True and bloc.get("type") == "fichier"
             and bloc.get("format") == "docx" and str(bloc.get("nom", "")).endswith(".docx")
             and str(bloc.get("url", "")).startswith("/api/documents/"), bloc)
    verifier("l'a_faire interdit de réécrire un bloc et propose de retenir la trame",
             "n'écris aucun bloc" in r2["a_faire"] and "trame" in r2["a_faire"])

    produit = list(DEPOSES.values())[-1]
    verifier("le document est déposé sous l'origine « reproduction » (ni produit ni pièce jointe)",
             produit["origine"] == "reproduction" and produit["proprietaire"] == "u-1", produit["origine"])

    # LA PREUVE : on ROUVRE le document produit.
    relu = docx.Document(io.BytesIO(produit["octets"]))
    tous = [p.text for p in relu.paragraphs]
    tous += [c.text for t in relu.tables for l in t.rows for c in l.cells]
    entetes = [p.text for s in relu.sections for p in s.header.paragraphs]
    joint = " | ".join(tous)
    verifier("le texte est REMPLACÉ, y compris la référence éclatée en plusieurs runs",
             "Madame Martin" in joint and "DEV-2026-207" in joint
             and "Monsieur Dupont" not in joint and "DEV-2025-014" not in joint, joint[:220])
    verifier("la variable {lieu} est remplie", "Mérignac" in joint and "{lieu}" not in joint)
    verifier("le montant du TABLEAU est remplacé, la structure du tableau intacte",
             "11 400 €" in joint and len(relu.tables) == 1
             and len(relu.tables[0].rows) == 2 and len(relu.tables[0].columns) == 3)
    verifier("L'EN-TÊTE d'origine est conservé (logo, raison sociale, TVA)",
             any("TVA FR00 123456789" in e for e in entetes), entetes)
    verifier("le PIED de page est conservé",
             any("document type" in p.text for s in relu.sections for p in s.footer.paragraphs))
    verifier("le GRAS du titre a survécu (la mise en forme n'est pas reconstruite)",
             any(r.bold for p in relu.paragraphs for r in p.runs if p.text.strip() == "DEVIS"))

    # ── 4. Excel : les formules et les largeurs de colonnes ──
    r3 = asyncio.run(sk.reproduire_document({
        "fichier": "/home/Drive/03-Appel d'offres etudes/suivi.xlsx",
        "remplacements": {"Monsieur Dupont": "Madame Martin"}}, _Moi()))
    classeur = load_workbook(io.BytesIO(list(DEPOSES.values())[-1]["octets"]))
    f = classeur["Suivi"]
    verifier("Excel : la cellule est remplacée, la FORMULE et la largeur de colonne survivent",
             f["A2"].value == "Madame Martin" and f["B3"].value == "=SUM(B2:B2)"
             and round(f.column_dimensions["A"].width) == 42,
             (f["A2"].value, f["B3"].value, f.column_dimensions["A"].width))

    # ── 5. Les refus, et ce qu'ils disent ──
    try:
        asyncio.run(sk.reproduire_document(
            {"fichier": "/home/Drive/03-Appel d'offres etudes/plan.pdf"}, _Moi()))
        verifier("un PDF est refusé, en disant pourquoi", False)
    except sk.TrameInvalide as e:
        verifier("un PDF est refusé, en disant pourquoi (on ne le rouvre pas sans le reconstruire)",
                 "PDF" in str(e) and "reconstruire" in str(e), str(e)[:120])
    try:
        asyncio.run(sk.reproduire_document({}, _Moi()))
        verifier("sans référence, le refus dit où prendre le chemin", False)
    except sk.TrameInvalide as e:
        verifier("sans référence, le refus dit où prendre le chemin (un listage du serveur)",
                 "chemin" in str(e).lower() and "list" in str(e).lower(), str(e)[:120])
    try:
        asyncio.run(sk.reproduire_document({"fichier": "/home/inconnu.docx"}, _Moi()))
        verifier("une référence introuvable est refusée avec sa raison", False)
    except sk.TrameInvalide as e:
        verifier("une référence introuvable est refusée avec sa raison", "retrouve pas" in str(e), str(e)[:100])

# ── 6. Enregistrer une trame depuis le serveur (l'autre voie, permanente) ──
verifier("`enregistrer_trame` accepte la même désignation (elle passe par la même résolution)",
         "from mail.attaches import resoudre" in chemin_sk.read_text(encoding="utf-8"))

# ── 7. Le catalogue ──
d = sk.SKILLS.get("reproduire_document")
verifier("le geste est au catalogue, en écriture interne (rien ne sort de l'entreprise)",
         d is not None and d.effet == "ecriture_interne")
verifier("sa description dit les deux temps et les formulations du métier",
         d is not None and "SANS `remplacements`" in d.description
         and "meme presentation" in d.description.lower())

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
