"""
Banc « une photo jointe ne se réinvente pas, un 503 se réessaie » — 01/09.

Deux relevés dans l'export Langfuse du matin (fil a8403146, 07:02 → 07:15) :
  · « simulation avant/après … garde tout le reste à l'identique » sur une
    photo jointe → le modèle a appelé `tester_visuel` avec un brief TEXTE :
    le moteur d'images n'a jamais VU la photo et a rendu une AUTRE maison ;
  · la retouche VALIDÉE par l'utilisateur est morte sur UN HTTP 503 de
    Google (« high demand ») — sans le moindre réessai, alors que le tirage
    final n'a qu'un seul moteur autorisé.

Ce banc prouve : le prédicat `demande_de_garder_la_photo` reconnaît la
demande de retouche, la garde de `tools_node` refuse l'essai texte quand le
fil porte une image (en nommant `modifier_visuel` et la clé), le catalogue le
dit aussi, et Nano Banana réessaie les statuts transitoires avant d'abandonner.
"""
import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
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
        elif isinstance(n, ast.Import) and any(
                (a.asname or a.name) in noms for a in n.names):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ PHOTO IDENTIQUE ET 503 — {BACKEND.resolve().parent}\n")

espace = extraire(BACKEND / "agents" / "annonce.py",
                  {"demande_de_garder_la_photo", "_RETOUCHE_LA_PHOTO",
                   "_sans_accent", "_ACCENTS", "re"}, {})
p = espace["demande_de_garder_la_photo"]
verifier("la demande EXACTE de prod est reconnue",
         p("Je joins une photo du jardin : fais une simulation avant/après en ajoutant "
           "ajoute une terrase bois devant les baie vitré, ajoute des bordures net autour "
           "du chemin et enlève les plantes sur le devant laisse que la pelouse plate "
           "Garde la maison et tout le reste à l’identique."))
verifier("« garde tout le reste à l'identique » est reconnu",
         p("Ajoute une pergola et garde tout le reste à l'identique."))
verifier("« avant/après » est reconnu", p("Fais une simulation avant/après."))
verifier("« sur cette photo » est reconnu", p("Ajoute une terrasse sur cette photo."))
verifier("une CRÉATION libre n'est pas reconnue",
         not p("Crée un visuel de jardin méditerranéen avec oliviers et graviers clairs."))
verifier("vide → faux", not p("") and not p(None))

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("la garde refuse l'essai TEXTE quand le fil porte une image à garder",
         re.search(r"action\[\"skill\"\] in \(\"tester_visuel\", \"generer_visuel\"\).*?"
                   r"cles_images_du_fil\(state\).*?demande_de_garder_la_photo.*?"
                   r"modifier_visuel", agent1, re.S))
verifier("le refus passe par SkillError : le modèle se corrige au tour suivant",
         "réinventerait" in agent1 and 'image="{cles[-1]}"' in agent1)

if (BACKEND / "skills" / "visuels.py").exists():
    visuels = (BACKEND / "skills" / "visuels.py").read_text(encoding="utf-8")
    verifier("le catalogue de tester_visuel dit : JAMAIS pour une photo existante",
             "JAMAIS pour transformer une PHOTO" in visuels
             and "AUTRE maison" in visuels)
    nano = (BACKEND / "visuels" / "nano_banana.py").read_text(encoding="utf-8")
    verifier("un statut transitoire (500/502/503/504) se réessaie avant d'abandonner",
             "in (500, 502, 503, 504)" in nano
             and re.search(r"for essai, pause_s in enumerate\(\(0, 5, 15\)\)", nano)
             and "await asyncio.sleep(pause_s)" in nano)
    verifier("la cause est DITE : surcharge passagère, pas un problème de crédit",
             "surcharge" in nano and "pas un problème de crédit" in nano)
    verifier("le 429 (quota) garde son traitement à part, hors réessais",
             "_diagnostic_429" in nano and "== 429" in nano)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
