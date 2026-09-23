"""
Banc « LE MÊME FICHIER DU NAS, AJOUTÉ DEUX FOIS » (23/09, Duret).

Conversation de Damien, 16:12 : « lis-le entièrement et propose-moi le classement »
→ « Plusieurs pièces différentes répondent à /home/Drive/SUIVI ADM DOSSIERS.xlsx ».
Le classeur avait été ajouté aux sources à 10:50, puis de nouveau à 12:08 après une
modification sur le NAS : deux versions, même adresse. La plus récente doit servir.

CE QUE CE BANC PROUVE (module EXÉCUTÉ sur une base SQLite temporaire) : deux versions
d'une même adresse → la plus récente ; deux fichiers DIFFÉRENTS du même nom à deux
adresses → toujours une ambiguïté dite ; un exemplaire unique → inchangé.
"""
import importlib.util
import pathlib
import sys
import tempfile
import time
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LE MÊME FICHIER AJOUTÉ DEUX FOIS — {BACKEND}\n")
dossier = pathlib.Path(tempfile.mkdtemp())
registre = types.ModuleType("ressources.registre")
registre._chemin = lambda: dossier / "registre.json"
sys.modules.setdefault("ressources", types.ModuleType("ressources"))
sys.modules["ressources.registre"] = registre
spec = importlib.util.spec_from_file_location("dossiers_banc", BACKEND / "ressources" / "dossiers.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

U, F = "u-damien", "fil-1"
ADR = "/home/Drive/SUIVI ADM DOSSIERS.xlsx"
ancienne = d.enregistrer(U, F, "SUIVI ADM DOSSIERS.xlsx", "version de 10:50", reference=ADR)
time.sleep(0.02)
recente = d.enregistrer(U, F, "SUIVI ADM DOSSIERS.xlsx", "version de 12:08, modifiée sur le NAS", reference=ADR)

try:
    r = d.sources(U, F, [ADR])
    verifier("par son adresse : la version la plus récente", [x["id"] for x in r] == [recente], r)
except ValueError as e:
    verifier("par son adresse : la version la plus récente", False, str(e)[:120])
try:
    r = d.sources(U, F, ["SUIVI ADM DOSSIERS.xlsx"])
    verifier("par son nom : la version la plus récente", [x["id"] for x in r] == [recente], r)
except ValueError as e:
    verifier("par son nom : la version la plus récente", False, str(e)[:120])
verifier("par son identifiant : la version demandée, même ancienne",
         [x["id"] for x in d.sources(U, F, [ancienne])] == [ancienne])

d.enregistrer(U, "fil-2", "DPGF.xlsx", "lot 11", reference="/home/Drive/AFF 1/DPGF.xlsx")
d.enregistrer(U, "fil-2", "DPGF.xlsx", "lot 12", reference="/home/Drive/AFF 2/DPGF.xlsx")
try:
    d.sources(U, "fil-2", ["DPGF.xlsx"])
    verifier("deux fichiers différents, même nom, deux adresses : ambiguïté dite", False, "aucune erreur")
except ValueError as e:
    verifier("deux fichiers différents, même nom, deux adresses : ambiguïté dite", "Plusieurs pièces" in str(e))

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
