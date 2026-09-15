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
     ouverts, les plus récents d'abord, le scan de jour est noté pour la nuit
     puis lu la nuit ;
  4 bis. (16/09, audit D-27) une copie POSSIBLE (même nom, même taille) n'est
     plus écartée : lue en dernier, reconnue à l'empreinte de son contenu, elle
     reprend les morceaux de l'original sous SA source et à SON niveau d'accès ;
     deux fichiers différents de même nom et taille sont lus tous les deux ; un
     fichier trop lent est retenté (1, 3, 7, 30 jours) et se reprend à la main ;
     un essai sur un seul dossier ne vide plus la liste de la nuit ;
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
verifier("des copies POSSIBLES (même nom, même taille) : un soupçon, désignées pour passer après la plus récente",
         tri.copies_possibles(copies) == {"/a/CCTP type.pdf", "/c/cctp TYPE.pdf"}, tri.copies_possibles(copies))
verifier("sans taille connue, deux fichiers de même nom ne sont pas des copies possibles",
         "/e/Notes.pdf" not in tri.copies_possibles(copies))
verifier("le filtre qui ÉCARTAIT les doublons sur nom + taille n'existe plus", not hasattr(tri, "doublons"))
toujours = tri.lire_regles([{"chemin": "/home/Drive/Trames", "decision": "toujours"}])
verifier("« toujours apprendre » est une décision reconnue",
         tri.decision_du_chemin("/home/Drive/Trames/devis type 2018.docx", toujours) == "toujours")
verifier("sous « toujours », l'âge ne compte plus — une photo reste une photo",
         tri.ecarte_sans_ia({"nom": "devis type 2018.docx", "modifie": MAINTENANT - 8 * AN}, MAINTENANT,
                            tri.age_applicable("toujours", 3)) is None
         and tri.ecarte_sans_ia({"nom": "IMG.jpg", "modifie": MAINTENANT}, MAINTENANT,
                                tri.age_applicable("toujours", 3)) == "photo"
         and tri.age_applicable("apprendre", 3) == 3)
verifier("l'IA ne peut pas proposer « toujours » : c'est un choix d'administrateur",
         tri.lire_decisions('{"decisions": [{"chemin": "/x", "decision": "toujours"}]}', ["/x"]) == {})

print("1 bis. Les fichiers écartés se retentent, les empreintes désignent la bonne source")
JOUR = 86400
fiche = tri.noter_ecarte(None, 500, "trop_lent", MAINTENANT)
verifier("un fichier trop lent n'attend que jusqu'à son prochain essai (1 jour), et l'essai est compté",
         tri.reste_ecarte(fiche, 500, MAINTENANT + 3600) and not tri.reste_ecarte(fiche, 500, MAINTENANT + JOUR + 1)
         and fiche["tentatives"] == 1, fiche)
delais, courante, t = [], fiche, MAINTENANT
for _ in range(4):
    delais.append(round((courante["prochain"] - t) / JOUR))
    t = courante["prochain"] + 1
    courante = tri.noter_ecarte(courante, 500, "trop_lent", t)
verifier("les essais s'espacent : 1, 3, 7 puis 30 jours", delais == [1, 3, 7, 30] and courante["tentatives"] == 5,
         (delais, courante))
stable = tri.noter_ecarte(None, 500, "sans_texte", MAINTENANT)
verifier("« sans texte » est un motif STABLE : écarté tant que le fichier ne change pas",
         tri.reste_ecarte(stable, 500, MAINTENANT + 400 * JOUR))
verifier("un fichier modifié est relu, quel que soit le motif", not tri.reste_ecarte(stable, 501, MAINTENANT))
verifier("l'ancien format (la date seule, motif inconnu) est retenté",
         not tri.reste_ecarte(500, 500, MAINTENANT) and tri.fiche_ecartee(500)["raison"] == "inconnue")
ecartes_essai = {"/a": tri.noter_ecarte(None, 1, "trop_lent", MAINTENANT),
                 "/b": tri.noter_ecarte(None, 1, "sans_texte", MAINTENANT)}
verifier("sans reprise demandée, rien n'est repris", tri.appliquer_reprise(ecartes_essai) == 0)
tri.demander_reprise(tout=False)
repris = tri.appliquer_reprise(ecartes_essai)
verifier("une reprise demandée rend les trop lents lisibles tout de suite, pas les « sans texte », et s'efface",
         repris == 1 and not tri.reste_ecarte(ecartes_essai["/a"], 1, MAINTENANT)
         and tri.reste_ecarte(ecartes_essai["/b"], 1, MAINTENANT) and tri.reprise_en_attente() is None, ecartes_essai)
