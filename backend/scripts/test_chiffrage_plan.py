"""
Banc « chiffrer un plan » — 02/09.

Demande de Noa : « fais un bouton action rapide du chat pour faire un chiffrage,
où ça donne un pré-prompt énorme que tu dois faire en t'inspirant du
fonctionnement de l'analyse du workflow que je te donne » (un workflow de métré
CVC multi-passes qui tourne en production chez un autre client).

CE QUE CE WORKFLOW FAIT, ET QUE NOUS NE FAISIONS PAS. Il découpe l'analyse en
six appels au modèle, un par sujet, chacun recevant le résultat des précédents.
On ne peut pas copier ce découpage tel quel : notre analyse tient en UN tour de
vision. Mais ses quatre principes se transposent, et ce sont eux qui font la
qualité du résultat :

  1. UNE MISSION PAR ÉTAPE, en ignorant explicitement le reste. Un modèle à qui
     l'on demande tout à la fois survole tout.
  2. LA LÉGENDE AVANT TOUT. Les conventions graphiques changent d'un bureau
     d'études à l'autre ; les supposer fausse tout ce qui suit, et l'erreur ne
     se voit pas — elle ressemble à une lecture.
  3. TOUTE MESURE DIT SA SOURCE, par fiabilité décroissante : cote lue,
     déduction par proportion, estimation d'après un étalon, non mesurable.
  4. LA SYNTHÈSE SE JUGE ELLE-MÊME : ce qui manque, ce qu'il faut vérifier, et
     si le relevé est exploitable tel quel. Sans ce verdict, une analyse
     partielle a exactement l'allure d'une analyse complète.

Les principes 2 et 4 manquaient au préprompt de vision ; ils y sont posés. Le
raccourci, lui, porte les six étapes.

Le banc lit les sources, sans base ni réseau. Il est IDENTIQUE des deux côtés :
seul le vocabulaire métier diffère, et il ne le contrôle pas.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.resolve().parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ CHIFFRER UN PLAN — {BACKEND.resolve().parent}\n")

vision = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
raccourcis = (FRONTEND / "lib" / "raccourcis.ts").read_text(encoding="utf-8")

# Le préprompt seul, sans les commentaires Python : c'est ce que le modèle LIT.
bloc = vision.split("VISION_PROMPT = (")[1].split("\n)")[0]
prompt = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', bloc))

# ── 1. LE PRÉPROMPT DE VISION : les deux principes qui manquaient ────────
verifier("le préprompt travaille désormais en CINQ temps", "CINQ temps" in prompt)
etapes = re.findall(r"(\d)\. [A-ZÉÈ]", prompt)
verifier("les cinq étapes sont numérotées sans trou ni doublon",
         etapes == ["1", "2", "3", "4", "5"], str(etapes))

def avant(gauche, droite, texte):
    """`gauche` précède `droite` dans `texte`, et les deux y sont.

    Un `.index()` nu lèverait sur la version d'avant, où la légende n'existe
    pas : un banc doit ÉCHOUER, pas planter — sinon les contrôles suivants ne
    sont jamais joués et l'on ne sait pas ce qui manque vraiment.
    """
    a, b = texte.find(gauche), texte.find(droite)
    return a >= 0 and b >= 0 and a < b


verifier("PRINCIPE 2 — la légende passe en PREMIER, avant tout inventaire",
         avant("CARTOUCHE ET LÉGENDE", "INVENTAIRE", prompt))
verifier("et elle prime sur toute convention supposée (elle varie d'un "
         "bureau d'études à l'autre)",
         "PRIME sur toute convention" in prompt)
verifier("une légende absente se DIT, elle ne se devine pas",
         "Si elle est absente" in prompt)
verifier("l'inventaire se fait par BALAYAGE de zones, pas au fil de l'œil",
         "BALAIE LE PLAN ZONE PAR ZONE" in prompt)
verifier("PRINCIPE 4 — l'analyse se juge elle-même : ce qui manque est dit",
         "TERMINE par un verdict" in prompt and "ce qui MANQUE" in prompt)
verifier("et elle dit si elle est exploitable telle quelle",
         "exploitable tel quel" in prompt)

# Les trois régimes de mesure (posés le 01/09) ne devaient pas être perdus.
for regime in ("LUE", "ESTIMÉE", "NON MESURABLE"):
    verifier(f"le régime de mesure « {regime} » tient toujours", regime in prompt)

# LE PIÈGE TYPOGRAPHIQUE, PAYÉ UNE FOIS EN RECETTE (27/08). Le prompt interdit
# au modèle le tiret cadratin, et il en contenait un lui-même depuis toujours —
# un modèle imite ce qu'il LIT au moins autant qu'il suit ce qu'on lui dit. Le
# contrôle porte sur TOUT le prompt, pas seulement sur les ajouts du jour : une
# règle qu'on s'applique à soi-même est la seule qui tienne.
cadratins = [m.group(0) for m in re.finditer(r".{30}[—–].{30}", prompt)]
verifier("le préprompt n'emploie pas le tiret cadratin qu'il interdit",
         not cadratins, " | ".join(cadratins))

# ── 2. LE RACCOURCI — RETIRÉ DU MENU LE 24/09 ───────────────────────────
# Le menu éclair est devenu le cahier des 19 prompts de Duret (demande de Noa) ;
# le prompt de chiffrage en six passes n'y a plus de bouton. Il vit dans
# l'historique git (lib/raccourcis.ts avant le 24/09) si l'on veut le remettre.
verifier("le menu éclair ne porte plus le chiffrage en six passes (cahier des 19 prompts)",
         'libelle: "Chiffrer un plan"' not in raccourcis and raccourcis.count(", libelle: ") == 19)

# ── 3. MESURER SUR UNE PHOTO ─────────────────────────────────────────────
# UN PLAN EST À L'ÉCHELLE PARTOUT, UNE PHOTO NE L'EST NULLE PART. Sans les
# règles ci-dessous, le modèle rend des mètres carrés avec l'aplomb qu'il
# aurait sur un plan coté : le chiffrage part alors sur des quantités fausses
# que rien ne signale. C'est le pire cas, pire qu'un refus de mesurer.
verifier("le préprompt traite la mesure SUR PHOTO à part",
         "SUR UNE PHOTO, l'échelle se construit autrement" in prompt)
verifier("l'étalon doit être NOMMÉ, pas seulement utilisé",
         "NOMME-le" in prompt)
verifier("RÉFLEXE 1 — compter un motif répété plutôt qu'estimer une longueur",
         "COMPTE PLUTÔT QUE D'ESTIMER" in prompt)
verifier("et l'exemple montre le calcul, pas seulement la consigne",
         "font 9 m" in prompt or "font 1,95 m" in prompt)
verifier("RÉFLEXE 2 — les trois limites se DISENT, elles ne se taisent pas",
         "à DIRE, jamais à taire" in prompt)
for limite, marque in (
        ("ce qui fuit vers le fond est sous-estimé", "FUIT vers le fond"),
        ("l'étalon ne vaut qu'à sa propre distance", "à la MÊME distance que lui"),
        ("le biais et le grand angle déforment", "grand angle")):
    verifier(f"    · {limite}", marque in prompt)
verifier("sur photo, la fourchette s'élargit et on dit pourquoi",
         "élargis la fourchette et dis pourquoi" in prompt)

verifier("le recalage photo/plan est demandé AVANT toute comparaison",
         avant("dis D'ABORD d'où la photo est prise", "répartis", prompt))
verifier("chacun son rôle : le plan dit les DIMENSIONS",
         "pour les DIMENSIONS, le plan fait foi" in prompt)
verifier("la photo dit l'ÉTAT", "pour l'ÉTAT réel" in prompt)
verifier("ce que l'un montre et que l'autre ignore est signalé (c'est ce "
         "qui coûte)",
         "est justement ce " in prompt and "qui coûte : signale-le" in prompt)
verifier("une contradiction entre photo et plan se dit EN CLAIR",
         "CONTRADICTION" in prompt and "se dit en clair" in prompt)

# 24/09 : le raccourci « Mesurer d'après une photo » a quitté le menu avec les autres
# (le menu éclair est le cahier des 19 prompts) ; ses six étapes vivent dans l'historique git.
verifier("le menu ne porte plus « Mesurer d'après une photo »",
         "libelle: \"Mesurer d'après une photo\"" not in raccourcis)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
