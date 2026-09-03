"""
Banc des IMPORTS MANQUANTS — un module qui utilise `os` sans l'importer.

LE BUG QU'IL AURAIT ÉVITÉ (03/09). L'export Langfuse de Symbiose montre CHAQUE
recherche Drive morte sur « name 'os' is not defined » : `import os` avait
quitté `ingestion/connectors/google_drive.py` dans le commit du 31/08 (Drive
incrémentale), et `os.path.exists` était appelé cinq fois plus bas. Deux jours
de « je n'ai pas trouvé le fichier » en prod, sur un mot qui manque.

Python ne dit rien à la compilation : un nom non défini n'est une erreur qu'à
l'EXÉCUTION de la ligne. `py_compile` passe, le backend démarre, et c'est le
premier utilisateur qui découvre. Ce banc fait ce que `py_compile` ne fait pas :
pour chaque module, il cherche les noms de la bibliothèque standard qui sont
UTILISÉS sans être IMPORTÉS — ni en tête de module, ni dans la fonction qui
s'en sert, ni dans une fonction englobante.

Volontairement borné aux modules standard courants : c'est là que la faute se
commet (on retire un import « inutile » qui ne l'était pas), et c'est ce qui
garde le banc sans faux positif sur des variables locales.
"""
import ast
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []

SUSPECTS = {
    "os", "re", "json", "pathlib", "asyncio", "time", "datetime", "logging", "hashlib",
    "base64", "io", "shutil", "tempfile", "uuid", "math", "random", "secrets",
    "collections", "itertools", "functools", "subprocess", "urllib", "html", "zipfile",
    "csv", "struct", "unicodedata", "textwrap", "string", "copy", "traceback", "inspect",
    "typing", "contextlib", "dataclasses", "enum", "statistics", "decimal", "glob",
    "mimetypes", "smtplib", "ssl", "socket", "signal", "threading", "queue", "heapq",
    "bisect", "operator", "warnings", "zlib", "gzip", "tarfile", "pickle", "sqlite3",
    "binascii", "codecs", "calendar", "sys", "platform", "importlib", "pkgutil", "types",
    "abc", "difflib", "ipaddress", "hmac", "email", "mimetypes",
}


def _lies_par_import(noeud) -> set[str]:
    """Les noms qu'un import pose dans la portée : `import os` → os,
    `import os.path` → os, `from x import y as z` → z."""
    noms: set[str] = set()
    if isinstance(noeud, ast.Import):
        for a in noeud.names:
            noms.add((a.asname or a.name).split(".")[0])
    elif isinstance(noeud, ast.ImportFrom):
        for a in noeud.names:
            noms.add(a.asname or a.name)
    return noms


def _noms_poses(corps) -> set[str]:
    """Ce qu'un bloc DÉFINIT directement (sans descendre dans les fonctions
    imbriquées) : imports, affectations, fonctions, classes, boucles, with."""
    poses: set[str] = set()

    def _cibles(c):
        if isinstance(c, ast.Name):
            poses.add(c.id)
        elif isinstance(c, (ast.Tuple, ast.List)):
            for x in c.elts:
                _cibles(x)
        elif isinstance(c, ast.Starred):
            _cibles(c.value)

    def _visiter(n):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            poses.update(_lies_par_import(n))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            poses.add(n.name)
            return                     # son corps est une autre portée
        elif isinstance(n, ast.Assign):
            for c in n.targets:
                _cibles(c)
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            _cibles(n.target)
        elif isinstance(n, (ast.For, ast.AsyncFor)):
            _cibles(n.target)
        elif isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                if item.optional_vars is not None:
                    _cibles(item.optional_vars)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            poses.add(n.name)
        elif isinstance(n, (ast.NamedExpr,)):
            _cibles(n.target)
        for enfant in ast.iter_child_nodes(n):
            if isinstance(enfant, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            _visiter(enfant)

    for n in corps:
        _visiter(n)
    return poses


def _parametres(fn) -> set[str]:
    a = fn.args
    tous = list(a.args) + list(a.posonlyargs) + list(a.kwonlyargs)
    noms = {x.arg for x in tous}
    if a.vararg:
        noms.add(a.vararg.arg)
    if a.kwarg:
        noms.add(a.kwarg.arg)
    return noms


def controler(chemin: pathlib.Path) -> list[str]:
    """Les usages d'un module standard sans import visible, « ligne : nom »."""
    try:
        arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    except SyntaxError:
        return []                      # Python 3.12 seulement (f-string) : hors sujet ici
    fautes: list[str] = []

    def _parcourir(corps, portee: set[str]):
        for n in ast.walk(ast.Module(body=list(corps), type_ignores=[])):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Une fonction : sa portée = celle d'au-dessus + ses paramètres + ce qu'elle pose.
                interne = portee | _parametres(n) | _noms_poses(n.body)
                _parcourir(n.body, interne)
            elif isinstance(n, ast.ClassDef):
                _parcourir(n.body, portee | _noms_poses(n.body))
        # Les usages DIRECTS de ce bloc (hors fonctions imbriquées, déjà traitées).
        for n in corps:
            for x in ast.walk(n):
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and x is not n:
                    continue
                if (isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
                        and x.value.id in SUSPECTS and x.value.id not in portee):
                    # Ne pas compter un usage situé DANS une fonction imbriquée de ce bloc.
                    fautes.append(f"{x.lineno} : {x.value.id}.{x.attr}")

    # Parcours par portées explicites, pour ne pas confondre les niveaux.
    def _parcourir_precis(corps, portee):
        for n in corps:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _parcourir_precis(n.body, portee | _parametres(n) | _noms_poses(n.body))
                continue
            if isinstance(n, ast.ClassDef):
                _parcourir_precis(n.body, portee | _noms_poses(n.body))
                continue
            # Les nœuds de ce niveau, sans entrer dans les fonctions imbriquées.
            pile = [n]
            while pile:
                x = pile.pop()
                if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    # une fonction imbriquée dans un if/for : même règle
                    _parcourir_precis([x], portee)
                    continue
                if isinstance(x, ast.Lambda):
                    pile.extend(ast.iter_child_nodes(x))
                    continue
                if (isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
                        and x.value.id in SUSPECTS and x.value.id not in portee):
                    fautes.append(f"{x.lineno} : {x.value.id}.{x.attr}")
                pile.extend(ast.iter_child_nodes(x))

    _parcourir_precis(arbre.body, _noms_poses(arbre.body) | {"__name__", "__file__"})
    # Dédoublonner en gardant l'ordre
    vus: set[str] = set()
    propres = []
    for f in fautes:
        if f not in vus:
            vus.add(f)
            propres.append(f)
    return propres


print(f"\n═══ IMPORTS MANQUANTS — {BACKEND}\n")
fichiers = sorted(p for p in BACKEND.rglob("*.py")
                  if "__pycache__" not in p.parts and "scripts" not in p.parts
                  and "node_modules" not in p.parts)
total = 0
for f in fichiers:
    fautes = controler(f)
    total += 1
    if fautes:
        rel = f.relative_to(BACKEND)
        print(f"  ✗ {rel} : {', '.join(fautes[:4])}" + (" …" if len(fautes) > 4 else ""))
        echecs.append(str(rel))
print(f"  {total} modules contrôlés")
if not echecs:
    print("  ✓ aucun module n'utilise un module standard sans l'importer")

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
