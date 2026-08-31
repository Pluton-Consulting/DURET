"""
Banc des routeurs du graphe — « toute étiquette renvoyée par un routeur est une arête ».

POURQUOI. Le 31/08, trois tours de suite sont morts sur « Une erreur est
survenue » (280 s, 545 s, 62 s de travail jetés) : `route_apres_llm` renvoyait
« llm » alors que la table des arêtes posée juste en dessous ne connaissait que
tools / forcer / rediger / rehydrate. LangGraph lève un KeyError, le tour
meurt, et l'écran affiche une phrase écrite dans le code. Le banc d'arêtes
existant lisait la TABLE (chaque cible est-elle un nœud ?) mais jamais ce que
les routeurs RENVOIENT — il était vert au-dessus du trou.

CE QUE CE BANC PROUVE, sur le source livré et sans LangGraph (absent du poste
de contrôle) : pour chaque `add_conditional_edges("nœud", routeur, {table})`,
toute chaîne littérale qu'un `return` du routeur peut produire est une clé de
la table. Il sait ÉCHOUER : lancé sur la version d'avant le correctif, il
tombe sur « llm ».

Plus trois contrôles de la reprise bornée (le KeyError n'était que le
symptôme ; la cause est une seconde redemande de rédaction qui n'aurait pas dû
exister) et le plafond d'appels d'un même skill.

Usage : python backend/scripts/test_graphe_routeurs.py [backend] [--source chemin/agent1.py]
"""
import pathlib
import re
import sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BACKEND = pathlib.Path(args[0] if args else "backend")
SOURCE = None
if "--source" in sys.argv:
    SOURCE = pathlib.Path(sys.argv[sys.argv.index("--source") + 1])

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def corps_de(fonction: str, source: str) -> str:
    """Le texte d'une fonction de premier niveau, jusqu'au prochain def/class."""
    m = re.search(rf"^(?:async )?def {re.escape(fonction)}\(", source, re.M)
    if not m:
        return ""
    fin = re.search(r"^(?:async )?def |^class ", source[m.end():], re.M)
    return source[m.start():m.end() + (fin.start() if fin else len(source))]


def etiquettes_renvoyees(corps: str) -> set:
    """Toutes les chaînes littérales qu'un `return` peut produire (y compris
    « a if … else b »). Les commentaires et docstrings sont retirés d'abord :
    une phrase qui cite « return "x" » ne doit pas compter."""
    sans_doc = re.sub(r'"""[\s\S]*?"""', "", corps)
    sans_com = "\n".join(l.split("  #")[0] if not l.lstrip().startswith("#") else ""
                         for l in sans_doc.splitlines())
    sortie = set()
    for ligne in re.findall(r"^\s*return\s+(.+)$", sans_com, re.M):
        if ligne.lstrip().startswith("{"):
            continue                      # un nœud rend un dict, pas une étiquette
        # `state.get("x")` et `state["x"]` dans une condition ne sont pas des
        # étiquettes : on les retire avant de lire les littéraux.
        ligne = re.sub(r'\.get\(\s*"[^"]+"[^)]*\)', "", ligne)
        ligne = re.sub(r'\["[^"]+"\]', "", ligne)
        sortie |= set(re.findall(r'"([a-z_0-9]+)"', ligne))
    return sortie


def tables(source: str) -> list:
    """(nœud, routeur, {clés}) pour chaque add_conditional_edges à table."""
    sortie = []
    for m in re.finditer(r'add_conditional_edges\(\s*"([a-z_0-9]+)"\s*,\s*([A-Za-z_0-9]+)\s*,'
                         r'\s*(\{[\s\S]*?\})\s*,?\s*\)', source):
        cles = set(re.findall(r'"([a-z_0-9]+)"\s*:', m.group(3)))
        sortie.append((m.group(1), m.group(2), cles))
    return sortie


print(f"\n═══ ROUTEURS DU GRAPHE — {BACKEND}\n")

fichiers = [SOURCE] if SOURCE else [BACKEND / "agents" / "agent1.py", BACKEND / "agents" / "agent2.py"]
for chemin in fichiers:
    src = chemin.read_text(encoding="utf-8")
    print(f"1. {chemin.name} : ce que renvoie chaque routeur est une clé de sa table")
    t = tables(src)
    verifier(f"{chemin.name} : au moins une table d'arêtes lue", bool(t))
    for noeud, routeur, cles in t:
        corps = corps_de(routeur, src)
        if not corps:
            verifier(f"{routeur} : routeur trouvé dans le source", False, "fonction absente")
            continue
        renvoyees = etiquettes_renvoyees(corps)
        hors_table = sorted(renvoyees - cles)
        verifier(f"{noeud} → {routeur} : {sorted(renvoyees)} ⊆ {sorted(cles)}",
                 not hors_table, f"étiquette(s) sans arête : {hors_table} — KeyError garanti")

if not SOURCE:
    print("\n2. La reprise de rédaction est BORNÉE (agent1.py)")
    a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
    rediger = corps_de("rediger_node", a1)
    verifier("rediger_node pose redaction_forcee (sinon la note dispense llm_node de le poser)",
             '"redaction_forcee": True' in rediger)
    llm = corps_de("llm_node", a1)
    verifier("llm_node garde un drapeau déjà posé (collant dans le tour)",
             'redaction_a_reprendre = bool(state.get("redaction_forcee"))' in llm)
    route = corps_de("route_apres_llm", a1)
    verifier("route_apres_llm ne renvoie plus jamais « llm »", '"llm"' not in etiquettes_renvoyees(route))
    verifier("runtime remet redaction_forcee à zéro à chaque tour",
             '"redaction_forcee": False' in (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8"))

    print("\n3. Plafond d'appels d'un même skill par tour")
    verifier("MAX_APPELS_MEME_SKILL déclaré", re.search(r"^MAX_APPELS_MEME_SKILL = \d+", a1, re.M) is not None)
    verifier("le plafond est inférieur au plafond global (sinon il ne sert à rien)",
             int(re.search(r"^MAX_APPELS_MEME_SKILL = (\d+)", a1, re.M).group(1))
             < int(re.search(r"^MAX_ACTIONS_PAR_TOUR = (\d+)", a1, re.M).group(1)))
    verifier("ajouter_document exempté (un rapport se construit par morceaux)",
             '"ajouter_document"' in re.search(r"^SKILLS_SANS_PLAFOND = (.+)$", a1, re.M).group(1))
    verifier("la garde sort par une NOTE, pas par une exception",
             "memes >= MAX_APPELS_MEME_SKILL" in a1 and "return _sortir(f\"l'action « {action['skill']} » a déjà été appelée" in a1)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
