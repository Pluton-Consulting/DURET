"""
LE CONTENEUR NAVIGATEUR LIT CE QU'UN MÉTREUR CHERCHE (18/09, banc Duret).

Essai réel depuis le serveur : « Gerflor Taralay Impression Acoustic 43 fiche technique »
rendait trois résultats dont deux VIDES — la fiche technique PDF (`--dump-dom` n'en rend
que la visionneuse) et une page produit lue à deux de front (seule, elle rendait 6 000
caractères en 4 s). Et la navigation autonome était réglée sur un fournisseur à clé
refusée que la sonde déclarait vivant (sa liste de modèles répond même en 401).

Ce banc charge `browser-worker/rapide.py` et `llm_factory.py` tels quels, réseau doublé :
  * une adresse .pdf passe par la lecture PDF, pas par Chromium ;
  * une page vide après la lecture de front est relue une fois, seule ;
  * la sonde d'un fournisseur fait un VRAI appel (chat/completions), pas un GET /models ;
  * le texte d'un vrai PDF est extrait (si pypdf est installé ici — il l'est dans l'image).
"""
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path

RACINE = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve().parent
TRAVAILLEUR = RACINE / "browser-worker"
echecs = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + ("" if cond else f"  → {detail}"))
    if not cond:
        echecs.append(nom)


def charger(nom):
    spec = importlib.util.spec_from_file_location(nom + "_banc", TRAVAILLEUR / f"{nom}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print("═══ CONTENEUR NAVIGATEUR — " + str(TRAVAILLEUR))
rapide = charger("rapide")

verifier("une adresse de fiche technique .pdf est reconnue (query et majuscules comprises)",
         rapide._est_pdf("https://cdn.gerflor.com/media/2/41285/fiche%20technique.PDF?v=2")
         and not rapide._est_pdf("https://www.gerflor.fr/produits/taralay"))

appels = {"dump": [], "pdf": []}


async def faux_dump(url, delai_ms):
    appels["dump"].append(url)
    if "vide" in url and appels["dump"].count(url) == 1:
        return "<html><body></body></html>"           # vide à la lecture de front
    if "duckduckgo" in url:
        return ('<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fex.fr%2Fvide">a</a>'
                '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fex.fr%2Fplein">b</a>'
                '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fcdn.ex.fr%2Ffiche.pdf">c</a>')
    return f"<html><title>{url}</title><body>Texte utile de {url}</body></html>"


async def faux_pdf(url, delai_ms):
    appels["pdf"].append(url)
    return {"url": url, "titre": "fiche.pdf", "contenu": "Epaisseur totale 2.70 mm", "format": "pdf"}


rapide._dump = faux_dump
rapide._lire_pdf = faux_pdf
res = asyncio.run(rapide.chercher("fiche technique", 3, 15000))
urls = {r["url"]: r for r in res["results"]}
verifier("le PDF est lu par la lecture PDF, jamais par Chromium",
         appels["pdf"] == ["https://cdn.ex.fr/fiche.pdf"] and "https://cdn.ex.fr/fiche.pdf" not in appels["dump"],
         appels)
verifier("…et son texte revient", urls.get("https://cdn.ex.fr/fiche.pdf", {}).get("contenu") == "Epaisseur totale 2.70 mm")
verifier("une page vide à la lecture de front est relue une fois, seule, et revient pleine",
         appels["dump"].count("https://ex.fr/vide") == 2 and (urls.get("https://ex.fr/vide") or {}).get("contenu"),
         appels["dump"])
verifier("une page pleine n'est lue qu'une fois", appels["dump"].count("https://ex.fr/plein") == 1, appels["dump"])

# Le texte d'un VRAI PDF (fabriqué ici), si pypdf est installé sur ce poste.
try:
    import pypdf  # noqa: F401
    import fitz
    d = fitz.open(); pg = d.new_page(); pg.insert_text((50, 60), "Epaisseur totale 2.70 mm - Classement U4P3E2/3C2", fontsize=11)
    titre, texte = rapide._texte_pdf(d.tobytes())
    verifier("un vrai PDF : son texte est extrait", "2.70" in texte and "U4P3" in texte, texte[:120])
except ImportError:
    print("  (SKIP partiel : pypdf absent de ce poste — présent dans l'image du conteneur)")

# ── La sonde des fournisseurs : un vrai appel ──
os.environ["LONGCAT_API_KEY"] = "fausse"
sys.modules.setdefault("wconfig", types.SimpleNamespace(LLM_PROVIDER="longcat", LLM_MODEL="LongCat-2.0"))
fabrique = charger("llm_factory")
vus = []


class _Rep:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def faux_urlopen(req, timeout=0):
    vus.append((req.full_url, req.get_method(), bool(req.data)))
    if "longcat" in req.full_url:
        raise OSError("HTTP Error 401: Unauthorized")
    return _Rep()


fabrique.urllib.request.urlopen = faux_urlopen
verifier("la sonde fait un VRAI appel (POST chat/completions), pas un GET /models",
         fabrique._vivant("longcat", "LongCat-2.0") is False
         and vus and vus[-1][0].endswith("/v1/chat/completions") and vus[-1][1] == "POST" and vus[-1][2], vus)

# ── « Ce qu'on y a lu » : le passage qui répond, pas le décor de la page (19/09) ──
import ast
src_outils = (RACINE / "backend" / "browser" / "tools.py").read_text(encoding="utf-8")
arbre = ast.parse(src_outils)
code = "\n\n".join(ast.get_source_segment(src_outils, n) for n in arbre.body
                    if isinstance(n, ast.FunctionDef) and n.name in ("_plat_web", "_extrait"))
espace = {}
exec("import re\n" + code, espace)
page = ("DTU 53.2 : Guide essentiel | Mon site --> --> Aller au contenu Accueil Blog Contact. "
        "Le support doit présenter un taux d'humidité inférieur à 3 % mesuré à la bombe au carbure. "
        "Nos autres articles sur la décoration.")
ext = espace["_extrait"](page, requete="DTU 53.2 taux humidité support", titre="DTU 53.2 : Guide essentiel | Mon site")
verifier("l'extrait est le passage qui porte les mots de la recherche", "humidité inférieur à 3 %" in ext and "Aller au contenu" not in ext, ext)
sans = espace["_extrait"]("DTU 53.2 : Guide | Mon site Aller au contenu Texte de la page ici, assez long pour un extrait.",
                          titre="DTU 53.2 : Guide | Mon site")
verifier("sans recherche : le début de la page, titre et « Aller au contenu » retirés", sans.startswith("Texte de la page"), sans)

print("\n" + ("✓ 0 échec" if not echecs else f"✗ {len(echecs)} échec(s)"))
sys.exit(1 if echecs else 0)
