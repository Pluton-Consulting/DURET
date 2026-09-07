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
                  {"demande_de_garder_la_photo", "_RETOUCHE_LA_PHOTO", "demande_un_visuel",
                   "_DEMANDE_VISUEL", "_sans_accent", "_ACCENTS", "re"}, {})
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

pv = espace.get("demande_un_visuel")
verifier("le prédicat `demande_un_visuel` existe", callable(pv))
if callable(pv):
    verifier("la demande de simulation EXACTE de prod est un visuel demandé",
             pv("Je joins une photo du jardin : fais une simulation avant/après en "
                "ajoutant supprime les plantes du jardin. Garde la maison et tout le "
                "reste à l'identique."))
    verifier("« fais une image d'une maison moderne » est un visuel demandé",
             pv("Fais une image d'une maison moderne sur le bassin d'Arcachon."))
    verifier("« décris-moi la maison » n'en est pas un", not pv("Décris-moi la maison."))

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("la garde refuse l'essai TEXTE quand le fil porte une image à garder",
         re.search(r"action\[\"skill\"\] in \(\"tester_visuel\", \"generer_visuel\"\).*?"
                   r"cles_images_du_fil\(state\).*?demande_de_garder_la_photo.*?"
                   r"modifier_visuel", agent1, re.S))
verifier("le refus passe par SkillError : le modèle se corrige au tour suivant",
         "réinventerait" in agent1 and 'image="{cles[-1]}"' in agent1)
verifier("le fantôme couvre les VISUELS : une simulation demandée sans image produite force",
         # 03/09 : le visuel REMONTRÉ depuis le fil (vraie clé) n'est plus un
         # fantôme ; la demande sans image produite l'est toujours.
         # 07/09 soir : la remontrance n'exempte plus que si on a demandé de VOIR
         # (`remontre_a_bon_droit` = demande_de_montrer + photo du fil).
         "or (demande_un_visuel(demande) and \"?\" not in visible" in agent1
         and "and not remontre_a_bon_droit)" in agent1
         and "remontre_a_bon_droit = (demande_de_montrer(demande)" in agent1)

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

# ══════════════════════════════════════════════════════════════════════════
# « FAIS-LA UN PEU PLUS HAUTE » — la suite qui ne répète pas son objet (07/09)
# ══════════════════════════════════════════════════════════════════════════
# Relevé par Noa sur deux tours consécutifs (16:52 et 16:53) : « remplace la
# piscine en coque par une piscine maçonnée hors sol de 65 cm » puis « fais-la
# un peu plus haute ». Le premier n'a rendu AUCUNE réponse finale, le second a
# été interrompu à la main. Ni `demande_de_garder_la_photo` (qui veut les mots
# de la fidélité) ni `demande_un_visuel` (qui veut les mots de l'image) ne
# voient ces phrases : une suite de conversation ne répète pas son objet.
print("\n── La suite qui retouche, sans dire quoi")

import unicodedata as _ud
_src_annonce = (BACKEND / "agents" / "annonce.py").read_text(encoding="utf-8")
_d = _src_annonce.index("_MODIFIE_SANS_DIRE_QUOI")
_f = _src_annonce.index("# ── Le point sur les mails")
_esp = {"re": re,
        "_sans_accent": lambda s: "".join(
            c for c in _ud.normalize("NFD", s or "") if _ud.category(c) != "Mn").lower()}
exec(compile(_src_annonce[_d:_f], "annonce.py", "exec"), _esp)
suite_qui_retouche = _esp["suite_qui_retouche"]

verifier("LES DEUX TOURS DU 07/09 sont reconnus comme des retouches",
         suite_qui_retouche("fais la un plus haute")
         and suite_qui_retouche("fais la un peu plus haute")
         and suite_qui_retouche(
             "Je voudrais reprendre sur le photo montage et faire une dernière "
             "version, je souhaite que tu remplace la piscine en coque par une "
             "piscine maçonnée hors sol de 65cm et de couleur blanche pour "
             "l'extérieur, margelle en travertin,"))
verifier("un comparatif, un verbe de changement ou une couleur suffisent",
         suite_qui_retouche("mets la en blanc")
         and suite_qui_retouche("agrandis la")
         and suite_qui_retouche("un peu moins foncé"))
verifier("une modification qui NOMME un autre livrable n'est pas une retouche",
         not suite_qui_retouche("remplace la ligne 3 du devis")
         and not suite_qui_retouche("change le titre du document")
         and not suite_qui_retouche("ajoute une colonne avec mon mail"))
verifier("une demande sans modification n'est pas une retouche",
         not suite_qui_retouche("fais le point sur mes mails")
         and not suite_qui_retouche("bonjour") and not suite_qui_retouche(""))
verifier("une longue demande, qui dit son objet, est laissée aux autres prédicats",
         not suite_qui_retouche("change " + "x" * 320))

_a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le prédicat NE DÉCIDE JAMAIS SEUL : une image du fil est exigée",
         "cles and (demande_de_garder_la_photo(demande)" in _a1
         and "or suite_qui_retouche(demande))" in _a1
         and "and cles_images_du_fil(state)" in _a1)
verifier("un essai depuis un TEXTE est refusé, et le refus nomme `modifier_visuel`",
         "modifier_visuel" in _a1.split("suite_qui_retouche(demande))")[1][:600])
verifier("un tour qui ne produit RIEN sur une telle suite part au forceur",
         'or (suite_qui_retouche(demande)' in _a1)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
