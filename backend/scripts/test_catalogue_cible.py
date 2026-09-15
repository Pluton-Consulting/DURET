"""
Banc du CATALOGUE CIBLÉ — ne détailler au modèle que les outils utiles (15/09).

Demande de Noa : des consignes plus ciblées. Le prompt portait ~41 000
caractères de catalogue (tous les outils, en détail, à chaque tour). Le
ROUTEUR — un modèle déjà appelé à chaque tour — choisit les familles d'outils
utiles ; seules celles-là sont détaillées, avec la question ; le prompt système
ne garde qu'un INDEX d'une ligne par outil, identique d'un tour à l'autre (le
cache du fournisseur continue de servir).

CE QUE CE BANC PROUVE (sans réseau, routeur doublé) :
  · `skills/familles.py` : aucun choix → tout est détaillé ; une liste vide →
    les outils toujours utiles et ceux qu'aucune famille ne nomme ; une famille
    → ses outils ; un outil déjà utilisé dans le tour reste détaillé ; chaque
    outil DÉCLARÉ dans le code appartient à une famille (le tableau est tenu) ;
  · `skills/protocol.py` : l'index nomme TOUS les outils sans leurs paramètres,
    le détail ne porte que ceux retenus, une erreur de paramètres rend le
    détail de l'outil appelé ;
  · `routeur_node` EXÉCUTÉ : « outils » et « correction » sont lus ; une liste
    illisible vaut « tout détailler » ; une panne aussi ;
  · le câblage de llm_node (index au système, détail avec la question) et du
    forceur (catalogue complet, contexte neuf).
Tombe sur la version d'avant (module absent).

Usage : python backend/scripts/test_catalogue_cible.py [backend]
"""
import ast
import asyncio
import importlib
import json
import pathlib
import re
import sys
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = [n for n in arbre.body
              if (isinstance(n, ast.ImportFrom) and n.module == "__future__")
              or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms)]
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    return [x for x in noms if x not in espace]


print("1. Les familles")
try:
    F = importlib.import_module("skills.familles")
except Exception as e:  # noqa: BLE001
    F = None
    verifier("skills/familles.py existe", False, e)
if F:
    noms = ["lire_mail", "envoyer_email", "creer_document", "drive_ouvrir", "rechercher_documents",
            "competence_validee_en_base", "chercher_web"]
    verifier("aucun choix : tout est détaillé", F.a_detailler(noms, None) == set(noms))
    verifier("liste vide : les toujours utiles et les inconnus des familles",
             F.a_detailler(noms, []) == {"rechercher_documents", "competence_validee_en_base"})
    verifier("« mails » : les outils du courrier, plus les toujours utiles",
             F.a_detailler(noms, ["mails"]) == {"lire_mail", "envoyer_email", "rechercher_documents",
                                                 "competence_validee_en_base"})
    verifier("un outil déjà utilisé dans le tour reste détaillé",
             "drive_ouvrir" in F.a_detailler(noms, ["mails"], ["drive_ouvrir"]))
    verifier("familles valides : les inconnues tombent, l'ordre reste",
             F.familles_valides(["mails", "inconnue", "documents", "mails"]) == ["mails", "documents"])
    verifier("rien de reconnu : None", F.familles_valides(["mail"]) is None and F.familles_valides("x") is None)
    verifier("le routeur lit une ligne par famille", all(f'"{f}"' in F.liste_pour_le_routeur() for f in F.FAMILLES))

    declares = set()
    for chemin in list((racine / "skills").glob("*.py")) + list((racine / "mail").glob("*.py")):
        texte = chemin.read_text(encoding="utf-8")
        declares |= set(re.findall(r'^\s{4}"([a-z_0-9]+)": Declaration\(', texte, re.M))
    proto = (racine / "skills" / "protocol.py").read_text(encoding="utf-8")
    declares |= set(re.findall(r'^\s{4}"([a-z_0-9]+)": \(\n\s*(?:#[^\n]*\n\s*)*"', proto, re.M))
    ranges = {n for fam in F.FAMILLES.values() for n in fam} | set(F.TOUJOURS)
    orphelins = sorted(declares - ranges)
    verifier("chaque outil déclaré dans le code appartient à une famille (sinon il est détaillé à chaque tour)",
             not orphelins, orphelins)

print("2. L'index et le détail")
CAT = {"lire_mail": ("OUVRE un message en entier. Le corps complet est rendu.", ["ref"], ["pieces"]),
       "creer_document": ("Ouvre un document Word ou PDF; il se remplit ensuite", ["titre"], ["format"])}