tri.demander_reprise(tout=True)
verifier("« tout reprendre » rouvre aussi les « sans texte »",
         tri.appliquer_reprise(ecartes_essai) == 2 and "/b" not in ecartes_essai)
resume = tri.resume_ecartes({"/a": tri.noter_ecarte(None, 1, "trop_lent", MAINTENANT), "/b": stable}, MAINTENANT)
verifier("l'écran reçoit le compte, le motif et le prochain essai",
         resume["total"] == 2 and resume["sans_texte"] == 1 and resume["a_retenter"] == 1
         and resume["prochain"] and resume["exemples"][0]["raison"] == "trop_lent", resume)
emp, idx = {}, {}
tri.noter_empreinte(emp, idx, "synology:/a/CCTP.pdf", "e1", "ingere")
tri.noter_empreinte(emp, idx, "synology:/b/CCTP.pdf", "e1", "ingere")
verifier("une empreinte désigne la PREMIÈRE source lue", idx["e1"][0] == "synology:/a/CCTP.pdf")
tri.noter_empreinte(emp, idx, "synology:/a/CCTP.pdf", "e2", "ingere")
verifier("une source relue avec un autre contenu ne désigne plus l'ancien : la copie identique prend sa place",
         idx["e1"][0] == "synology:/b/CCTP.pdf" and idx["e2"][0] == "synology:/a/CCTP.pdf", idx)
tri.noter_empreinte(emp, idx, "synology:/c/scan.pdf", "e3", "sans_texte")
tri.noter_empreinte(emp, idx, "synology:/d/scan.pdf", "e3", "ingere")
verifier("une source LUE l'emporte sur une « sans texte » de même contenu", idx["e3"] == ("synology:/d/scan.pdf", "ingere"))
verifier("l'index se reconstruit à l'identique depuis le fichier", tri.index_des_empreintes(emp) == idx)
tri.ecrire_json("essai.json", {"a": 1})
verifier("écriture ATOMIQUE : le contenu est relu, aucun temporaire ne traîne",
         tri.lire_json("essai.json", None) == {"a": 1} and not list(pathlib.Path(os.environ["DOCUMENTS_DIR"]).glob("*.tmp")))
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
# « texte|<ce qui distingue le fichier> » : un contenu PAR fichier (audit D-27,
# une copie se reconnaît désormais à son empreinte).
poser("pdfplumber", open=lambda f: _Pdf(PAGES[f.getvalue().split(b"|")[0]]))
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
INGERES, TELECHARGES, SOURCES_LUES, COPIES = [], [], [], []
CONTENUS = {}


async def _ingest_document(**k):
    INGERES.append(k["source_filename"])
    SOURCES_LUES.append(k["source_id"])
    return 3


async def _copier_document(origine, source_type, source_id, source_filename=None, access_level="all"):
    COPIES.append({"origine": origine, "source_id": source_id, "nom": source_filename, "niveau": access_level})
    return 3 if COPIE_POSSIBLE[0] else 0
COPIE_POSSIBLE = [True]
sys.modules["ingestion.pipeline"].ingest_document = _ingest_document
sys.modules["ingestion.pipeline"].copier_document = _copier_document
synology = charger("ingestion.connectors.synology", "ingestion/connectors/synology.py")


async def _telecharger_ou_raison(client, base, sid, chemin):
    TELECHARGES.append(chemin)
    if "scan" in chemin:
        return b"scan", ""
    return b"texte|" + CONTENUS.get(chemin, chemin).encode("utf-8"), ""
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

print("4 bis. Copies, fichiers trop lents, reprise (audit D-27)")
EC = "/home/Drive/03-Appel d'offres/ETUDES EN COURS"
for affaire, age in (("Affaire A", 0.1), ("Affaire B", 0.3), ("Affaire C", 0.4)):
    CATALOGUE.append({"chemin": f"{EC}/{affaire}/CCTP type.pdf", "nom": "CCTP type.pdf", "dossier": False,
                      "octets": 5000, "modifie": MAINTENANT - age * AN})
