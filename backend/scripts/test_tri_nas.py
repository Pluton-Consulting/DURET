"""
Banc du TRI AVANT LA LECTURE du NAS (15/09, Duret — `nas/tri.py`).

Demande de Noa : « l'enrichir via lecture du NAS c'est bien, mais beaucoup trop
long et ça bouffe le serveur ; via l'IA pour qu'elle juge ce qui est pertinent ? »
→ « mets tout en place ».

CE QUE CE BANC PROUVE (NAS, modèle et base doublés) :
  1. les règles : la plus longue l'emporte, une décision inconnue est écartée ;
     le filtre SANS IA (photos, fichiers trop anciens, doublons) ;
  2. la proposition EXÉCUTÉE : l'IA juge les dossiers du premier degré sur leurs
     NOMS (aucun fichier téléchargé), « détailler » fait juger les sous-dossiers,
     un chemin inventé par le modèle est ignoré, rien n'est appliqué seul ;
  3. l'OCR remis à plus tard : `en_lecture(ocr=False)` lève `OcrReporte` sur un
     PDF scanné, un PDF qui a du texte est lu quand même, la nuit lit tout ;
  4. la VRAIE synchronisation : « ignorer » et « à la demande » ne sont pas
     ouverts, une copie non plus, les plus récents d'abord, le scan de jour est
     noté pour la nuit puis lu la nuit ;
  5. le câblage : routes, montage, boucle de nuit, réglages, écran.
Tombe sur la version d'avant (`nas/tri.py` absent).

Usage : python backend/scripts/test_tri_nas.py [backend]
"""
import asyncio
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import time
import types
from contextlib import asynccontextmanager

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
os.environ["DOCUMENTS_DIR"] = tempfile.mkdtemp(prefix="banc-tri-")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def poser(nom, **attrs):
    mod = types.ModuleType(nom)
    mod.__dict__.update(attrs)
    sys.modules[nom] = mod
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            poser(parent)
        setattr(sys.modules[parent], feuille, mod)
    return mod


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, BACKEND / chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            poser(parent)
        setattr(sys.modules[parent], feuille, mod)
    spec.loader.exec_module(mod)
    return mod


if not (BACKEND / "nas" / "tri.py").exists():
    verifier("nas/tri.py existe", False, "absent")
    print(f"\n✗ {len(echecs)} échec(s)")
    sys.exit(1)

SETTINGS = types.SimpleNamespace(
    synology_folders="/home", synology_access_level="all", synology_source_type="nas",
    synology_max_file_mb=25, synology_verify_tls=False, nas_tri_age_ans=3,
    nas_ocr_nuit_debut=21, nas_ocr_nuit_fin=6)
poser("config", settings=SETTINGS)
poser("llm.reglages", texte=lambda nom: "", valeur=lambda nom: "")
charger("security.lecteur", "security/lecteur.py")
acces = charger("nas.acces", "nas/acces.py")
charger("nas.niveaux", "nas/niveaux.py")
tri = charger("nas.tri", "nas/tri.py")
# Le paquet `ingestion` importe la base : ses deux modules utiles sont posés à la main.
poser("ingestion.pipeline", ingest_document=None)
parsers = charger("ingestion.parsers", "ingestion/parsers.py")
MAINTENANT = time.time()
AN = 365.25 * 86400

print("1. Les règles et le filtre sans IA")
regles = tri.lire_regles(json.dumps([
    {"chemin": "/home/Drive/Archives", "decision": "demande"},
    {"chemin": "/home/Drive/Archives/Modèles", "decision": "apprendre"},
    {"chemin": "/home/Drive/Photos", "decision": "ignorer"},
    {"chemin": "/home/Drive/X", "decision": "supprimer"}]))
verifier("une décision inconnue est écartée", len(regles) == 3, regles)
verifier("la règle la plus longue l'emporte",
         tri.decision_du_chemin("/home/Drive/Archives/Modèles/devis type.docx", regles) == "apprendre"
         and tri.decision_du_chemin("/home/Drive/Archives/2019/CCTP.pdf", regles) == "demande")