esp = {"catalogue": lambda role=None: CAT, "re": re}
manque = extraire(racine / "skills" / "protocol.py",
                  {"_ligne_detaillee", "_resume", "detail_actions", "instruction_actions"}, esp)
verifier("protocol porte l'index et le détail", not manque, manque)
if not manque:
    index = esp["instruction_actions"]("direction", compacte=True)
    complet = esp["instruction_actions"]("direction")
    verifier("l'index nomme chaque outil, sans ses paramètres",
             "- lire_mail : OUVRE un message en entier." in index and "Paramètres (" not in index)
    verifier("le catalogue complet garde le détail", "Paramètres (ref*, pieces)" in complet)
    detail = esp["detail_actions"]("direction", {"lire_mail"})
    verifier("le détail ne porte que les outils retenus", "lire_mail" in detail and "creer_document" not in detail)
    verifier("rien de retenu : aucun détail", esp["detail_actions"]("direction", set()) == "")
src_proto = (racine / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("une erreur de paramètres rend le détail de l'outil", "Détail de l'action : " in src_proto)

print("3. routeur_node exécuté")


class _LLM:
    reponse = ""
    panne = False

    async def ainvoke(self, messages):
        if _LLM.panne:
            raise RuntimeError("panne")
        return types.SimpleNamespace(content=_LLM.reponse)


sys.modules["llm"] = types.ModuleType("llm")
sys.modules["llm.router"] = types.SimpleNamespace(get_llm=lambda t: _LLM(), LLMTier=types.SimpleNamespace(LIGHT="light"))
sys.modules["langchain_core"] = types.ModuleType("langchain_core")
sys.modules["langchain_core.messages"] = types.SimpleNamespace(HumanMessage=lambda content: types.SimpleNamespace(content=content))
sys.modules["agents.memoire_conversation"] = types.SimpleNamespace(question_meta=lambda q: False)


class _Journal:
    def info(self, *a, **k):
        pass
    debug = warning = info


espr = {"logger": _Journal(), "AgentState": dict}
manque = extraire(racine / "agents" / "agent1.py", {"routeur_node", "_echange_precedent"}, espr)
if manque:
    verifier("agent1 porte routeur_node", False, manque)
else:
    etat = {"query": "mais c'est pas ma signature ça, reprends la bonne depuis un mail envoyé",
            "messages": [types.SimpleNamespace(type="ai", content="La signature a bien été apprise.")]}
    _LLM.reponse = json.dumps({"memoire": False, "requete": "", "effort": "simple",
                               "outils": ["mails"], "correction": True})
    r = asyncio.run(espr["routeur_node"](etat))
    verifier("« outils » et « correction » sont lus",
             r.get("familles_outils") == ["mails"] and r.get("correction_signalee") is True, r)
    _LLM.reponse = json.dumps({"memoire": False, "effort": "simple", "outils": [], "correction": False})
    r = asyncio.run(espr["routeur_node"]({"query": "explique-moi ce que tu sais faire", "messages": []}))
    verifier("liste vide : [] (seuls les outils toujours utiles)", r.get("familles_outils") == [], r)
    _LLM.reponse = json.dumps({"memoire": False, "effort": "simple", "outils": ["mail"]})
    r = asyncio.run(espr["routeur_node"]({"query": "lis mes derniers messages", "messages": []}))
    verifier("une famille illisible (« mail ») : tout détailler", r.get("familles_outils") is None, r)
    _LLM.panne = True
    r = asyncio.run(espr["routeur_node"]({"query": "lis mes derniers messages", "messages": []}))
    verifier("une panne du routeur : tout détailler, pas de correction",
             r.get("familles_outils") is None and r.get("correction_signalee") is False, r)
    _LLM.panne = False

print("4. Le câblage")
a1 = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("llm_node : index au système quand une famille est choisie",
         'compacte=state.get("familles_outils") is not None' in a1)
verifier("llm_node : le détail vient avec la question", "bloc_resultats + bloc_outils + human_content" in a1)
f = a1[a1.index("async def forcer_action_node"):]
verifier("le forceur garde le catalogue complet (contexte neuf)", "instruction_actions(role)" in f[:3000])
etat_src = (racine / "agents" / "state.py").read_text(encoding="utf-8")
verifier("`familles_outils` et `correction_signalee` sont déclarées",
         "familles_outils: Optional[List[str]]" in etat_src and "correction_signalee: bool" in etat_src)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
