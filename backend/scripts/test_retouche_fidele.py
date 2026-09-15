"""
Banc de LA RETOUCHE FIDÈLE À LA DEMANDE — export Langfuse du 15/09 (Symbiose,
fil d4864cdc, 16:23 → 17:11).

Relevé de Noa : « il a du mal à vraiment faire les modifications que je lui
demande ; des fois il fait bien et des fois non ». Quatre causes, lues tour par
tour :
  · 16:59 — photo + « en face du garage ça doit rester une allée en goudron,
    le gravier vient jusqu'au bâtiment. Garde le reste identique » : aucun verbe
    de la liste de passe de main, la vision a DÉCRIT le photomontage à faire et
    aucune image n'est sortie ;
  · 17:00 — « fais le rendu » : le forceur a préparé un visuel NEUF (questions
    de style) au lieu de retoucher la photo ; 17:02 — « fais une allée en
    goudron en face du garage… » : la photo remontrée, sans retouche ;
  · 17:07 — le moteur d'images ne recevait QUE la traduction anglaise écrite par
    un modèle qui n'a pas vu la photo : « Replace the gravel on the left side of
    the garage with gravel only, keep it as gravel » ;
  · le préréglage insistait tant sur « rien ne bouge » qu'une grande surface de
    sol changée restait timide.

CE QUE CE BANC PROUVE (fonctions du module livré EXÉCUTÉES) :
  · la vision passe la main sur les demandes exactes de prod, et quand elle
    annonce elle-même un photomontage ; une question reste à la vision ;
  · « fais le rendu », « fais une allée… », « refais un rendu… », « doit rester »
    sont des suites qui retouchent ; « fais le point sur mes mails » non ;
  · la demande d'origine accompagne la retouche (posée par le serveur, avant
    l'empreinte), une suite courte emporte les demandes précédentes ;
  · le préréglage porte les mots du client et exige des changements entiers ;
  · la garde refuse aussi `preparer_visuel` quand le fil porte une photo.

Usage : python backend/scripts/test_retouche_fidele.py [backend]
"""
import ast
import pathlib
import re
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
    gardes = []
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, ast.Assign) and any(isinstance(c, ast.Name) and c.id in noms for c in n.targets):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manque = [x for x in noms if x not in espace]
    assert not manque, f"absent du module livré : {manque}"
    return espace


print(f"\n═══ LA RETOUCHE FIDÈLE À LA DEMANDE — {BACKEND.parent}\n")

print("1. La vision passe la main quand on attend une image")
r = extraire(BACKEND / "agents" / "router.py",
             {"route_apres_agent2", "_SUITE_ATTENDUE", "_VISION_ANNONCE_UNE_RETOUCHE"}, {"AgentState": dict})["route_apres_agent2"]
Q_1659 = ("sur cette image, dans la continuété du batiment en face du garage ca doit rester une allée "
          "en goudron, le gravier viens jusqu'au batiment et se colle à l'allé en goudron. Garde le reste identique")
verifier("la demande exacte de 16:59 part chez l'assistant (qui retouche)",
         r({"query": Q_1659, "vision_analysis": "x", "vision_mode": "reponse"}) == "agent1")
verifier("la vision qui annonce elle-même un photomontage passe la main",
         r({"query": "voilà ce que je veux sur le sol", "vision_analysis": "x", "vision_mode": "reponse",
            "vision_reponse": "L'image fournie servira de base pour réaliser le photomontage."}) == "agent1")
verifier("une simple question sur la photo reste à la vision",
         r({"query": "c'est quoi cette plante ?", "vision_analysis": "x", "vision_mode": "reponse",
            "vision_reponse": "C'est un olivier."}) == "human_gate")

print("2. Les suites qui retouchent")
esp_a = {"re": re}
src_a = (BACKEND / "agents" / "annonce.py").read_text(encoding="utf-8")
exec(compile(src_a, "annonce", "exec"), esp_a)
sq = esp_a["suite_qui_retouche"]
for q in ("fais le rendu",
          "fais une allée en goudron en face du garage  de la largeur du garage avec une séparation nette avec le gravier.",
          "refais un rendu ou tu laisses que du gravier sur le coté gauche du garage",
          "le sol à droite du trait rouge doit rester identique"):
    verifier(f"« {q[:60]} » est une suite qui retouche", sq(q))
for q in ("fais le point sur mes mails de la semaine", "fais une recherche sur la berlinoise dans le devis"):
    verifier(f"« {q[:60]} » n'en est pas une", not sq(q))
verifier("« montre-moi le rendu » reste une demande de VOIR", esp_a["demande_de_montrer"]("montre-moi le rendu"))

print("3. La demande d'origine accompagne la retouche")
esp1 = extraire(BACKEND / "agents" / "agent1.py", {"_demande_de_retouche"}, {})
d = esp1["_demande_de_retouche"]


class H:
    type = "human"

    def __init__(self, c):
        self.content = c


class A:
    type = "ai"

    def __init__(self, c):
        self.content = c


Q_1707 = ("refais un rendu ou tu laisses que du gravier sur le coté gauche du garage et le goudron démarre "
          "que sur la face avant du garage et il fait que la largeur de la face avant du garage")
verifier("une demande détaillée part telle quelle", d({"query": Q_1707, "messages": [H("avant"), H(Q_1707)]}) == Q_1707)
dd = d({"query": "fais le rendu", "messages": [H("ajoute une piscine"), A("..."), H(Q_1659), A("..."), H("fais le rendu")]})
verifier("« fais le rendu » emporte les demandes précédentes du fil", "allée en goudron" in dd and dd.endswith("fais le rendu"), dd)
a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
i_inj = a1.find('args = {**args, "demande": demande_retouche}')
verifier("le serveur la pose AVANT l'empreinte (ce qui est validé est ce qui part)",
         0 < i_inj < a1.find("empreinte = hash_payload(action[\"skill\"], args)"))
verifier("la garde refuse aussi `preparer_visuel` quand le fil porte une photo",
         '("preparer_visuel", "tester_visuel", "generer_visuel")' in a1)

print("4. Le moteur d'images lit les mots du client, et applique tout")
vis = BACKEND / "skills" / "visuels.py"
if not vis.exists():
    print("  (pas de skills/visuels.py : la retouche est l'offre de Symbiose, contrôles sautés)")
else:
    esp_v = {"re": re}
    extraire(vis, {"PRESET_FIDELITE", "MAX_DEMANDE", "MAX_CHANGEMENTS"}, esp_v)
    prompt = esp_v["PRESET_FIDELITE"].format(changements="add a tarmac driveway", demande="« ICI »")
    verifier("les mots du client entrent dans le préréglage", "« ICI »" in prompt)
    verifier("chaque changement doit être appliqué EN ENTIER, à sa place", "APPLY EVERY REQUESTED CHANGE FULLY" in prompt)
    src_v = vis.read_text(encoding="utf-8")
    verifier("modifier_visuel lit `demande` et la dit « authority »",
             'data.get("demande")' in src_v and "this is the authority" in src_v)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
