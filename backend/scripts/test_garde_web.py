"""
Banc de la garde anti-web — la question du 21/08 ne doit plus partir sur Internet.

`agent1.py` importe tout un graphe au chargement. On n'extrait donc que la
fonction visée et sa liste de mots, exécutées dans un espace de noms neuf : ce
qui est testé reste le TEXTE LIVRÉ, pas une réécriture.
"""
import sys, ast, pathlib

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
source = (pathlib.Path(BACKEND) / "agents" / "agent1.py").read_text(encoding="utf-8")
arbre = ast.parse(source)

espace = {"AgentState": dict}
for noeud in arbre.body:
    garde = isinstance(noeud, ast.Assign) and getattr(noeud.targets[0], "id", "") in ("_MOTS_INTERNES", "_MOTS_EXTERNES")
    fonction = isinstance(noeud, ast.FunctionDef) and noeud.name == "should_use_browser"
    if garde or fonction:
        exec(compile(ast.Module(body=[noeud], type_ignores=[]), "agent1", "exec"), espace)

assert "should_use_browser" in espace, "fonction absente du module livré"


class _Reglages:
    browser_enabled = True


faux = type(sys)("config"); faux.settings = _Reglages()
sys.modules["config"] = faux

decider = espace["should_use_browser"]
echecs = []


def verifier(nom, condition, detail=""):
    print(f"  {'✓' if condition else '✗'} {nom}" + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        echecs.append(nom)


print(f"\n═══ GARDE ANTI-WEB — {BACKEND}\n")

# ── 1. Les questions internes ne partent JAMAIS sur le web ────────────────
print("1. Données internes, RAG vide")
INTERNES = [
    "Sors-moi la liste de tous les clients",
    "combien de devis pour la SCI Les Tilleuls ?",
    "quel est le chiffre d'affaires de Dupont ?",
    "montre-moi mes factures impayées",
    "où en est le chantier de la mairie ?",
    "fais un check de mes mails",
    "quels sont nos fournisseurs de pierre ?",
    # LE CAS QUI A FAIT ÉCHOUER LA PREMIÈRE GARDE : pas de « mes », pas de
    # « client » — juste « les mails de la semaine ». Parti chercher la météo.
    "donne-moi les mails de la semaine",
    "combien de mails cette semaine ?",
    "quel est le prix du devis Dupont ?",          # « prix » mais c'est un devis : veto
    "résume-moi le dossier de la résidence du Port",
    # Aucun marqueur ni interne ni externe : dans le doute, on reste au-dedans.
    "quelles essences résistent au vent salé ?",
    "quelle heure est-il ?",
]
for q in INTERNES:
    verifier(f"« {q[:46]}… » reste en interne",
             decider({"query": q, "raw_chunks": [], "anonymized_chunks": []}) == "llm")

# ── 2. Une vraie question externe garde son repli web ─────────────────────
print("\n2. Demande EXPLICITE d'information publique, RAG vide")
EXTERNES = [
    "quel est le prix moyen du m2 de terrasse en ipé en 2026 ?",
    "réglementation sur les clôtures mitoyennes",
    "cherche sur internet les horaires d'ouverture de la déchetterie",
    "quelle est la météo à Arcachon demain ?",
    "qu'est-ce que le DTU 51.4 ?",
]
for q in EXTERNES:
    verifier(f"« {q[:46]}… » peut aller sur le web",
             decider({"query": q, "raw_chunks": [], "anonymized_chunks": []}) == "browser")

# ── 3. Les garde-fous d'origine tiennent toujours ────────────────────────
print("\n3. Comportements préexistants")
verifier("RAG non vide → pas de web",
         decider({"query": "prix du ipé", "raw_chunks": ["un extrait"]}) == "llm")
verifier("web déjà utilisé → on n'y retourne pas",
         decider({"query": "prix du ipé", "raw_chunks": [], "browser_used": True}) == "llm")
_Reglages.browser_enabled = False
verifier("navigateur désactivé → pas de web",
         decider({"query": "prix du ipé", "raw_chunks": []}) == "llm")
_Reglages.browser_enabled = True

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
