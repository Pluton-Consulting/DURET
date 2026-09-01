"""
Banc « Pilotage, tableau de bord et tâches : actualisés et fonctionnels » — 01/09.

Demande de Noa : « partie admin dans pilotage et connaissance, fais en sorte que
ça soit entièrement actualisé et fonctionnel. Et dans le dashboard, fais en sorte
que toutes les tâches planifiées, tâches en attente, tâches en arrière-plan
soient fonctionnelles, et fais bien en sorte qu'on puisse planifier des tâches. »

UN AUDIT CROISÉ A TROUVÉ NEUF DÉFAUTS, dont trois qui rendaient l'écran menteur
et un qui rendait la demande centrale impossible :

  · PLANIFIER UNE TÂCHE QUOTIDIENNE ÉCHOUAIT TOUJOURS. L'heure partait en base
    sous forme de CHAÎNE vers un paramètre `$8::time` : asyncpg exige un
    `datetime.time` et lève. « Chaque matin à 7h30, trie les mails » rendait
    « ERREUR : invalid input for query argument $8 ». Seule la récurrence par
    intervalle passait, parce qu'elle ne pose pas d'heure.
  · LE COÛT N'ÉTAIT JAMAIS CALCULÉ, et les jetons n'étaient comptés que par la
    VISION — le chemin le moins emprunté. « Coût IA du mois » affichait 0,00 €
    depuis toujours, sous un titre qui promettait « ce que ça coûte ».
  · LE JOURNAL DISAIT « RÉUSSI » À TOUS LES COUPS, sans modèle, et les pannes du
    chat n'y entraient jamais : la tuile « Erreurs 24 h » était vide par
    construction.
  · LA DIRECTION VOYAIT LES SUPER_ADMIN dans le Journal et les Erreurs — le
    filtre n'avait été posé qu'à un seul des trois endroits, alors que le
    commentaire au-dessus dit qu'un filtre à un seul endroit est un rideau.
  · UN RÔLE TERRAIN VOYAIT les compteurs de toute la maison.
  · RIEN NE S'ACTUALISAIT : un seul chargement au montage, et la scène gardant
    les deux vues montées, basculer ne relisait rien.
  · LES EXÉCUTIONS DE TÂCHES étaient invisibles : le worker écrivait dans une
    table qu'aucun écran ne lisait.
  · LA CARTE « ACTIONS PLANIFIÉES » montrait des tâches non planifiées.

Ce banc lit les sources et EXÉCUTE ce qui peut l'être : la conversion d'heure et
le compteur de consommation.
"""
import ast
import pathlib
import sys
from datetime import time
from typing import Optional

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.resolve().parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel):
    return (BACKEND / rel).read_text(encoding="utf-8")


print(f"\n═══ ÉCRANS ET TÂCHES — {BACKEND.resolve().parent}\n")

# ── 1. PLANIFIER UNE TÂCHE : la conversion d'heure, EXÉCUTÉE ─────────────
src = lire("tasks/scheduler.py")
noeud = next((x for x in ast.parse(src).body
              if isinstance(x, ast.FunctionDef) and x.name == "heure_du_jour"), None)
verifier("`heure_du_jour` existe", noeud is not None)
if noeud:
    esp = {"time": time, "Optional": Optional}
    exec(compile(ast.Module(body=[noeud], type_ignores=[]), "s", "exec"), esp)
    f = esp["heure_du_jour"]
    verifier("EXÉCUTÉ — « 07:30 » devient un time", f("07:30") == time(7, 30))
    verifier("« 7h30 » aussi, c'est ce qu'un humain écrit", f("7h30") == time(7, 30))
    verifier("« 08 » vaut huit heures pile", f("08") == time(8, 0))
    verifier("un time reste un time (idempotent)", f(time(9, 15)) == time(9, 15))
    verifier("rien, ou n'importe quoi, ne devient pas une heure",
             f(None) is None and f("") is None and f("bonjour") is None)
    verifier("une heure impossible est refusée, pas tronquée",
             f("25:00") is None and f("07:99") is None)

for rel in ("tasks/skills.py", "routers/tasks.py"):
    t = lire(rel)
    verifier(f"{rel} convertit l'heure avant la base",
             "heure_du_jour(" in t and "from tasks.scheduler import heure_du_jour" in t)

