"""
Banc « la frise et la ligne d'activité racontent la même histoire » — 01/09.

Relevé de Noa : « les éléments et le suivi dans "En ce moment" ne sont pas
cohérents avec les textes de thinking au-dessus du chat ». Les deux affichages
lisaient le même tour par deux sources différentes : la ligne d'activité suit
les LIBELLÉS du journal (par action), la frise suivait les NŒUDS bruts du
graphe — tout le travail des actions s'affichait sous « J'agis et je rédige »
pendant que la ligne disait « je cherche dans la mémoire », l'étape active
était la plus AVANCÉE au lieu de la COURANTE, et « Je protège les noms » se
cochait même l'anonymisation coupée.

Ce banc prouve : le serveur émet le skill en cours avec chaque événement de
nœud (`skill_du_moment`, exécuté), l'écran le traduit en étape mémoire/web,
la frise suit le DERNIER nœud, et l'étape de protection ne s'allume que si le
masquage a réellement parlé.
"""
import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = (BACKEND.resolve().parent / "frontend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = []
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            gardes.append(n)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id in noms for c in n.targets):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ FRISE COHÉRENTE — {BACKEND.resolve().parent}\n")

# ── 1. Le serveur dit par quel geste le travail passe ────────────────────
espace = extraire(BACKEND / "agents" / "journal.py", {"skill_du_moment"}, {})
sdm = espace["skill_du_moment"]
verifier("le nœud d'actions émet le skill qui vient de tourner",
         sdm("tools", {"tool_results": [{"skill": "rechercher_documents", "ok": True}]})
         == "rechercher_documents")
verifier("une action en attente de validation est dite aussi",
         sdm("tools", {"pending_action": {"skill": "envoyer_email"}}) == "envoyer_email")
verifier("les autres nœuds n'émettent rien", sdm("llm", {"tool_results": [{"skill": "x"}]}) == "")
verifier("un état mal formé ne casse rien",
         sdm("tools", None) == "" and sdm("tools", {"tool_results": ["brut"]}) == "")

runtime = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
verifier("l'événement de nœud du flux porte le skill",
         '"skill": skill_du_moment(node_name' in runtime
         and "from agents.journal import libelle, skill_du_moment" in runtime)
verifier("la reprise post-validation le porte aussi",
         runtime.count('"skill": skill_du_moment(node_name') >= 2)

# ── 2. L'écran le traduit en étape, et la frise suit le DERNIER nœud ─────
chat = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("etapeDuSkill : un geste web allume l'étape web, un geste de lecture l'étape mémoire",
         "function etapeDuSkill" in chat and '"chercher_web"' in chat
         and '"drive_"' in chat and '"nas_"' in chat and '"rechercher"' in chat)
verifier("le skill de l'événement est poussé dans la frise, en dernier (étape active)",
         re.search(r"const pseudo = etapeDuSkill\(", chat)
         and re.search(r"prev\[prev\.length - 1\] === pseudo \? prev : \[\.\.\.prev, pseudo\]", chat))
verifier("« anonymize » muet (masquage coupé) n'entre pas dans la frise",
         re.search(r'n !== "anonymize" \|\| libelle', chat))

frise = (FRONTEND / "components" / "chat" / "ReasoningPath.tsx").read_text(encoding="utf-8")
verifier("l'étape active est celle du DERNIER nœud, plus la plus avancée",
         "const courant" in frise and "steps.length - 1" in frise
         and re.search(r'if \(loading && i === actif\) return "active"', frise))
verifier("`rag` a quitté l'étape de protection : elle ne s'allume que sur `anonymize`",
         re.search(r'nodes: \["classify", "check_schedule", "rag"\]', frise)
         and re.search(r'nodes: \["anonymize"\]', frise))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