CONTENUS[f"{EC}/Affaire A/CCTP type.pdf"] = "le CCTP commun"
CONTENUS[f"{EC}/Affaire B/CCTP type.pdf"] = "le CCTP commun"         # vraie copie de A
CONTENUS[f"{EC}/Affaire C/CCTP type.pdf"] = "un AUTRE CCTP"           # même nom, même taille, autre contenu
vrai_niveau = synology._niveau_nas
synology._niveau_nas = lambda chemin: "direction_only" if "Affaire B" in chemin else "all"
tri.fenetre_de_nuit = lambda heure=None: False
for liste in (TELECHARGES, INGERES, SOURCES_LUES, COPIES):
    liste.clear()
res = asyncio.run(synology.sync())
source_a = synology._source_id(f"{EC}/Affaire A/CCTP type.pdf")
source_b = synology._source_id(f"{EC}/Affaire B/CCTP type.pdf")
source_c = synology._source_id(f"{EC}/Affaire C/CCTP type.pdf")
copies_lues = [i for i, c in enumerate(TELECHARGES) if "Affaire B" in c or "Affaire C" in c]
autres = [i for i, c in enumerate(TELECHARGES) if not ("Affaire B" in c or "Affaire C" in c)]
verifier("les copies possibles ne sont plus écartées : lues, et APRÈS tous les autres fichiers",
         len(copies_lues) == 2 and autres and max(autres) < min(copies_lues) and res.get("copies_possibles") == 2,
         (TELECHARGES, res))
verifier("une vraie copie (même contenu) reprend les morceaux de l'original, sans relecture",
         [c["origine"] for c in COPIES] == [source_a] and source_b not in SOURCES_LUES
         and res.get("copies_reconnues") == 1, (COPIES, SOURCES_LUES, res))
verifier("la copie garde SA source, SON nom et SON niveau d'accès (les droits de deux affaires ne fusionnent pas)",
         COPIES and COPIES[0]["source_id"] == source_b and COPIES[0]["niveau"] == "direction_only"
         and COPIES[0]["nom"] == "CCTP type.pdf", COPIES)
verifier("deux fichiers DIFFÉRENTS de même nom et même taille sont lus tous les deux",
         source_a in SOURCES_LUES and source_c in SOURCES_LUES, SOURCES_LUES)
empreintes = tri.lire_empreintes()
verifier("les empreintes sont retenues sur le disque (une relance reconnaît la copie)",
         empreintes.get(source_a) and empreintes.get(source_a) == empreintes.get(source_b)
         and empreintes.get(source_c) != empreintes.get(source_a), empreintes)
COPIE_POSSIBLE[0] = False
for liste in (TELECHARGES, INGERES, SOURCES_LUES, COPIES):
    liste.clear()
asyncio.run(synology.sync())
verifier("l'original n'a plus ses morceaux : la copie est RELUE, jamais perdue",
         COPIES and source_b in SOURCES_LUES, (COPIES, SOURCES_LUES))
COPIE_POSSIBLE[0] = True
synology._niveau_nas = vrai_niveau

LENT = f"{EC}/CCTP très lent.pdf"
CATALOGUE.append({"chemin": LENT, "nom": "CCTP très lent.pdf", "dossier": False, "octets": 9000,
                  "modifie": MAINTENANT - 0.2 * AN})
vraie_lecture = parsers.en_lecture


async def _lecture_lente(fonction, nom, brut, delai=None, ocr=False):
    if nom == "CCTP très lent.pdf":
        raise TimeoutError("trop long")
    return await vraie_lecture(fonction, nom, brut, delai=delai, ocr=ocr)
parsers.en_lecture = _lecture_lente
tri.fenetre_de_nuit = lambda heure=None: True
TELECHARGES.clear()
res = asyncio.run(synology.sync())
fiche_lente = synology._lire_ecartes().get(LENT)
verifier("la nuit, un fichier trop lent est écarté avec son motif et son essai compté",
         res.get("trop_lents") == 1 and isinstance(fiche_lente, dict) and fiche_lente.get("raison") == "trop_lent"
         and fiche_lente.get("tentatives") == 1, (res, fiche_lente))
TELECHARGES.clear()
res = asyncio.run(synology.sync())
verifier("relancée aussitôt, il attend son prochain essai (pas retéléchargé)",
         LENT not in TELECHARGES and res.get("déjà_écartés", 0) >= 1, res)
import time as _temps
vraie_heure = _temps.time
_temps.time = lambda: vraie_heure() + 2 * 86400
try:
    TELECHARGES.clear()
    res = asyncio.run(synology.sync())
finally:
    _temps.time = vraie_heure
verifier("deux jours plus tard, il est RETENTÉ (un délai ponctuel n'écarte plus pour toujours)",
         LENT in TELECHARGES and res.get("retentés") == 1
         and synology._lire_ecartes().get(LENT, {}).get("tentatives") == 2, res)
