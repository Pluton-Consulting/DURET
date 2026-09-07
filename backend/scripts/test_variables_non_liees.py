"""
Banc « UNE VARIABLE LUE AVANT D'EXISTER » — relevé du 07/09 chez Duret.

Export Langfuse `1788803568867-…json` : chaque tour mourait dans `rehydrate`
sur « cannot access local variable 'besoin' where it is not associated with a
value », et l'écran disait « Une erreur est survenue » quoi qu'on demande.
Cause : `besoin` n'était affecté que dans deux branches d'un `if … elif …`, puis
lu par `if besoin:` — sur tout tour ORDINAIRE (ni promesse, ni démenti), il
n'existait pas. Symbiose avait `besoin = None` depuis le refactor du 30/08 ;
le portage chez Duret l'avait perdu, et rien ne l'a vu pendant une semaine :
`py_compile` accepte ce code, `test_imports_manquants` ne regarde que les
modules, et un banc qui exécute le nœud passe forcément par une des branches.

CE QUE CE BANC FAIT : pour chaque fonction des modules livrés, il cherche un
`if` de premier niveau dont le test LIT une variable locale qui n'a reçu
aucune affectation INCONDITIONNELLE avant lui. Une affectation dans les deux
branches d'un `if/else`, ou dans un `try` dont chaque `except` sort (raise,
return), compte comme inconditionnelle. C'est une analyse volontairement
étroite : elle ne connaît que la forme exacte du défaut vu en production,
pour ne jamais crier à tort.

Tombe sur la version d'avant chez Duret ; passe des deux côtés ensuite.
"""
import ast
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []

DOSSIERS = ("agents", "skills", "routers", "mail", "outils", "learning", "tasks",
            "bureautique", "vectorstore", "llm", "auth", "nas", "visuels", "voix")


def _cibles(noeud) -> set:
    """Les noms qu'un nœud d'affectation lie."""
    noms = set()
    for c in ast.walk(noeud):
        if isinstance(c, ast.Name) and isinstance(c.ctx, ast.Store):
            noms.add(c.id)
    return noms


# Les fonctions du projet qui LÈVENT toujours (SkillError) : un `except` qui se
# termine par l'une d'elles sort de la fonction, comme un `raise`.
_LEVE_TOUJOURS = ("_echec", "_refus", "_erreur")


def _sort_toujours(corps) -> bool:
    """Un bloc qui se termine par raise / return / continue / break, ou par un
    appel qui lève toujours (`_echec(...)`)."""
    if not corps:
        return False
    fin = corps[-1]
    if isinstance(fin, (ast.Raise, ast.Return, ast.Continue, ast.Break)):
        return True
    if (isinstance(fin, ast.Expr) and isinstance(fin.value, ast.Call)
            and isinstance(fin.value.func, ast.Name) and fin.value.func.id in _LEVE_TOUJOURS):
        return True
    return False


def _lie_toujours(stmt) -> set:
    """Les noms qu'une instruction lie SANS CONDITION."""
    if isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        cibles = set()
        for t in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]):
            cibles |= _cibles(t)
        return cibles
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in stmt.names}
    if isinstance(stmt, (ast.For, ast.AsyncFor)):
        # La cible d'une boucle n'est liée que si elle tourne : on ne compte pas.
        return set()
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        noms = set()
        for item in stmt.items:
            if item.optional_vars is not None:
                noms |= _cibles(item.optional_vars)
        for s in stmt.body:
            noms |= _lie_toujours(s)
        return noms
    if isinstance(stmt, ast.If):
        if not stmt.orelse:
            return set()
        dans_if = set()
        for s in stmt.body:
            dans_if |= _lie_toujours(s)
        dans_else = set()
        for s in stmt.orelse:
            dans_else |= _lie_toujours(s)
        # Une branche qui SORT ne compte pas contre l'autre.
        if _sort_toujours(stmt.body):
            return dans_else
        if _sort_toujours(stmt.orelse):
            return dans_if
        return dans_if & dans_else
    if isinstance(stmt, ast.Try):
        dans_try = set()
        for s in stmt.body:
            dans_try |= _lie_toujours(s)
        for h in stmt.handlers:
            if _sort_toujours(h.body):
                continue
            dans_h = set()
            for s in h.body:
                dans_h |= _lie_toujours(s)
            dans_try &= dans_h
        for s in stmt.finalbody:
            dans_try |= _lie_toujours(s)
        return dans_try
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {stmt.name}
    return set()