verifier("sans règle : à apprendre (le comportement d'avant)",
         tri.decision_du_chemin("/home/Drive/03-Appel d'offres/RC.pdf", regles) == "apprendre")
verifier("casse et accents ne font pas deux dossiers",
         tri.decision_du_chemin("/home/drive/archives/modeles/x.pdf", regles) == "apprendre")
verifier("une photo est écartée sans être ouverte",
         tri.ecarte_sans_ia({"nom": "IMG_2031.JPG", "modifie": MAINTENANT}, MAINTENANT, 3) == "photo")
verifier("un fichier de plus de 3 ans est écarté",
         tri.ecarte_sans_ia({"nom": "CCTP.pdf", "modifie": MAINTENANT - 4 * AN}, MAINTENANT, 3) == "ancien")
verifier("0 an = aucune limite", tri.ecarte_sans_ia({"nom": "CCTP.pdf", "modifie": MAINTENANT - 9 * AN}, MAINTENANT, 0) is None)
copies = [{"chemin": "/a/CCTP type.pdf", "nom": "CCTP type.pdf", "octets": 5000, "modifie": 100},
          {"chemin": "/b/CCTP type.pdf", "nom": "CCTP type.pdf", "octets": 5000, "modifie": 300},
          {"chemin": "/c/cctp TYPE.pdf", "nom": "cctp TYPE.pdf", "octets": 5000, "modifie": 200},
          {"chemin": "/d/CCTP type.pdf", "nom": "CCTP type.pdf", "octets": 7000, "modifie": 50},
          {"chemin": "/e/Notes.pdf", "nom": "Notes.pdf", "octets": None, "modifie": 1},
          {"chemin": "/f/Notes.pdf", "nom": "Notes.pdf", "octets": None, "modifie": 2}]
verifier("des copies (même nom, même taille) : seule la plus récente est lue",
         tri.doublons(copies) == {"/a/CCTP type.pdf", "/c/cctp TYPE.pdf"}, tri.doublons(copies))
verifier("sans taille connue, deux fichiers de même nom ne sont pas des doublons", "/e/Notes.pdf" not in tri.doublons(copies))
verifier("la nuit : 23 h et 3 h oui, 10 h et 20 h non",
         tri.fenetre_de_nuit(23) and tri.fenetre_de_nuit(3) and not tri.fenetre_de_nuit(10) and not tri.fenetre_de_nuit(20))

print("2. La proposition de l'IA, exécutée")
CATALOGUE = []


def dossier(c):
    CATALOGUE.append({"chemin": c, "nom": c.rsplit("/", 1)[-1], "dossier": True})


def fichier(c, age_ans=0.5, octets=4096):
    CATALOGUE.append({"chemin": c, "nom": c.rsplit("/", 1)[-1], "dossier": False,
                      "octets": octets, "modifie": MAINTENANT - age_ans * AN})


for c in ("/home/Drive", "/home/Drive/03-Appel d'offres", "/home/Drive/03-Appel d'offres/ETUDES EN COURS",
          "/home/Drive/03-Appel d'offres/ETUDES TERMINEE", "/home/Drive/Photos chantier", "/home/Drive/Compta"):
    dossier(c)
fichier("/home/Drive/03-Appel d'offres/ETUDES EN COURS/RC Pessac.pdf", 0.1)
fichier("/home/Drive/03-Appel d'offres/ETUDES EN COURS/CCTP lot 12.pdf", 0.2)
fichier("/home/Drive/03-Appel d'offres/ETUDES EN COURS/scan DPGF.pdf", 0.05)
fichier("/home/Drive/03-Appel d'offres/ETUDES TERMINEE/CCTP 2019.pdf", 6)
fichier("/home/Drive/Photos chantier/IMG_001.jpg", 0.3)
fichier("/home/Drive/Compta/facture BTF.pdf", 0.4)
fichier("/home/Drive/Compta/copie/CCTP lot 12.pdf", 0.9)

acces.dossiers_autorises = lambda: ["/home"]


async def _catalogue_attendu(**k):
    return list(CATALOGUE), True
acces.catalogue_attendu = _catalogue_attendu

PROMPTS = []


