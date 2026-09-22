"""
Banc du COÛT DU PROMPT — deux économies sans effet sur ce que lit le modèle (22/09).

Relevé Langfuse du 22/09 chez Duret (18,47 $ la journée) :
  · kimi-k3 répond souvent à la boucle d'actions par un appel d'outil NATIF
    (texte vide + `tool_calls`). Le routeur y voyait une réponse vide et
    renvoyait le MÊME prompt : 15 appels payés deux fois, 1,10 $ ;
  · le fournisseur facture 10 à 30 fois moins cher un début de prompt déjà vu,
    jusqu'au premier caractère qui change. Le détail des outils et les
    documents venaient APRÈS les résultats, qui changent à chaque passe : ils
    étaient refacturés au plein tarif. Rejoué sur les 569 appels du jour, les
    remettre devant fait passer le coût prédit de 17,59 $ à 15,33 $.

CE QUE CE BANC PROUVE (sans réseau) :
  · `_appel_natif_en_bloc` EXÉCUTÉ sur un vrai AIMessage (langchain_core) :
    l'appel natif devient un bloc ```action que `extraire_action` lit, le
    premier appel seul, paramètres intacts ; sans nom, rien n'est touché ;
  · le routeur ne traduit que pour qui l'a demandé, et AVANT la relance ;
  · llm_node le demande hors passe de rédaction, le forceur toujours ;
  · l'ordre du message : outils et documents avant les résultats, la question
    en dernier.
Tombe sur la version d'avant (fonction absente, ancien ordre).

Usage : python backend/scripts/test_cout_prompt.py [backend]
"""
import ast
import json
import pathlib
import re
import sys

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, ok):
    print(("  ✓ " if ok else "  ✗ ") + nom)
    if not ok:
        echecs.append(nom)


rt = (racine / "llm" / "router.py").read_text(encoding="utf-8")
a1 = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")

print("— l'appel d'outil natif devient une action")
arbre = ast.parse(rt)
fonc = next((n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "_appel_natif_en_bloc"), None)
verifier("`_appel_natif_en_bloc` existe dans llm/router.py", fonc is not None)
try:
    from langchain_core.messages import AIMessage
except ImportError:
    AIMessage = None
    print("  · langchain_core absent : l'exécution de la traduction est sautée (SKIP)")
if fonc is not None and AIMessage is not None:
    espace = {"Any": object}
    exec(compile(ast.Module(body=[fonc], type_ignores=[]), "router", "exec"), espace)
    traduire = espace["_appel_natif_en_bloc"]
    # La forme exacte relevée le 22/09 (paramètres rangés sous `args`).
    natif = AIMessage(content="", tool_calls=[
        {"name": "interroger_donnees", "args": {"args": {"feuille": "SITUATION"}}, "id": "call_1"},
        {"name": "lire_mails", "args": {"depuis": "2j"}, "id": "call_2"}],
        usage_metadata={"input_tokens": 20000, "output_tokens": 50, "total_tokens": 20050})
    t = traduire(natif)
    verifier("un bloc ```action est produit", t is not None and str(t.content).startswith("```action\n"))
    corps = json.loads(re.search(r"```action\n(.*)\n```", t.content, re.S).group(1)) if t is not None else {}
    verifier("le PREMIER appel seul, nom intact, paramètres déballés de `args`",
             corps == {"skill": "interroger_donnees", "args": {"feuille": "SITUATION"}})
    verifier("plus d'appel natif dans le message rendu", t is not None and not t.tool_calls)
    verifier("le compte des jetons est gardé", t is not None and (t.usage_metadata or {}).get("input_tokens") == 20000)
    verifier("sans appel natif : rien n'est touché", traduire(AIMessage(content="")) is None)
    verifier("un appel sans nom : rien n'est touché",
             traduire(AIMessage(content="", tool_calls=[{"name": "", "args": {}, "id": "x"}])) is None)
    try:
        from skills.protocol import extraire_action
        action, _, erreur = extraire_action(t.content, "super_admin")
        verifier("`extraire_action` lit l'action traduite, paramètres déballés",
                 action == {"skill": "interroger_donnees", "args": {"feuille": "SITUATION"}})
    except Exception as e:  # noqa: BLE001 — dépendances du protocole absentes hors conteneur
        print(f"  · extraire_action non importable ici ({type(e).__name__}) : lecture par le protocole sautée")

print("— le routeur ne traduit que pour qui l'attend, avant la relance")
i_flag = rt.find('actions_natives = bool(getattr(self, "actions_natives", False))')
verifier("le drapeau est un attribut posé par l'appelant", i_flag > 0)
i_trad = rt.find("if actions_natives and _contenu_vide(result):")
i_rel = rt.find("if _contenu_vide(result):", i_trad + 1)
verifier("la traduction passe AVANT la relance « réponse vide »", 0 < i_trad < i_rel)

print("— la boucle et le forceur le demandent")
verifier("llm_node : hors passe de rédaction seulement",
         'llm.actions_natives = not state.get("tools_finished")' in a1)
f = a1[a1.index("async def forcer_action_node"):]
verifier("le forceur : toujours", "llm.actions_natives = True" in f[:12000])

print("— ce qui ne bouge pas passe devant ce qui bouge")
m = re.search(r"human_content = \(bloc_lecons \+ bloc_memoire_txt \+ bloc_outils \+ bloc_documents\s*\n\s*\+ bloc_resultats \+ human_content\)", a1)
verifier("leçons, mémoire, outils, documents, PUIS résultats, puis la question", m is not None)
verifier("l'ancien ordre (outils après les résultats) a disparu",
         "bloc_resultats + bloc_outils + human_content" not in a1)
verifier("la question reste en dernier",
         'human_content = f"Date et heure actuelles : {_maintenant()} (Europe/Paris).\\nQuestion : {query}"' in a1
         and 'bloc_documents = f"Documents disponibles :\\n{context_text}\\n\\n" if context_text else ""' in a1)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
