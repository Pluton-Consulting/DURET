"""
Banc « OÙ EN EST LA CAMPAGNE « ENRICHIR LES DOCUMENTS » » (14/09) — socle.

Relevé de Noa (Duret) : « En cours… · En ce moment : ouverture des fichiers
(voir la carte du connecteur ci-dessous) — il n'y a aucun détail de où il en
est, il faudrait une vraie barre de progression détaillée ». La carte ne
disait qu'une phrase pendant des heures, et le rapporteur d'avancement des
synchronisations, limité à une écriture par seconde, pouvait sauter le passage
d'une étape à l'autre (le relevé → l'ouverture des fichiers).

CE QUE CE BANC PROUVE : le rapporteur (`routers/ingestion._avancement`,
EXÉCUTÉ contre une base doublée) écrit toujours un changement d'étape et ne
coupe plus l'étape à 200 caractères ; la campagne expose son étape en code et
son connecteur ; l'écran dessine les quatre étapes avec leur barre et suit la
carte du connecteur en direct. Le même fichier des deux côtés ; le relevé du
NAS a son propre banc chez Duret (`test_progression_nas.py`).
Tombe sur la version d'avant.
"""
import ast
import asyncio
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ OÙ EN EST LA CAMPAGNE — {RACINE}\n")

print("— Le rapporteur n'avale pas un changement d'étape")
ing = (BACKEND / "routers" / "ingestion.py").read_text(encoding="utf-8")

fn = next(n for n in ast.parse(ing).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_avancement")
ECRITS = []


class _Conn:
    async def execute(self, sql, *a):
        ECRITS.append(a)


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *x):
        return False


espace = {"get_db": lambda: _Db()}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "ingestion", "exec"), espace)
poser = asyncio.run(espace["_avancement"]("sync-1"))


async def _sequence():
    await poser(0, None, "je relève l'arborescence du NAS · 12 dossiers lus")
    await poser(0, None, "je relève l'arborescence du NAS · 13 dossiers lus")   # même seconde : sautée
    await poser(0, 120, "18 530 fichiers au catalogue · 120 à ouvrir")          # même seconde, nouvelle étape
asyncio.run(_sequence())
verifier("EXÉCUTÉ — le passage du relevé à l'ouverture s'écrit, même dans la même seconde",
         [e[1] for e in ECRITS] == [None, 120], ECRITS)
verifier("l'étape n'est plus coupée à 200 caractères", "[:400]" in ing)

print("— La campagne et l'écran")
camp = (BACKEND / "learning" / "enrichissement_docs.py").read_text(encoding="utf-8")
verifier("la campagne expose son étape en code et son connecteur",
         all(f'_ETAT["etape"] = "{c}"' in camp for c in ("ouverture", "assemblage", "classement", "analyse", "terminee", "interrompue"))
         and '"connecteur": connecteur' in camp)
ecran = (RACINE / "frontend" / "components" / "settings" / "SyncTab.tsx").read_text(encoding="utf-8")
verifier("l'écran dessine les quatre étapes, celle en cours avec sa barre",
         "function EtapesEnrichissement" in ecran and "Analyser et apprendre" in ecran
         and "<Barre pourcentage={pctAnalyse} />" in ecran)
verifier("pendant l'ouverture, la carte suit le connecteur en direct",
         'etats.find((x) => x.source === enrichDocs.connecteur)' in ecran and "<AvancementConnecteur e={connecteur} />" in ecran)
verifier("« 0 traité(s) » immobile remplacé par ce qui est vrai pendant le relevé",
         "le total sera connu à la fin du relevé" in ecran)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