class _LLM:
    async def ainvoke(self, messages, config=None):
        prompt = messages[0].content
        PROMPTS.append(prompt)
        if '"chemin": "/home/Drive"' in prompt:
            return types.SimpleNamespace(content=json.dumps({"decisions": [
                {"chemin": "/home/Drive", "decision": "detailler", "raison": "tout le classement"}]}))
        return types.SimpleNamespace(content="Voici : " + json.dumps({"decisions": [
            {"chemin": "/home/Drive/03-Appel d'offres", "decision": "apprendre", "raison": "appels d'offres"},
            {"chemin": "/home/Drive/Photos chantier", "decision": "ignorer", "raison": "photos"},
            {"chemin": "/home/Drive/Compta", "decision": "demande", "raison": "comptabilité"},
            {"chemin": "/home/Drive/Inventé", "decision": "ignorer", "raison": "n'existe pas"}]}))


poser("llm.router", get_llm=lambda tier: _LLM(), LLMTier=types.SimpleNamespace(STANDARD="standard", LIGHT="light"))
poser("langchain_core.messages", HumanMessage=lambda content: types.SimpleNamespace(content=content))
etat = asyncio.run(tri.proposer(lance_par="noa"))
decisions = {d["chemin"]: d["decision"] for d in etat.get("dossiers") or []}
verifier("« détailler » fait juger les sous-dossiers, le premier degré puis le suivant",
         len(PROMPTS) == 2 and decisions.get("/home/Drive/03-Appel d'offres") == "apprendre"
         and decisions.get("/home/Drive/Photos chantier") == "ignorer"
         and decisions.get("/home/Drive/Compta") == "demande", (len(PROMPTS), decisions))
verifier("un dossier inventé par le modèle n'entre pas dans la proposition", "/home/Drive/Inventé" not in decisions)
verifier("l'IA juge sur les NOMS : chemin, sous-dossiers, exemples de fichiers",
         "exemples_de_fichiers" in PROMPTS[-1] and "RC Pessac.pdf" in PROMPTS[-1] or "CCTP" in PROMPTS[-1], PROMPTS[-1][:300])
verifier("la proposition est RANGÉE, jamais appliquée seule", tri.regles() == [] and etat.get("estimation"), etat.get("estimation"))
est = etat["estimation"]
verifier("l'estimation compte ce que le tri éviterait d'ouvrir",
         est["ignorer"] == 1 and est["demande"] == 2 and est["ancien"] == 1 and est["a_lire"] == 3, est)

print("3. L'OCR remis à la nuit")
OCR = []


class _Page:
    def __init__(self, texte):
        self.texte = texte

    def extract_text(self):
        return self.texte


class _Pdf:
    def __init__(self, textes):
        self.pages = [_Page(t) for t in textes]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


PAGES = {b"scan": ["", ""], b"texte": ["CAHIER DES CLAUSES TECHNIQUES " * 5, "Lot 12 sols souples " * 5]}
poser("pdfplumber", open=lambda f: _Pdf(PAGES[f.getvalue()]))
parsers.ocr_disponible = lambda: True
parsers.ocr_pdf = lambda brut: OCR.append(brut) or "texte reconnu par OCR " * 10


async def _lire(brut, ocr):
    return await parsers.en_lecture(parsers.lire_pdf, brut, delai=30, ocr=ocr)

try:
    asyncio.run(_lire(b"scan", False))
    verifier("de jour, un PDF scanné lève `OcrReporte` sans OCR", False, OCR)
except parsers.OcrReporte:
    verifier("de jour, un PDF scanné lève `OcrReporte` sans OCR", not OCR)
verifier("un PDF qui a du texte se lit de jour", "CAHIER" in asyncio.run(_lire(b"texte", False)))
verifier("la nuit, le scan passe à l'OCR", "OCR" in asyncio.run(_lire(b"scan", True)) and OCR == [b"scan"])
verifier("`OcrReporte` est un FichierNonSupporte (les autres appelants ne cassent pas)",
         issubclass(parsers.OcrReporte, parsers.FichierNonSupporte))

print("4. La vraie synchronisation")
INGERES, TELECHARGES = [], []


