"""
Banc de l'OCR BORNÉ — une lecture de masse ne prend plus tout le serveur (15/09).

Relevé en prod chez Duret : pendant « Enrichir les documents », l'application
« se déconnecte puis revient ». Sur le serveur, dix tesseract en même temps
(certains depuis 39 minutes), charge 38 pour 6 cœurs. La synchronisation
attendait chaque lecture par `wait_for(to_thread(analyser…), 180 s)` : passé le
délai elle abandonnait l'ATTENTE, pas l'OCR — un thread ne se tue pas. Les
lectures fantômes ont rempli la réserve de threads par défaut (10 places), dont
dépend tout le backend.

CE QUE CE BANC PROUVE (pytesseract et pypdfium2 doublés, sans réseau) :
  · jamais plus de OCR_SIMULTANES tesseract, même avec huit lectures de front ;
  · une lecture qui dépasse son échéance S'ARRÊTE entre deux pages (plus aucun
    OCR ne tourne quand `en_lecture` rend la main) et lève `DelaiDepasse` ;
  · tesseract reçoit un délai par page ; une page trop longue rend vide sans
    arrêter la suivante ;
  · les lectures tournent dans la réserve « lecture », pas dans celle du reste
    de l'application : un `to_thread` ordinaire passe pendant qu'elles tournent ;
  · les synchronisations passent par `en_lecture`, plus par `wait_for(to_thread…)` ;
  · pdfium n'est JAMAIS appelé par deux threads à la fois (22/09 : sept plantages
    natifs du backend en une nuit d'ingestion), l'OCR restant parallèle.
Tombe sur la version d'avant (`en_lecture` absent ; puis, pour le 6, sans `_PDFIUM`).

Usage : python backend/scripts/test_ocr_borne.py [backend]
"""
import asyncio
import pathlib
import sys
import threading
import time
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


class Tesseract:
    """Un tesseract doublé : compte les passages simultanés et ceux qui restent."""
    verrou = threading.Lock()
    en_cours = 0
    maximum = 0
    passages = 0
    duree = 0.2
    delais = []
    fils = set()

    @classmethod
    def image_to_string(cls, image, lang=None, timeout=0):
        with cls.verrou:
            cls.en_cours += 1
            cls.maximum = max(cls.maximum, cls.en_cours)
            cls.passages += 1
            cls.delais.append(timeout)
            cls.fils.add(threading.current_thread().name)
        try:
            if timeout and cls.duree > timeout:
                time.sleep(timeout)
                raise RuntimeError("Tesseract process timeout")
            time.sleep(cls.duree)
            return "texte de la page"
        finally:
            with cls.verrou:
                cls.en_cours -= 1

    @staticmethod
    def get_tesseract_version():
        return "5.3"


class _Image:
    def close(self):
        pass

    def copy(self):
        return _Image()


class Pdfium:
    """Compte les appels à pdfium qui se CHEVAUCHENT : la vraie bibliothèque plante
    le processus (« trap int3 in libpdfium.so ») dès qu'il y en a deux."""
    verrou = threading.Lock()
    en_cours = 0
    maximum = 0

    @classmethod
    def appel(cls, duree=0.0):
        with cls.verrou:
            cls.en_cours += 1
            cls.maximum = max(cls.maximum, cls.en_cours)
        try:
            time.sleep(duree)
        finally:
            with cls.verrou:
                cls.en_cours -= 1


class _Bitmap:
    def to_pil(self):
        Pdfium.appel()
        return _Image()

    def close(self):
        Pdfium.appel()


class _Page:
    def render(self, scale=1):
        Pdfium.appel(0.02)
        return _Bitmap()

    def close(self):
        Pdfium.appel()


class _Pdf:
    pages = 10

    def __init__(self, brut):
        Pdfium.appel(0.01)

    def __len__(self):
        return _Pdf.pages

    def __getitem__(self, i):
        Pdfium.appel()
        return _Page()

    def close(self):
        Pdfium.appel()


sys.modules["pytesseract"] = Tesseract
sys.modules["pypdfium2"] = types.SimpleNamespace(PdfDocument=_Pdf)

try:
    # Chargé par son fichier : le paquet `ingestion` importe la base (asyncpg).
    import importlib.util
    _spec = importlib.util.spec_from_file_location("parsers_banc", racine / "ingestion" / "parsers.py")
    P = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(P)
except Exception as e:  # noqa: BLE001
    P = None
    verifier("ingestion/parsers.py s'importe", False, e)

if P is not None and not hasattr(P, "en_lecture"):
    verifier("parsers porte `en_lecture` et `DelaiDepasse`", False, "absents")
    P = None

