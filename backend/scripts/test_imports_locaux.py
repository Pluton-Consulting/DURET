"""
Banc des IMPORTS LOCAUX HORS DE PORTÉE — un nom importé DANS une fonction,
utilisé dans une AUTRE (14/09).

LE BUG QU'IL AURAIT ÉVITÉ. Relevé de Noa (Symbiose) : « Le point sur vos mails
de la semaine n'a pas pu être effectué : name '_json' is not defined ». Le
10/09, la coupe des résultats de gestes (`_reduire_valeur`,
`_tailler_resultat`, `agents/agent1.py`) a été écrite avec `_json` — alias
importé partout ailleurs DANS les fonctions (`import json as _json`), jamais en
tête du module. Tout résultat plus gros que son plafond (une semaine de mails)
levait. Le banc de la coupe injectait `_json` lui-même : il ne pouvait pas le
voir. `test_imports_manquants` non plus : il ne connaît que les noms de
modules (`json`), pas leurs alias.

LA RÈGLE, SANS FAUX POSITIF SUR LES VARIABLES : un nom qui est la cible d'un
`import` QUELQUE PART dans le fichier doit, à chaque lecture, être lié dans sa
portée — au module, ou dans une fonction englobante (import, affectation,
paramètre, fonction imbriquée). C'est exactement la faute « importé ici,
utilisé là ». Deux fautes du même type ont été trouvées dans la foulée : le
repli de `security/anonymizer.py` (`settings`) et la délégation de domaine du
Drive (`build`).
"""
import ast
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


PORTEES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def cibles_import(arbre) -> set:
    noms = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name != "*":
                    noms.add((a.asname or a.name).split(".")[0])
    return noms


def lies_directs(portee) -> set:
    """Les noms liés DANS cette portée, sans descendre dans les portées imbriquées."""
    lies = set()
    if isinstance(portee, PORTEES):
        a = portee.args
        for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
            lies.add(arg.arg)
    corps = portee.body if isinstance(portee.body, list) else [portee.body]
    pile = list(corps)
    while pile:
        n = pile.pop()
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                lies.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lies.add(n.name)
            continue                                  # portée à part
        elif isinstance(n, ast.Lambda):
            continue
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            lies.add(n.id)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            lies.update(n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            lies.add(n.name)
        elif isinstance(n, ast.alias):
            continue
        pile.extend(ast.iter_child_nodes(n))
    return lies


def fautes(chemin: pathlib.Path) -> list:
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    suspects = cibles_import(arbre)
    au_module = lies_directs(arbre)
    sortie = []

    def visiter(noeud, chaine):
        for enfant in ast.iter_child_nodes(noeud):
            if isinstance(enfant, PORTEES):
                visiter(enfant, chaine + [enfant])
                continue
            if isinstance(enfant, ast.ClassDef):
                visiter(enfant, chaine)
                continue
            if (isinstance(enfant, ast.Name) and isinstance(enfant.ctx, ast.Load)
                    and enfant.id in suspects and enfant.id not in au_module
                    and not any(enfant.id in lies_directs(p) for p in chaine)):
                # Les compréhensions lient leurs propres cibles.
                sortie.append((enfant.lineno, enfant.id,
                               getattr(chaine[-1], "name", "<lambda>") if chaine else "<module>"))
            visiter(enfant, chaine)

    visiter(arbre, [])
    return sortie


print(f"\n═══ IMPORTS LOCAUX HORS DE PORTÉE — {BACKEND.parent}\n")
total = 0
for f in sorted(BACKEND.rglob("*.py")):
    if "__pycache__" in f.parts or "scripts" in f.parts:
        continue
    try:
        trouve = fautes(f)
    except SyntaxError:
        continue
    total += 1
    for ligne, nom, fn in trouve:
        verifier(f"{f.relative_to(BACKEND)}:{ligne} — « {nom} » importé ailleurs, hors de portée dans {fn}()",
                 False)
verifier(f"{total} modules lus, aucun nom importé hors de sa portée", not echecs)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s)' if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
