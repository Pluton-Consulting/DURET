"""
Banc de l'état du graphe — « une clé que l'AgentState ne déclare pas n'existe pas ».

POURQUOI. LangGraph ne garde d'un TypedDict que les clés DÉCLARÉES : une clé
posée par `runtime` (`etat["tour_debut"] = time.time()`) ou renvoyée par un
nœud (`{"tour_debut": ...}`) est jetée en silence avant d'atteindre le nœud
suivant. Le 04/09, le temps imparti d'un tour (TOUR_DUREE_MAX_S, huit minutes)
a été posé ainsi — et n'a JAMAIS tourné : `state.get("tour_debut")` valait
toujours None. Le 14/09, « et voici le devis » a tourné trente et une minutes,
159 `ajouter_document`, sans qu'aucun garde ne l'arrête. Ni `py_compile`, ni
un banc qui appelle le nœud avec un dict Python (lui garde tout) ne le voient.

CE QUE CE BANC PROUVE, sur le source livré et sans LangGraph : toute clé LUE
(`state.get("x")`, `state["x"]`) ou ÉCRITE dans l'état (`etat["x"] = …`, clés
d'un dict renvoyé par une fonction qui reçoit `state`, ou d'un dict nommé
`maj` / `armement`) dans `agents/` est déclarée dans `AgentState`. Il sait
échouer : sans `tour_debut` dans la déclaration, il tombe.

Usage : python backend/scripts/test_etat_declare.py [backend]
"""
import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def declarees() -> set:
    arbre = ast.parse((BACKEND / "agents/state.py").read_text(encoding="utf-8"))
    for n in ast.walk(arbre):
        if isinstance(n, ast.ClassDef) and n.name == "AgentState":
            return {b.target.id for b in n.body
                    if isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name)}
    return set()


def cles_ecrites(fichier: pathlib.Path) -> dict:
    """{clé: [fonction, …]} pour les écritures d'état repérables."""
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    trouve: dict = {}

    def noter(cle, ou):
        trouve.setdefault(cle, set()).add(ou)

    for f in ast.walk(arbre):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in f.args.args + f.args.kwonlyargs}
        recoit_etat = "state" in params
        for n in ast.walk(f):
            # etat["x"] = …  /  maj["x"] = …
            if isinstance(n, ast.Assign):
                for cible in n.targets:
                    if (isinstance(cible, ast.Subscript) and isinstance(cible.value, ast.Name)
                            and cible.value.id in ("etat", "maj", "armement")
                            and isinstance(cible.slice, ast.Constant)
                            and isinstance(cible.slice.value, str)):
                        noter(cible.slice.value, f.name)
                # maj = {…} / armement = {…}
                if (isinstance(n.value, ast.Dict)
                        and any(isinstance(c, ast.Name) and c.id in ("maj", "armement")
                                for c in n.targets)):
                    for k in n.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            noter(k.value, f.name)
            # return {…} dans une fonction qui reçoit l'état
            if (recoit_etat and isinstance(n, ast.Return)
                    and isinstance(n.value, ast.Dict)):
                for k in n.value.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        noter(k.value, f.name)
    return trouve


def cles_lues(texte: str) -> set:
    return set(re.findall(r'\bstate\.get\(\s*"([A-Za-z_0-9]+)"', texte)) | \
        set(re.findall(r'\bstate\[\s*"([A-Za-z_0-9]+)"\s*\]', texte))


print("État du graphe : clés déclarées")
decl = declarees()
verifier("AgentState est lisible", len(decl) > 40, f"{len(decl)} clés")
verifier("tour_debut est déclaré (temps imparti d'un tour)", "tour_debut" in decl)

manquantes: dict = {}
for fichier in sorted((BACKEND / "agents").glob("*.py")):
    if fichier.name == "state.py":
        continue
    texte = fichier.read_text(encoding="utf-8")
    for cle in cles_lues(texte):
        if cle not in decl:
            manquantes.setdefault(cle, set()).add(f"{fichier.name} (lue)")
    for cle, fonctions in cles_ecrites(fichier).items():
        if cle not in decl:
            manquantes.setdefault(cle, set()).update(f"{fichier.name}:{fn}" for fn in fonctions)

# Filtre : un dict dont AUCUNE clé n'est déclarée n'est pas une mise à jour
# d'état (réponse d'API, entrée de résultat). On recalcule par fonction.
faux = set()
for fichier in sorted((BACKEND / "agents").glob("*.py")):
    if fichier.name == "state.py":
        continue
    arbre = ast.parse(fichier.read_text(encoding="utf-8"))
    for f in ast.walk(arbre):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(f):
            d = n.value if isinstance(n, (ast.Return, ast.Assign)) else None
            if isinstance(d, ast.Dict):
                cles = {k.value for k in d.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if cles and not (cles & decl):
                    faux |= {(c, f"{fichier.name}:{f.name}") for c in cles}

reelles = {}
for cle, ou in manquantes.items():
    restes = {o for o in ou if (cle, o) not in faux}
    if restes:
        reelles[cle] = restes

verifier("toute clé d'état lue ou écrite dans agents/ est déclarée",
         not reelles, "; ".join(f"{k} ← {sorted(v)}" for k, v in sorted(reelles.items())))

print()
if echecs:
    print(f"ÉCHEC : {len(echecs)} contrôle(s)")
    sys.exit(1)
print("Tous les contrôles passent.")