if P is not None:
    print("1. Jamais plus de OCR_SIMULTANES tesseract")
    _Pdf.pages = 3
    Tesseract.duree = 0.15

    async def huit():
        return await asyncio.gather(*[P.en_lecture(P.ocr_pdf, b"%PDF", delai=30) for _ in range(8)])

    textes = asyncio.run(huit())
    verifier("les huit lectures rendent leur texte", all("texte de la page" in t for t in textes), textes[:1])
    verifier(f"au plus {P.OCR_SIMULTANES} tesseract en même temps (vu : {Tesseract.maximum})",
             1 <= Tesseract.maximum <= P.OCR_SIMULTANES)
    verifier("tesseract reçoit un délai par page", Tesseract.delais and all(d and d <= P.OCR_DELAI_PAGE_S for d in Tesseract.delais),
             Tesseract.delais[:5])
    verifier("les lectures tournent dans la réserve « lecture »",
             Tesseract.fils and all(n.startswith("lecture") for n in Tesseract.fils), Tesseract.fils)

    print("2. Une lecture hors délai s'arrête vraiment")
    _Pdf.pages = 40
    Tesseract.duree = 0.25
    Tesseract.passages = 0

    async def trop_long():
        debut = time.monotonic()
        try:
            await P.en_lecture(P.ocr_pdf, b"%PDF", delai=0.8)
            return "rendu", time.monotonic() - debut
        except P.DelaiDepasse:
            return "delai", time.monotonic() - debut

    issue, duree = asyncio.run(trop_long())
    verifier("`DelaiDepasse` est levé", issue == "delai", issue)
    verifier("la lecture s'est arrêtée bien avant ses 40 pages", Tesseract.passages < 10, Tesseract.passages)
    verifier("plus aucun OCR ne tourne quand la main revient", Tesseract.en_cours == 0, Tesseract.en_cours)
    verifier("elle rend la main peu après l'échéance", duree < 0.8 + 1.5, round(duree, 2))
    verifier("`DelaiDepasse` est un TimeoutError (les synchros le comptent « trop lent »)",
             issubclass(P.DelaiDepasse, TimeoutError))

    print("3. Une page trop longue rend vide, la suivante passe")
    _Pdf.pages = 2
    Tesseract.duree = 0.3
    ancien = P.OCR_DELAI_PAGE_S
    P.OCR_DELAI_PAGE_S = 0.1
    try:
        texte = P.ocr_pdf(b"%PDF")
        verifier("aucune exception, texte vide", texte == "", texte)
    except Exception as e:  # noqa: BLE001
        verifier("aucune exception, texte vide", False, e)
    finally:
        P.OCR_DELAI_PAGE_S = ancien

    print("4. Le reste de l'application n'attend pas derrière les lectures")
    _Pdf.pages = 6
    Tesseract.duree = 0.2

    async def a_cote():
        lectures = [asyncio.ensure_future(P.en_lecture(P.ocr_pdf, b"%PDF", delai=30)) for _ in range(12)]
        await asyncio.sleep(0.1)
        debut = time.monotonic()
        await asyncio.to_thread(lambda: None)
        attente = time.monotonic() - debut
        await asyncio.gather(*lectures)
        return attente

    attente = asyncio.run(a_cote())
    verifier("un `to_thread` ordinaire passe pendant douze lectures", attente < 0.5, round(attente, 2))

    print("6. pdfium n'est jamais appelé par deux threads à la fois (22/09)")
    _Pdf.pages = 5
    Tesseract.duree = 0.05
    Pdfium.maximum = 0

    async def seize():
        return await asyncio.gather(*[P.en_lecture(P.ocr_pdf, b"%PDF", delai=30) for _ in range(8)],
                                    *[asyncio.to_thread(P.ocr_pdf, b"%PDF") for _ in range(8)])

    textes = asyncio.run(seize())
    verifier("seize lectures de front (masse + chat) rendent leur texte",
             all("texte de la page" in t for t in textes), textes[:1])
    verifier(f"au plus UN appel à pdfium à la fois (vu : {Pdfium.maximum})", Pdfium.maximum == 1)
    verifier("l'OCR, lui, reste parallèle", Tesseract.maximum >= 2, Tesseract.maximum)

print("5. Les synchronisations passent par `en_lecture`")
for chemin in ("ingestion/connectors/synology.py", "ingestion/connectors/google_drive.py"):
    f = racine / chemin
    if not f.exists():
        continue
    src = f.read_text(encoding="utf-8")
    if "DELAI_LECTURE_S" not in src and "DELAI_PAR_DOCUMENT_S" not in src:
        continue          # connecteur sans lecture bornée (ancien, inactif)
    verifier(f"{chemin} : `en_lecture`, plus de wait_for(to_thread(…))",
             "en_lecture(" in src and "wait_for(\n" not in src.replace(" ", "")
             and "to_thread(analyser" not in src and "to_thread(_download_text" not in src)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
