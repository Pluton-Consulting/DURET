"""
Banc de la vitesse d'un tour — moins d'appels en série, connexions réutilisées.

POURQUOI. Noa, 31/08 : « fais en sorte que la vitesse de réponse soit plus
rapide ». Le gros de la lenteur est le CHOIX DES MODÈLES (LongCat ~60 s l'appel,
réglage Paramètres) — mais le code ajoutait le sien, sur le chemin critique de
CHAQUE tour :
  * le routeur payait un appel LLM léger à chaque message, même « oui » ;
  * le résumé glissant (un appel LLM) et le rappel vectoriel (un embedding)
    tournaient EN SÉRIE avant l'appel principal ;
  * chaque appel LLM reconstruisait son client (poignée de main TLS) ;
  * chaque embedding ouvrait un client HTTP neuf.
Ce banc lit le code livré (et exécute le cache des modèles sur une fabrique
doublée : réutilisation, et invalidation quand la clé API change).
"""
import ast
import pathlib
import re
import sys
from typing import Any, Optional

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ VITESSE D'UN TOUR — {BACKEND.parent}\n")
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
routeur = agent1[agent1.index("async def routeur_node("):agent1.index("async def recherche_node(")]
verifier("routeur : la voie RAPIDE juge une suite courte sans appel LLM",
         "question_meta(" in routeur and '"besoin_memoire": False' in routeur
         and routeur.index("question_meta(") < routeur.index("get_llm("))
verifier("routeur : la voie rapide ne coupe pas les vraies questions (le prédicat est celui du banc de cohérence)",
         "from agents.memoire_conversation import question_meta" in routeur)
verifier("mémoire : résumé glissant et rappel vectoriel en PARALLÈLE, plus en série",
         re.search(r"gather\(\s*fondre_dans_le_resume\(.*?rappeler_echanges\(", agent1, re.S) is not None)

routeur_llm = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")
verifier("LLM : les instances sont mises en CACHE (connexion réutilisée entre les appels)",
         "_MODELES" in routeur_llm and "def _construire_modele(" in routeur_llm)
verifier("LLM : le cache s'invalide quand la clé API change (Paramètres)",
         re.search(r"def _build_model\(.*?\[-6:\]", routeur_llm, re.S) is not None)
try:
    arbre = ast.parse(routeur_llm)
    espace: dict = {"Optional": Optional, "Any": Any}
    for noeud in arbre.body:
        if isinstance(noeud, ast.FunctionDef) and noeud.name == "_build_model":
            exec(compile(ast.Module([noeud], []), "router", "exec"), espace)  # noqa: S102
        # `_MODELES: dict = {}` est une affectation ANNOTÉE (AnnAssign), pas un Assign.
        if ((isinstance(noeud, ast.Assign) and any(getattr(c, "id", "") == "_MODELES" for c in noeud.targets))
                or (isinstance(noeud, ast.AnnAssign) and getattr(noeud.target, "id", "") == "_MODELES")):
            exec(compile(ast.Module([noeud], []), "router", "exec"), espace)  # noqa: S102
    fabriques = []
    espace["_construire_modele"] = lambda p, m, mt, d: fabriques.append((p, m)) or object()
    cles = {"groq": "sk-abc123"}
    espace["_cle"] = lambda p: cles.get(p, "")
    a = espace["_build_model"]("groq", "llama", 1024, 45)
    b = espace["_build_model"]("groq", "llama", 1024, 45)
    verifier("même couple (fournisseur, modèle, budget, délai) → même instance, UNE construction",
             a is b and len(fabriques) == 1)
    espace["_build_model"]("groq", "llama", 2048, 45)
    verifier("un budget différent → une autre instance", len(fabriques) == 2)
    cles["groq"] = "sk-NOUVELLE99"
    c = espace["_build_model"]("groq", "llama", 1024, 45)
    verifier("la clé change → l'instance est reconstruite (pas de vieux client avec la vieille clé)",
             c is not a and len(fabriques) == 3)
except Exception as e:  # noqa: BLE001
    verifier("le cache des modèles s'exécute sur une fabrique doublée", False, repr(e))

embeddings = (BACKEND / "vectorstore" / "embeddings.py").read_text(encoding="utf-8")
gemini = embeddings[embeddings.index("async def _embed_gemini("):embeddings.index("async def _embed_ollama(")]
verifier("embeddings Gemini : client HTTP PARTAGÉ (plus de TLS à chaque appel)",
         "_client()" in gemini and "AsyncClient(timeout=60) as client" not in gemini)
verifier("le client partagé se recrée s'il a été fermé", "is_closed" in embeddings)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
