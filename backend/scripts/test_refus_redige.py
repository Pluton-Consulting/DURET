"""
Banc de LA RÉPONSE APRÈS UN REFUS (22/09, Duret, prompts 4, 14 et 18 de la recette).

Après « Refuser » sur une carte de dépôt, le tour rendait tel quel le texte d'attente posé à
l'armement de l'accord — « Action « nas_deposer » en attente de validation. » —, faux puisque
l'action venait d'être refusée, et tout ce que le modèle avait établi avant (au prompt 18 :
de quel fichier viennent l'en-tête et le pied) était perdu.

CE QUE CE BANC PROUVE (fonctions EXTRAITES de agents/router.py et EXÉCUTÉES, rédacteur et
anonymiseur doublés) :
  · un refus passe par `apres_refus`, une approbation par `execute_action`, un tour sans
    action en attente termine ;
  · le rédacteur reçoit TOUS les résultats du tour, plus l'action refusée (non exécutée,
    avec sa cible) et la cause « refus_de_la_personne » ;
  · la réponse finale = la prose du modèle + les cartes des fichiers produits ; le texte
    d'attente figé a disparu ;
  · modèle muet : les cartes seules, jamais le texte figé ;
  · le graphe déclare le nœud et ses arêtes ; la consigne du rédacteur connaît le refus.
Tombe sur la version d'avant (`apres_refus_node` absent).

Usage : python backend/scripts/test_refus_redige.py [backend]
"""
import ast
import asyncio
import pathlib
import re
import sys
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


source_routeur = (racine / "agents" / "router.py").read_text(encoding="utf-8")
source_agent1 = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")
arbre = ast.parse(source_routeur)
fonctions = {n.name: ast.get_source_segment(source_routeur, n) for n in arbre.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

if "apres_refus_node" not in fonctions:
    verifier("agents/router.py définit `apres_refus_node`", False, "absent")
    print(f"\n✗ {len(echecs)} échec(s)")
    sys.exit(1)

# ── Doublures : l'anonymiseur (identité) et le rédacteur (capture ce qu'il reçoit) ──
appels = []
REPONSE = {"texte": "Le dépôt sur le NAS a été refusé. La note reprend l'en-tête de « entete duret.docx »."}


async def _rediger(demande, resultats, cause=""):
    appels.append({"demande": demande, "resultats": resultats, "cause": cause})
    return REPONSE["texte"]


class _Anon:
    @staticmethod
    def anonymize(texte, carte):
        return texte, carte

    @staticmethod
    def rehydrate(texte, carte):
        return texte

    @staticmethod
    def find_placeholders(texte):
        return []


sys.modules["security"] = types.ModuleType("security")
sys.modules["security.anonymizer"] = types.SimpleNamespace(anonymizer=_Anon())
sys.modules["agents"] = types.ModuleType("agents")
sys.modules["agents.agent1"] = types.SimpleNamespace(
    _rediger_par_le_modele=_rediger,
    _BLOC_UI_RE=re.compile(r"```ui\s*(\{.*?\})\s*```", re.S))

espace = {"AgentState": dict, "logger": types.SimpleNamespace(info=lambda *a, **k: None)}
exec(fonctions["apres_refus_node"] + "\n\n" + fonctions["route_apres_gate"], espace)
apres_refus_node = espace["apres_refus_node"]
route_apres_gate = espace["route_apres_gate"]

CARTE = ('```ui\n{"type": "fichier", "url": "/api/documents/RXG9D5", '
         '"nom": "Note d\'information aux occupants.docx", "format": "docx"}\n```')
ETAT = {
    "anonymized_query": "Produis une note d'information aux occupants à la charte Duret & Sols…",
    "final_response": "Action « nas_deposer » en attente de validation.\n\n" + CARTE,
    "pending_action": {"skill": "nas_deposer",
                       "args": {"dossier": "/home/Drive/04-Chantiers a executer/CHANTIERS 2026/AFF 051-26",
                                "nom": "Note d'information aux occupants.docx"}},
    "tool_results": [
        {"skill": "nas_chercher", "ok": True, "resultat_masque": '{"resultats": [{"nom": "entete duret.docx"}]}'},
        {"skill": "creer_document", "ok": True, "resultat_masque": '{"pages": 1, "titre": "Note…"}'},
    ],
    "validation_status": "rejected",
}

print("1. Le routage après la décision")
verifier("refus → `apres_refus`", route_apres_gate(ETAT) == "apres_refus")
verifier("approbation → `execute_action`", route_apres_gate({**ETAT, "validation_status": "approved"}) == "execute_action")
verifier("sans action en attente → fin", route_apres_gate({**ETAT, "pending_action": None}) == "fin")

print("2. La réponse est rédigée par le modèle, les cartes restent")
sortie = asyncio.run(apres_refus_node(dict(ETAT)))
finale = sortie.get("final_response") or ""
verifier("le rédacteur est appelé une fois, cause « refus_de_la_personne »",
         len(appels) == 1 and appels[0]["cause"] == "refus_de_la_personne", appels)
if appels:
    res = appels[0]["resultats"]
    verifier("il reçoit TOUS les résultats du tour (ce qui a été lu et produit)",
             [r.get("skill") for r in res[:2]] == ["nas_chercher", "creer_document"], res)
    verifier("puis l'action refusée, non exécutée, avec sa cible",
             res[-1].get("skill") == "nas_deposer" and res[-1].get("ok") is False
             and "refusé" in res[-1].get("resultat_masque", "") and "AFF 051-26" in res[-1].get("resultat_masque", ""),
             res[-1])
verifier("la réponse finale porte la prose du modèle", REPONSE["texte"] in finale, finale)
verifier("la carte du fichier produit reste sous le texte", CARTE in finale, finale)
verifier("le texte d'attente figé a disparu", "en attente de validation" not in finale, finale)
verifier("plus aucune action en attente", sortie.get("pending_action") is None)

print("3. Modèle muet : les cartes seules, jamais le texte figé")
REPONSE["texte"] = ""
sortie = asyncio.run(apres_refus_node(dict(ETAT)))
verifier("les cartes seules", (sortie.get("final_response") or "").strip() == CARTE, sortie.get("final_response"))

print("4. Le graphe et la consigne")
verifier("le graphe déclare le nœud", 'graph.add_node("apres_refus", apres_refus_node)' in source_routeur)
verifier("la porte humaine peut y mener", '"apres_refus": "apres_refus"' in source_routeur)
verifier("le nœud termine le tour", 'graph.add_edge("apres_refus", END)' in source_routeur)
verifier("la consigne du rédacteur sait ce qu'est un refus",
         'cause == "refus_de_la_personne"' in source_agent1 and "REFUSÉE par la personne" in source_agent1)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
