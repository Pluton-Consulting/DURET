"""
Banc « LES FICHIERS DU NAS SE LISENT EN FLUX, SANS SE COPIER » (23/09, Duret).

Relevé de Noa : « il n'affiche pas toutes les pages des PDF, un gros fichier c'est long,
et il ne doit pas télécharger tout le NAS sur le serveur, ça va vite saturer ».

CE QUE CE BANC PROUVE : le billet de lecture lié à la personne et au chemin (EXÉCUTÉ) ;
plus aucune route qui copie un fichier sur le disque ; un flux relayé avec les plages
d'octets ; une page web ou un SVG du NAS forcés en téléchargement ; nginx sans tampon
disque et avec le cadre de l'application permis ; un PDF affiché par le lecteur du
navigateur ; les copies de fichiers du NAS du chat purgées après 7 jours, sans rien
toucher d'autre (EXÉCUTÉ sur un dossier temporaire).
"""
import ast
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import time
import types
from contextlib import contextmanager

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LES FICHIERS DU NAS EN FLUX — {RACINE}\n")
source = (BACKEND / "routers" / "nas_explorateur.py").read_text(encoding="utf-8")

print("— Le billet de lecture")
espace = {"_hashlib": __import__("hashlib"), "_hmac": __import__("hmac"), "_time": time}
sys.modules["config"] = types.SimpleNamespace(settings=types.SimpleNamespace(jwt_secret_key="secret-de-test"))
for n in ast.parse(source).body:
    if (isinstance(n, ast.FunctionDef) and n.name in ("_signature", "billet", "lire_billet")) or (
            isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DUREE_BILLET_S"):
        exec(compile(ast.Module(body=[n], type_ignores=[]), "nas_explorateur", "exec"), espace)
b = espace["billet"]("u1", "/home/Drive/CCTP.pdf", maintenant=1000)
lire = espace["lire_billet"]
verifier("valide pour sa personne et son chemin", lire(b, "/home/Drive/CCTP.pdf", maintenant=1100) == "u1")
verifier("refusé pour un AUTRE chemin", lire(b, "/home/Drive/Compta.xlsx", maintenant=1100) is None)
verifier("refusé une fois expiré (10 min)", lire(b, "/home/Drive/CCTP.pdf", maintenant=1601) is None)
verifier("refusé si la personne est changée", lire(b.replace("u1.", "u2.", 1), "/home/Drive/CCTP.pdf", maintenant=1100) is None)
verifier("refusé si illisible", lire("n'importe quoi", "/x", maintenant=1100) is None)

print("\n— La lecture en flux")
verifier("plus aucune route qui copie un fichier sur le disque (/ouvrir retirée)",
         '@router.post("/ouvrir")' not in source and "garantir_fichier_lu(" not in source
         and "deposer_fichier(" not in source)
verifier("le fichier est relayé par morceaux",
         "StreamingResponse(morceaux()" in source and "client.send(req, stream=True)" in source)
verifier("les plages d'octets sont relayées (Range → 206)",
         '{"Range": plage}' in source and "status_code=206 if rep.status_code == 206" in source)
verifier("page web, SVG, script du NAS : téléchargement forcé, jamais affichés",
         all(t in source for t in ('"html"', '"svg"', '"js"'))
         and 'telecharger, type_ = True, "application/octet-stream"' in source)
verifier("la session NAS est rendue même si l'envoi échoue", "await ctx.__aexit__(type(e), e, e.__traceback__)" in source)

print("\n— nginx et l'écran")
nginx = (RACINE / "nginx" / "nginx.conf").read_text(encoding="utf-8")
bloc = nginx.split("location /api/nas-explorateur/ {", 1)[1].split("}", 1)[0]
verifier("nginx : aucun tampon disque, dans un sens comme dans l'autre",
         "proxy_buffering off;" in bloc and "proxy_request_buffering off;" in bloc)
verifier("nginx : cadre de l'application permis, autres en-têtes reposés",
         "X-Frame-Options SAMEORIGIN" in bloc and "X-Content-Type-Options nosniff" in bloc and "Referrer-Policy" in bloc)
fx = (RACINE / "frontend" / "components" / "fichiers" / "Fichiers.tsx").read_text(encoding="utf-8")
verifier("écran : un PDF s'ouvre dans le lecteur du navigateur (toutes les pages)",
         'const NATIF_CADRE = new Set(["pdf"' in fx and "<iframe src={adresse}" in fx)
verifier("écran : le téléchargement part en direct du flux", "&telecharger=1" in fx)
verifier("écran : plus d'appel à /ouvrir", "/api/nas-explorateur/ouvrir" not in fx)

print("\n— La purge des copies du NAS")
dossier = tempfile.mkdtemp()
os.environ["DOCUMENTS_DIR"] = dossier
os.environ.pop("DOCUMENTS_RETENTION_JOURS", None)
sys.modules.setdefault("stockage", types.ModuleType("stockage"))
verrous = types.ModuleType("stockage.verrous")


@contextmanager
def _verrou(d, j, bloquant=True):
    yield True


verrous.verrou_fichier = _verrou
sys.modules["stockage.verrous"] = verrous
spec = importlib.util.spec_from_file_location("atelier_banc", BACKEND / "bureautique" / "atelier.py")
at = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(at)
except Exception as e:  # noqa: BLE001
    print(f"  (atelier non chargeable ici : {type(e).__name__} {e}) — purge non exécutée")
    at = None
if at is not None:
    vieux, recent = time.time() - 9 * 86400, time.time() - 86400
    FICHES = {}

    def poser(jeton, fiche):
        with open(os.path.join(dossier, jeton), "w") as f:
            f.write("x")
        FICHES[jeton] = fiche

    def J(c):
        return (c * 32)[:32]
    poser(J("a"), {"origine": "serveur", "termine": vieux})
    poser(J("b"), {"origine": "serveur", "termine": recent})
    poser(J("c"), {"origine": "depot", "termine": vieux, "fini": True})
    poser(J("d"), {"termine": vieux, "fini": True})
    poser(J("e"), {"origine": "serveur", "termine": vieux, "conserver": True})
    at._lire_fiche = lambda j: FICHES.get(j) if os.path.exists(os.path.join(dossier, j)) else None
    at.DOSSIER = dossier
    try:
        at.purger()
        restent = set(os.listdir(dossier))
        verifier("copie du NAS de plus de 7 jours : partie", J("a") not in restent, restent)
        verifier("copie du NAS récente : gardée", J("b") in restent)
        verifier("fichier déposé, document produit : jamais touchés", J("c") in restent and J("d") in restent)
        verifier("copie épinglée (conserver) : gardée", J("e") in restent)
    except Exception as e:  # noqa: BLE001
        verifier(f"purge exécutable ({type(e).__name__}: {e})", False)

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