tri.demander_reprise()
TELECHARGES.clear()
res = asyncio.run(synology.sync())
verifier("« Réessayer maintenant » à l'écran : repris dès la synchronisation suivante",
         LENT in TELECHARGES and res.get("repris_à_la_main", 0) >= 1, res)
parsers.en_lecture = vraie_lecture

tri.fenetre_de_nuit = lambda heure=None: False
SCAN = f"{EC}/scan DPGF.pdf"
tri.ecrire_ocr_differe({SCAN: next(e["modifie"] for e in CATALOGUE if e["chemin"] == SCAN)})
asyncio.run(synology.sync(dossiers=["/home/Drive/Compta"]))
verifier("un essai sur UN dossier ne vide plus la liste de la nuit (aucune disparition prouvée)",
         SCAN in tri.ocr_differe(), tri.ocr_differe())


async def _catalogue_partiel(**k):
    return [e for e in CATALOGUE if "ETUDES EN COURS" not in e["chemin"]], False
acces.catalogue_attendu = _catalogue_partiel
asyncio.run(synology.sync())
verifier("un relevé PARTIEL du NAS ne fait rien disparaître non plus",
         SCAN in tri.ocr_differe() and LENT in synology._lire_ecartes() and source_a in tri.lire_empreintes(),
         tri.ocr_differe())
acces.catalogue_attendu = _catalogue_attendu
FANTOME = "/home/Drive/03-Appel d'offres/disparu du NAS.pdf"
tri.ecrire_ocr_differe({**tri.ocr_differe(), FANTOME: 1})
synology._ecrire_ecartes({**synology._lire_ecartes(), FANTOME: tri.noter_ecarte(None, 1, "trop_lent", MAINTENANT)})
tri.ecrire_empreintes({**tri.lire_empreintes(), synology._source_id(FANTOME): ["e-fantome", "ingere"]})
asyncio.run(synology.sync())
verifier("sur un relevé COMPLET, un fichier disparu quitte les trois listes ; le scan présent y reste",
         FANTOME not in tri.ocr_differe() and FANTOME not in synology._lire_ecartes()
         and synology._source_id(FANTOME) not in tri.lire_empreintes() and SCAN in tri.ocr_differe(),
         (tri.ocr_differe(), list(synology._lire_ecartes())))
src_sync = (BACKEND / "ingestion" / "connectors" / "synology.py").read_text(encoding="utf-8")
verifier("les mémoires du NAS vivent au même endroit et s'écrivent atomiquement",
         "os.replace(temporaire, f)" in (BACKEND / "nas" / "tri.py").read_text(encoding="utf-8")
         and "return tri.lire_ecartes()" in src_sync)

print("5. Le câblage")
main = (BACKEND / "main.py").read_text(encoding="utf-8")
verifier("les routes sont montées et la boucle de nuit démarre",
         'prefix="/api/nas-tri"' in main and "boucle_de_nuit()" in main)
routes = (BACKEND / "routers" / "nas_tri.py").read_text(encoding="utf-8")
verifier("proposer / lire / valider, réservés à l'administration système",
         '@router.post("/proposer")' in routes and '@router.put("")' in routes and "manage_system" in routes)
verifier("la reprise des fichiers écartés a sa route, et l'état des écartés est rendu à l'écran",
         '@router.post("/reprendre")' in routes and "tri.demander_reprise(" in routes
         and '"ecartes": tri.resume_ecartes(' in routes)
reglages = (BACKEND / "llm" / "reglages.py").read_text(encoding="utf-8")
verifier("les réglages du tri sont connus, l'âge est borné", '"nas_tri",' in reglages and '"nas_tri_age_ans",' in reglages
         and "entre 0 (aucune limite) et 50" in reglages)
ecran = (BACKEND.parent / "frontend" / "components" / "settings" / "TriNas.tsx").read_text(encoding="utf-8")
reg = (BACKEND.parent / "frontend" / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
verifier("l'écran propose, montre la proposition, valide, et est dans Synchronisations",
         "/api/nas-tri/proposer" in ecran and 'method: "PUT"' in ecran and "<TriNas " in reg)
verifier("l'écran offre « Toujours apprendre », dit les copies possibles et permet de réessayer les écartés",
         'toujours: "Toujours apprendre"' in ecran and "copies possibles, lues en dernier" in ecran
         and "/api/nas-tri/reprendre" in ecran and 'data-testid="tri-ecartes"' in ecran)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
