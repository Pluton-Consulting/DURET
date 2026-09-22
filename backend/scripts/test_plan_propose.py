"""
Banc du PLAN ÉCRIT QUI DEVIENT UN PLAN PROPOSÉ (22/09, Duret, prompts 7, 8 et 19).

Devant une demande longue, le modèle a répondu par un bloc ```ui plan aux étapes toutes
« à faire », sans bloc d'action : il suivait la consigne du catalogue des blocs (« annonce le
plan dès ta PREMIÈRE réponse »), contraire à `proposer_plan`. Le graphe l'a pris pour la
réponse finale — rien d'exécuté, aucune carte d'accord — et le relecteur, qui retirait les
blocs avant de juger, n'a vu qu'une réponse vide.

CE QUE CE BANC PROUVE (`_plan_en_proposition` EXTRAITE de agents/agent1.py et EXÉCUTÉE sur la
FORME EXACTE des réponses des prompts 7 et 19, noms de chantiers neutralisés) :
  · un plan aux étapes toutes « à faire », sans action, devient un `proposer_plan` avec ses
    étapes, son titre et son résumé ;
  · rien ne change quand : une étape est franchie (compte rendu), un plan est déjà approuvé,
    une action est déjà demandée, un long texte accompagne le plan, `proposer_plan` n'est
    pas au catalogue du rôle ;
  · la consigne du catalogue ne dit plus d'annoncer le plan en bloc, et le relecteur juge
    une réponse faite de composants seuls.
Tombe sur la version d'avant (`_plan_en_proposition` absent).

Usage : python backend/scripts/test_plan_propose.py [backend]
"""
import ast
import json
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


source = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")
arbre = ast.parse(source)
fonctions = {n.name: ast.get_source_segment(source, n) for n in arbre.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

print("1. Le catalogue et le relecteur")
verifier("le catalogue ne dit plus « annonce le plan dès ta PREMIÈRE réponse »",
         "annonce le plan dès ta PREMIÈRE réponse" not in source)
verifier("le bloc plan sert à rendre compte, l'annonce passe par proposer_plan",
         "Ce bloc n’ANNONCE jamais un travail : pour annoncer, c’est `proposer_plan`" in source)
verifier("le relecteur juge une réponse faite de composants seuls",
         "[réponse faite uniquement de composants d'écran]" in source)

if "_plan_en_proposition" not in fonctions:
    verifier("agents/agent1.py définit `_plan_en_proposition`", False, "absent")
    print(f"\n✗ {len(echecs)} échec(s)")
    sys.exit(1)

print("2. Un plan écrit sans être proposé devient la proposition")
_ACTION = re.compile(r"```action\s*(\{.*?\})\s*```", re.S)
CATALOGUE = {"valeur": {"proposer_plan", "nas_lister", "lire_mails"}}
filets = []
sys.modules["skills"] = types.ModuleType("skills")
sys.modules["skills.protocol"] = types.SimpleNamespace(
    demande_une_action=lambda texte, role=None: bool(_ACTION.search(texte or "")),
    catalogue=lambda role=None: CATALOGUE["valeur"])
espace = {"_BLOC_UI_RE": re.compile(r"```ui\s*(\{.*?\})\s*```", re.S),
          "_tracer_filet": lambda state, filet, cause, **d: filets.append((filet, cause, d))}
exec(fonctions["_plan_en_proposition"], espace)
convertir = espace["_plan_en_proposition"]

# La forme EXACTE des réponses de production (prompts 7 et 19), chantiers neutralisés.
P07 = ('```ui\n{"type": "plan", "titre": "Chronologie – AFF 000-26 Chantier Exemple - VILLE", "resume": '
       '"Explorer le dossier NAS du chantier, lire les mails de la boîte, relever devis/situations/factures, '
       'rédiger la fiche chronologique d\'une page et la déposer dans le dossier du chantier.", "etapes": ['
       '{"titre": "Explorer le dossier NAS AFF 000-26 : commandes, situations, factures, documents produits", "etat": "a_faire"}, '
       '{"titre": "Lire les mails de la boîte concernant le chantier", "etat": "a_faire"}, '
       '{"titre": "Relever les devis, situations et factures liés au chantier dans les données importées", "etat": "a_faire"}, '
       '{"titre": "Rédiger la fiche chronologique d\'une page (tableau, une source par ligne)", "etat": "a_faire"}, '
       '{"titre": "Déposer la fiche dans le dossier du chantier", "etat": "a_faire"}]}\n```')
P19 = ('```ui\n{"type": "plan", "titre": "Planning 4e trimestre 2026 — 3 équipes", "resume": "Lire les chantiers '
       'et échéances des deux sources, construire le planning sous contrainte de 3 équipes et 7 h/jour, produire '
       'l\'Excel mensuel avec charge et taux d\'occupation, puis signaler les surcharges.", "etapes": ['
       '{"titre": "Lire « Planning masse chantier.xlsx » et relever chantiers, villes, prestations, durées, échéances", "etat": "a_faire"}, '
       '{"titre": "Lire les chantiers en cours et relever les mêmes données", "etat": "a_faire"}, '
       '{"titre": "Construire le planning octobre à décembre sous contrainte de 3 équipes et 7 h/jour", "etat": "a_faire"}, '
       '{"titre": "Produire l\'Excel (une feuille par mois, charge mensuelle, taux d\'occupation)", "etat": "a_faire"}, '
       '{"titre": "Contrôler et signaler les semaines en surcharge et les chantiers à décaler", "etat": "a_faire"}]}\n```')
ETAT = {"user_role": "super_admin"}

for nom, texte in (("prompt 7", P07), ("prompt 19", P19)):
    sortie = convertir(texte, ETAT)
    m = _ACTION.search(sortie or "")
    action = json.loads(m.group(1)) if m else {}
    plan = json.loads(re.search(r"```ui\s*(\{.*?\})\s*```", texte, re.S).group(1))
    verifier(f"{nom} : devient un `proposer_plan`", action.get("skill") == "proposer_plan", sortie)
    verifier(f"{nom} : ses 5 étapes, dans l'ordre",
             action.get("args", {}).get("etapes") == [e["titre"] for e in plan["etapes"]], action)
    verifier(f"{nom} : son titre et son résumé",
             action.get("args", {}).get("titre") == plan["titre"]
             and action.get("args", {}).get("resume") == plan["resume"], action)
verifier("la conversion se trace dans la console (filet « plan_propose »)",
         filets and filets[0][:2] == ("plan_propose", "plan_ecrit_sans_proposer"), filets)
verifier("une phrase d'introduction avant le plan ne l'empêche pas",
         "proposer_plan" in convertir("Voici ce que je propose :\n\n" + P07, ETAT))

print("3. Ce qui ne change pas")
franchi = P07.replace('"etat": "a_faire"}', '"etat": "fait", "resultats": ["12 pièces"]}', 1)
verifier("une étape franchie : c'est un compte rendu, rien ne change", convertir(franchi, ETAT) == "")
verifier("un plan déjà approuvé : rien ne change", convertir(P07, {**ETAT, "plan_valide": ["a", "b"]}) == "")
avec_action = P07 + '\n```action\n{"skill": "nas_lister", "args": {"chemin": "/home"}}\n```'
verifier("une action déjà demandée : rien ne change", convertir(avec_action, ETAT) == "")
verifier("un long texte accompagne le plan : rien ne change", convertir("x " * 400 + P07, ETAT) == "")
verifier("un texte sans plan : rien ne change", convertir("Bonjour, voici la réponse.", ETAT) == "")
CATALOGUE["valeur"] = {"nas_lister"}
verifier("`proposer_plan` absent du catalogue du rôle : rien ne change", convertir(P07, ETAT) == "")

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