def _locales(fn) -> set:
    """Tous les noms affectés quelque part dans la fonction (donc LOCAUX).

    Les cibles d'une compréhension (`any(m in n for m in …)`) et les
    arguments d'une lambda ont leur propre portée : ils ne sont pas des
    locaux de la fonction, et les compter faisait crier sur `m` ou `g`.
    """
    noms = set()
    portee_propre = set()
    for c in ast.walk(fn):
        if isinstance(c, ast.comprehension):
            portee_propre |= _cibles(c.target)
        elif isinstance(c, ast.Lambda):
            portee_propre |= {a.arg for a in c.args.args + c.args.kwonlyargs}
    for c in ast.walk(fn):
        if isinstance(c, ast.Name) and isinstance(c.ctx, ast.Store):
            noms.add(c.id)
        elif isinstance(c, (ast.Global, ast.Nonlocal)):
            noms -= set(c.names)
    # Un nom qui n'est lié QUE dans une compréhension n'est pas un local.
    lies_ailleurs = set()
    for stmt in ast.walk(fn):
        if isinstance(stmt, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.For, ast.AsyncFor,
                             ast.With, ast.AsyncWith, ast.NamedExpr)):
            cible = getattr(stmt, "target", None) or getattr(stmt, "targets", None)
            if cible is None and isinstance(stmt, (ast.With, ast.AsyncWith)):
                cible = [i.optional_vars for i in stmt.items if i.optional_vars is not None]
            for t in (cible if isinstance(cible, list) else [cible]):
                if t is not None:
                    lies_ailleurs |= _cibles(t)
    return (noms - portee_propre) | (portee_propre & lies_ailleurs)


def _analyser(fn, chemin) -> list:
    args = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    if fn.args.vararg:
        args.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        args.add(fn.args.kwarg.arg)
    globaux = set()
    for c in ast.walk(fn):
        if isinstance(c, (ast.Global, ast.Nonlocal)):
            globaux |= set(c.names)
    locales = _locales(fn) - args - globaux
    liees = set(args)
    defauts = []
    for stmt in fn.body:
        if isinstance(stmt, ast.If):
            # Les cibles d'une compréhension DANS le test (`any(x for r in …)`)
            # ont leur propre portée : on ne les juge pas.
            propres = set()
            for c in ast.walk(stmt.test):
                if isinstance(c, ast.comprehension):
                    propres |= _cibles(c.target)
            for c in ast.walk(stmt.test):
                if (isinstance(c, ast.Name) and isinstance(c.ctx, ast.Load)
                        and c.id in locales and c.id not in liees and c.id not in propres):
                    defauts.append(f"{chemin}:{c.lineno} {fn.name}() lit « {c.id} » "
                                   "qui n'existe pas sur tous les chemins")
        liees |= _lie_toujours(stmt)
    return defauts


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ VARIABLES LUES AVANT D'EXISTER — {BACKEND.parent}\n")

# ── Le détecteur est éprouvé sur la forme EXACTE du défaut, puis sur des formes saines ──
EXEMPLE_FAUTIF = '''
def rehydrate(text):
    if not text:
        besoin = "vide"
    elif text == "x":
        besoin = "x"
    if besoin:
        return besoin
'''
EXEMPLES_SAINS = '''
def a(text):
    besoin = None
    if text:
        besoin = "x"
    if besoin:
        return 1

def b(text):
    if text:
        besoin = "x"
    else:
        besoin = "y"
    if besoin:
        return 1

def c(text):
    try:
        besoin = int(text)
    except ValueError:
        return None
    if besoin:
        return 1

def d(text):
    if not text:
        return None
    else:
        besoin = 2
    if besoin:
        return 1

def e(text, besoin=None):
    if besoin:
        return 1
'''
faux = [d for fn in ast.parse(EXEMPLE_FAUTIF).body for d in _analyser(fn, "exemple")]
verifier("le détecteur reconnaît la forme exacte du défaut de production", len(faux) == 1, faux)
sains = [d for fn in ast.parse(EXEMPLES_SAINS).body for d in _analyser(fn, "exemple")]
verifier("…et ne crie pas sur une affectation préalable, un if/else, un try qui sort, un argument",
         not sains, sains)

# ── Puis sur les modules livrés ──
defauts = []
fichiers = 0
for dossier in DOSSIERS:
    for chemin in sorted((BACKEND / dossier).rglob("*.py")) if (BACKEND / dossier).exists() else []:
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        except SyntaxError:
            continue          # une f-string 3.12 sur un poste en 3.9 : ce n'est pas le sujet
        fichiers += 1
        for n in ast.walk(arbre):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                defauts += _analyser(n, str(chemin.relative_to(BACKEND)))
verifier(f"aucune fonction des {fichiers} modules livrés ne lit une variable qui peut ne pas exister",
         not defauts, "\n      ".join(defauts))

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