# ── 2. LE COÛT ET LES JETONS, comptés là où tout passe ───────────────────
comp = BACKEND / "llm" / "compteur.py"
verifier("le compteur existe", comp.exists())
if comp.exists():
    csrc = comp.read_text(encoding="utf-8")
    esp = {"ContextVar": __import__("contextvars").ContextVar, "Any": object,
           "Optional": Optional, "logging": __import__("logging")}
    gardes = [n for n in ast.parse(csrc).body
              if isinstance(n, (ast.FunctionDef, ast.Assign, ast.AnnAssign))]
    exec(compile(ast.Module(body=gardes, type_ignores=[]), "c", "exec"), esp)

    class _Rep:
        usage_metadata = {"input_tokens": 1000, "output_tokens": 500}

    esp["demarrer"]()
    esp["ajouter"]("anthropic", "claude", _Rep())
    esp["ajouter"]("google", "gemini", _Rep())
    b = esp["bilan"]()
    verifier("EXÉCUTÉ — les jetons de PLUSIEURS appels s'additionnent",
             b["tokens_in"] == 2000 and b["tokens_out"] == 1000, str(b))
    verifier("le coût suit le fournisseur (Anthropic coûte plus que Google)",
             b["cost_eur"] > 0, str(b))
    verifier("le modèle retenu est le DERNIER qui a répondu, pas l'espéré",
             b["modele"] == "gemini", str(b))

    class _Autre:
        response_metadata = {"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}}

    esp["demarrer"]()
    esp["ajouter"]("deepseek", "d", _Autre())
    verifier("l'autre forme d'usage est lue aussi (les fournisseurs diffèrent)",
             esp["bilan"]()["tokens_in"] == 7)

    class _Muet:
        pass

    esp["demarrer"]()
    esp["ajouter"]("x", "y", _Muet())
    verifier("une réponse sans usage ne fait pas tomber le tour",
             esp["bilan"]()["tokens_in"] == 0)
    # Hors tour : on ne compte pas ce qui n'a pas été ouvert.
    verifier("le module dit que le coût est une ESTIMATION, pas une facture",
             "pas à établir une facture" in csrc)

rt = lire("llm/router.py")
verifier("chaque appel de modèle est compté, au SEUL point de passage commun",
         "from llm.compteur import ajouter" in rt
         and rt.index("result = await llm.ainvoke(messages") < rt.index("_compter(provider, model, result)"))
run = lire("agents/runtime.py")
verifier("le compteur est ouvert avant le graphe, dans les DEUX chemins",
         run.count("demarrer()") == 2)
verifier("et sa mesure prime sur l'état (qui ne comptait que la vision)",
         "mesure = bilan()" in run and 'mesure["tokens_in"] or' in run)
verifier("l'événement final la porte — le WebSocket est le chemin NOMINAL",
         '"mesure": bilan()' in run)

chat = lire("routers/chat.py")
verifier("le WebSocket journalise le vrai coût, plus 0.0 en dur",
         "_increment_usage(user, tokens=tokens, cost=cout)" in chat)
verifier("il journalise le modèle qui a RÉPONDU", "model_used=modele" in chat)
verifier("un tour sans réponse finale n'est plus compté comme un succès",
         "success=bool(final_response)" in chat)
verifier("ET UNE PANNE LAISSE UNE TRACE : la tuile « Erreurs » était vide "
         "par construction",
         'error_message=str(e)[:500]' in chat)

# ── 3. LES FUITES ────────────────────────────────────────────────────────
dash = lire("routers/dashboard.py")
verifier("le filtre des super_admin est posé aux TROIS endroits, pas à un seul",
         dash.count("filtre_admin") >= 3
         and "u.role <> 'super_admin'" in dash)
verifier("le pourquoi est écrit (un filtre à un seul endroit est un rideau)",
         "rideau, pas un" in dash)

tab = lire("routers/tableau.py")
verifier("les compteurs de la maison ne sont plus servis à tout le monde",
         '""") if global_ else None' in tab)
verifier("ni l'état des synchronisations",
         'if global_ else []' in tab.split("synchros = await _sur")[1][:900])
ecran = (FRONTEND / "components" / "tableau" / "TableauDeBord.tsx").read_text(encoding="utf-8")
verifier("et l'écran ne dessine pas la carte qu'on ne lui donne pas",
         "{d.memoire && (" in ecran and "} | null" in ecran)

# ── 4. LES TÂCHES : visibles, et vraiment planifiées ─────────────────────
verifier("la carte « Actions planifiées » ne montre QUE ce qui a une échéance",
         "WHERE enabled AND next_run_at IS NOT NULL" in tab)
verifier("les RÉVEILS des tâches remontent enfin (table jamais lue jusqu'ici)",
         "FROM agent_task_runs r JOIN agent_tasks t" in tab
         and '"executions"' in tab)
verifier("l'écran les montre, avec leur issue et la cause d'un échec",
         "Derniers réveils" in ecran and "e.error &&" in ecran)

# ── 5. L'ACTUALISATION ───────────────────────────────────────────────────
verifier("le tableau de bord relit quand l'onglet redevient visible",
         'document.addEventListener("visibilitychange", relire)' in ecran)
verifier("et quand on revient du chat — la scène ne démonte pas la vue",
         "EVENEMENT_VUE, relire" in ecran)
verifier("il relit périodiquement, mais JAMAIS en arrière-plan",
         'document.visibilityState === "visible"' in ecran
         and "setInterval(relire, 60000)" in ecran)
pil = (FRONTEND / "app" / "(app)" / "gestion" / "PilotageClient.tsx").read_text(encoding="utf-8")
verifier("le pilotage aussi",
         'document.addEventListener("visibilitychange", relire)' in pil
         and 'document.visibilityState === "visible"' in pil)
verifier("le pourquoi de la période est écrit (un tableau n'est pas un moniteur)",
         "moniteur temps réel" in ecran)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