async def _ingest_document(**k):
    INGERES.append(k["source_filename"])
    return True
sys.modules["ingestion.pipeline"].ingest_document = _ingest_document
synology = charger("ingestion.connectors.synology", "ingestion/connectors/synology.py")


async def _telecharger_ou_raison(client, base, sid, chemin):
    TELECHARGES.append(chemin)
    return (b"scan" if "scan" in chemin else b"texte"), ""
synology._telecharger_ou_raison = _telecharger_ou_raison
parsers.analyser = lambda nom, brut: {"kind": "document", "rows": [], "columns": [],
                                      "text": parsers.lire_pdf(brut)}


@asynccontextmanager
async def _connexion():
    yield None, "http://nas", "sid"
acces.connexion = _connexion


async def _dates():
    return {}
synology._dates_ingerees = _dates
tri._MEMO.update(brut="x", regles=tri.lire_regles([
    {"chemin": "/home/Drive/Photos chantier", "decision": "ignorer"},
    {"chemin": "/home/Drive/Compta", "decision": "demande"}]))
tri.regles = lambda: tri._MEMO["regles"]
tri.fenetre_de_nuit = lambda heure=None: False
res = asyncio.run(synology.sync())
lus = [pathlib.PurePosixPath(c).name for c in TELECHARGES]
verifier("« ignorer » et « à la demande » ne sont pas ouverts",
         not any("Photos" in c or "Compta" in c for c in TELECHARGES)
         and res.get("ignorés") == 1 and res.get("à_la_demande") == 2, (TELECHARGES, res))
verifier("un fichier trop ancien n'est pas ouvert", "CCTP 2019.pdf" not in lus and res.get("anciens") == 1, res)
verifier("les plus récents d'abord", lus[:1] == ["scan DPGF.pdf"], lus)
verifier("de jour, le scan est noté pour la nuit, pas passé à l'OCR",
         res.get("scans_remis_à_la_nuit") == 1 and not OCR[1:]
         and "/home/Drive/03-Appel d'offres/ETUDES EN COURS/scan DPGF.pdf" in tri.ocr_differe(), res)
verifier("le reste est lu et rangé", sorted(INGERES) == ["CCTP lot 12.pdf", "RC Pessac.pdf"], INGERES)
TELECHARGES.clear()
INGERES.clear()
asyncio.run(synology.sync())
verifier("relancée de jour, le scan en attente n'est pas retéléchargé",
         not any("scan" in c for c in TELECHARGES), TELECHARGES)
tri.fenetre_de_nuit = lambda heure=None: True
TELECHARGES.clear()
asyncio.run(synology.sync())
verifier("la nuit, le scan est lu par OCR et quitte la liste",
         any("scan" in c for c in TELECHARGES) and "scan DPGF.pdf" in INGERES and not tri.ocr_differe(),
         (TELECHARGES, INGERES, tri.ocr_differe()))

print("5. Le câblage")
main = (BACKEND / "main.py").read_text(encoding="utf-8")
verifier("les routes sont montées et la boucle de nuit démarre",
         'prefix="/api/nas-tri"' in main and "boucle_de_nuit()" in main)
routes = (BACKEND / "routers" / "nas_tri.py").read_text(encoding="utf-8")
verifier("proposer / lire / valider, réservés à l'administration système",
         '@router.post("/proposer")' in routes and '@router.put("")' in routes and "manage_system" in routes)
reglages = (BACKEND / "llm" / "reglages.py").read_text(encoding="utf-8")
verifier("les réglages du tri sont connus, l'âge est borné", '"nas_tri",' in reglages and '"nas_tri_age_ans",' in reglages
         and "entre 0 (aucune limite) et 50" in reglages)
ecran = (BACKEND.parent / "frontend" / "components" / "settings" / "TriNas.tsx").read_text(encoding="utf-8")
reg = (BACKEND.parent / "frontend" / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
verifier("l'écran propose, montre la proposition, valide, et est dans Synchronisations",
         "/api/nas-tri/proposer" in ecran and 'method: "PUT"' in ecran and "<TriNas " in reg)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
