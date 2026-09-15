"""
Banc « UNE DEMANDE EN FILE D'ATTENTE SE SOUVIENT DE SA CONVERSATION » — export
Langfuse du 14/09, fil c9f5a00d (Symbiose, compte direction).

Pendant que « et voici le devis » tournait (trente et une minutes), la personne
a continué la conversation. Le fil principal étant occupé, ses trois messages
sont partis en file d'attente, chacun sur un fil `file:<id>` NEUF — sans un
seul message d'historique :
  · 13:06 « la palette végétale est simple, washingtonia robusta… » → versée
    quatre fois dans le document ouvert, rédaction « quatre opérations
    d'ajout ont été réalisées » ;
  · 13:08 « maintenant que tu as tous les documents… fournir un dossier » →
    ne sachant rien du client, le modèle est allé chercher « Zerrouqui » dans
    les mails ;
  · 13:14 « pourquoi veux-tu le dossier Zerrouqui ? » → « la demande n'a pas
    pu être traitée ».

CE QUE CE BANC PROUVE (sans base, sans réseau, sans LangGraph) :
  · `memoire_reprise` EXÉCUTÉE contre un graphe doublé : un fil de tâche NEUF
    reçoit les derniers messages de la conversation d'origine, la carte des
    jetons et le dernier tableau ; jamais le résumé glissant (rangs d'un autre
    fil) ; un fil qui a déjà ses messages (reprise après accord) n'est pas
    doublé ; une panne de lecture rend {} sans lever ;
  · `fil_de_la_personne` EXÉCUTÉE contre une base doublée : le fil d'un
    collègue, un fil `file:`/`task:` ou une valeur vide ne passent pas ;
  · le câblage : l'écran envoie `fil_origine`, la route le range après
    contrôle, l'exécution le passe à `stream_turn`, qui pose la reprise dans
    l'état initial.
Tombe sur la version d'avant (fonctions absentes).

Usage : python backend/scripts/test_file_memoire.py [backend]
"""
import ast
import asyncio
import logging
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    for n in arbre.body:
        cibles = n.targets if isinstance(n, ast.Assign) else []
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms) or any(
                isinstance(c, ast.Name) and c.id in noms for c in cibles):
            exec(compile(ast.Module(body=[n], type_ignores=[]), str(chemin), "exec"), espace)
    return [x for x in noms if x not in espace]


print("1. La mémoire reprise par une tâche en file")
esp = {"Optional": __import__("typing").Optional, "logger": logging.getLogger("banc"),
       "_graph_config": lambda fil, user=None: {"configurable": {"thread_id": fil}}}
manque = extraire(BACKEND / "agents/runtime.py", {"memoire_reprise", "MEMOIRE_REPRISE_MESSAGES"}, esp)
verifier("agents/runtime.py porte memoire_reprise", not manque, manque)

ETATS = {
    "conv-c9f5a00d": {"messages": [f"m{i}" for i in range(30)],
                      "entity_map": {"[PER_1]": "M. CAMP Nicolas"},
                      "dernier_tableau": {"lignes": [{"a": 1}]},
                      "resume_conversation": "résumé", "resume_couvre": 12},
    "file:reprise": {"messages": ["deja"]},
}


class Graphe:
    def __init__(self, panne=False):
        self.panne = panne

    async def aget_state(self, config):
        if self.panne:
            raise RuntimeError("checkpointer injoignable")
        return types.SimpleNamespace(values=ETATS.get(config["configurable"]["thread_id"], {}))


if not manque:
    r = asyncio.run(esp["memoire_reprise"](Graphe(), "conv-c9f5a00d", "file:neuve", "u1"))
    verifier("un fil de tâche neuf reçoit les derniers messages de la conversation",
             r.get("messages") == [f"m{i}" for i in range(10, 30)], r.get("messages"))
    verifier("… la carte des jetons et le dernier tableau",
             r.get("entity_map") == {"[PER_1]": "M. CAMP Nicolas"} and r.get("dernier_tableau"))
    verifier("… jamais le résumé glissant (rangs d'un autre fil)",
             "resume_conversation" not in r and "resume_couvre" not in r)
    verifier("un fil qui a déjà ses messages n'est pas doublé",
             asyncio.run(esp["memoire_reprise"](Graphe(), "conv-c9f5a00d", "file:reprise", "u1")) == {})
    verifier("une conversation vide ne pose rien",
             asyncio.run(esp["memoire_reprise"](Graphe(), "conv-vide", "file:neuve", "u1")) == {})
    verifier("une panne de lecture rend {} sans lever",
             asyncio.run(esp["memoire_reprise"](Graphe(panne=True), "conv-c9f5a00d", "file:x", "u1")) == {})

print("2. Le fil d'origine appartient à la personne")
LIGNES = {("conv-c9f5a00d", "u1")}


class Conn:
    async def fetchval(self, sql, fil, user):
        return 1 if (fil, user) in LIGNES else None


class Ctx:
    async def __aenter__(self):
        return Conn()

    async def __aexit__(self, *a):
        return False


esp2 = {"Optional": __import__("typing").Optional, "get_db": lambda: Ctx()}
manque2 = extraire(BACKEND / "routers/file_attente.py", {"fil_de_la_personne"}, esp2)
verifier("routers/file_attente.py porte fil_de_la_personne", not manque2, manque2)
if not manque2:
    f = esp2["fil_de_la_personne"]
    verifier("sa propre conversation passe", asyncio.run(f("conv-c9f5a00d", "u1")) == "conv-c9f5a00d")
    verifier("la conversation d'un collègue ne passe pas", asyncio.run(f("conv-c9f5a00d", "u2")) is None)
    verifier("un fil de tâche (file:/task:) ne passe pas",
             asyncio.run(f("file:abc", "u1")) is None and asyncio.run(f("task:abc", "u1")) is None)
    verifier("rien ne passe sans fil", asyncio.run(f(None, "u1")) is None and asyncio.run(f("  ", "u1")) is None)

print("3. Le câblage")
fa = (BACKEND / "routers/file_attente.py").read_text(encoding="utf-8")
rt = (BACKEND / "agents/runtime.py").read_text(encoding="utf-8")
cw = (BACKEND.parent / "frontend/components/chat/ChatWindow.tsx").read_text(encoding="utf-8")
verifier("la route range le fil d'origine APRÈS contrôle d'appartenance",
         "_ranger_fil_origine(tache_id, await fil_de_la_personne(body.fil_origine, current_user.id))" in fa)
verifier("l'exécution passe la mémoire à stream_turn", "historique_de=_reprendre_fil_origine(tache_id)" in fa)
verifier("stream_turn pose la reprise dans l'état initial",
         "memoire_reprise(graph, historique_de, thread_id, user_id)" in rt and "**reprise}" in rt)
verifier("l'écran envoie la conversation d'origine", "fil_origine: threadIdRef.current" in cw)

print()
if echecs:
    print(f"ÉCHEC : {len(echecs)} contrôle(s)")
    sys.exit(1)
print("Tous les contrôles passent.")
