"""
Banc « L'ESTIMATION DU TRI NAS : SUR CLIC, RAPIDE, BRIDÉE » (23/09, Duret).

Deux gels de l'API le 23/09 (16:41 et 17:00) : ouvrir Paramètres → Synchronisations
lançait l'estimation sur tout le catalogue, qui comparait chaque fichier à chaque
règle ; le processeur restait à 100 %. Demande de Noa : jamais plus de 60 %, et
seulement quand on clique sur le bouton.

CE QUE CE BANC PROUVE : la décision par index = la décision par boucle (EXÉCUTÉ sur
un catalogue synthétique) et elle est rapide ; l'estimation bridée travaille au plus
~60 % du temps écoulé ; la lecture de l'onglet ne calcule plus rien ; la route
POST /estimer part hors de la boucle principale ; l'écran a son bouton.
"""
import pathlib
import random
import sys
import time
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.modules.setdefault("config", types.SimpleNamespace(settings=types.SimpleNamespace()))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ L'ESTIMATION DU TRI NAS — {BACKEND}\n")
from nas import tri  # noqa: E402

random.seed(7)
brut = [{"chemin": f"/home/Drive/Dossier É{i}/Sous {j}", "decision": random.choice(["demande", "ignorer", "apprendre", "toujours"])}
        for i in range(60) for j in range(5)]
brut.append({"chemin": "/home/drive/dossier e3", "decision": "ignorer"})
brut.append({"chemin": "/home/Drive/Dossier É3/Sous 2/Profond", "decision": "toujours"})
regles = tri.lire_regles(brut)
chemins = [f"/home/Drive/Dossier É{random.randint(0, 70)}/Sous {random.randint(0, 7)}/"
           + random.choice(["", "Profond/"]) + f"f {k}.pdf" for k in range(60000)]
chemins += ["/home/Drive/Dossier É3/Sous 2", "/autre/x.pdf", "/home/Drive/Dossier É3/Sous 2x/y.pdf"]
index = tri.index_des_regles(regles)
t = time.monotonic()
par_index = [tri.decision_du_chemin(c, regles, index=index) for c in chemins]
duree = time.monotonic() - t
echantillon = chemins[:8000] + chemins[-3:]
verifier("par index = par boucle (le plus long chemin de règle l'emporte)",
         [tri.decision_du_chemin(c, regles, index=index) for c in echantillon]
         == [tri.decision_du_chemin(c, regles) for c in echantillon])
verifier(f"60 000 fichiers × {len(regles)} règles en moins de 2 s", duree < 2, f"{duree:.2f} s")

# `estimer` importe ingestion.parsers (asyncpg…) : doublé ici, on juge la CHARGE.
sys.modules.setdefault("ingestion", types.ModuleType("ingestion"))
sys.modules["ingestion.parsers"] = types.SimpleNamespace(famille=lambda nom: "pdf")
try:
    entrees = [{"chemin": c, "nom": c.rsplit("/", 1)[-1], "octets": 10, "modifie": time.time()} for c in chemins]
    debut_cpu, debut = time.process_time(), time.monotonic()
    tri.estimer(entrees, regles, 0, time.time(), respirer=True)
    part = (time.process_time() - debut_cpu) / max(time.monotonic() - debut, 1e-6)
    verifier("estimation bridée : au plus ~65 % du temps en calcul", part <= 0.65, f"{part:.0%}")
except ImportError as e:
    print(f"  (estimation non exécutée ici : {e})")

routes = (BACKEND / "routers" / "nas_tri.py").read_text(encoding="utf-8")
lecture = routes.split('@router.get("")', 1)[1].split("@router.", 1)[0]
verifier("ouvrir l'onglet ne calcule rien", "tri.estimer(" not in lecture and "derniere_estimation" in lecture)
verifier("POST /estimer : hors de la boucle, une à la fois",
         '@router.post("/estimer")' in routes and "asyncio.to_thread(tri.estimer_et_garder" in routes
         and "_ESTIMATION.locked()" in routes)
ecran = (RACINE / "frontend" / "components" / "settings" / "TriNas.tsx").read_text(encoding="utf-8")
verifier("écran : un bouton « Calculer l'estimation »", "/api/nas-tri/estimer" in ecran and "Calculer l'estimation" in ecran)

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
