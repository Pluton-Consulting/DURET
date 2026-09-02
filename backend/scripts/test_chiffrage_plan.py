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

# ── 2. LE RACCOURCI ──────────────────────────────────────────────────────
verifier("le raccourci « Chiffrer un plan » existe",
         'libelle: "Chiffrer un plan"' in raccourcis)
depart = raccourcis.find('libelle: "Chiffrer un plan"')
texte = raccourcis[depart:].split("` }")[0] if depart >= 0 else ""

verifier("PRINCIPE 1 — il impose SIX étapes séparées",
         "six étapes SÉPARÉES" in texte)
verifier("et il dit d'ignorer, à chaque étape, ce qui relève des autres "
         "(c'est ce qui évite de survoler)",
         "ignore ce qui relève des autres" in texte)
numeros = re.findall(r"\n(\d)\. [A-ZÉÈ]", texte)
verifier("les six étapes sont numérotées sans trou ni doublon",
         numeros == ["1", "2", "3", "4", "5", "6"], str(numeros))

verifier("étape 1 : la légende, et un ÉTALON désigné avec sa valeur",
         "ÉTALON" in texte and "donne sa valeur" in texte)
verifier("étape 2 : le balayage secteur par secteur",
         "nord-ouest" in texte and "sud-est" in texte)
verifier("étape 3 : chaque élément rattaché à une zone NOMMÉE de l'étape 2",
         "de l'étape 2, nommé" in texte)

verifier("PRINCIPE 3 — l'étape 4 impose la SOURCE de chaque quantité",
         "dis d'où elle vient" in texte)
for niveau, marque in (("cote lue", "cote lue sur le plan"),
                       ("déduction par proportion", "montre le calcul"),
                       ("estimation d'après l'étalon", "rappelle l'étalon"),
                       ("non mesurable", "n'avance aucun chiffre")):
    verifier(f"    · {niveau}", marque in texte)
verifier("les quatre niveaux sont donnés par ORDRE de préférence",
         "ordre de préférence" in texte)

verifier("étape 5 : ce qui coûte sans apparaître dans une surface",
         "sans apparaître dans une surface" in texte)
verifier("PRINCIPE 4 — l'étape 6 rend un tableau AVEC la fiabilité de chaque "
         "mesure",
         "fiabilité de la mesure" in texte)
verifier("elle dit ce qui manque et si le relevé est exploitable tel quel",
         "ce qui manque pour chiffrer" in texte and "exploitable tel quel" in texte)

# CE QUE LE CHIFFRAGE NE FAIT PAS. Un prix ne se déduit pas d'un plan : il
# vient des prix pratiqués par la maison (`prix_observes`), qui refuse déjà
# d'avancer un chiffre en dessous de deux observations. Un métré qui sortirait
# un prix contournerait ce garde-fou sans le dire.
verifier("aucun PRIX n'est demandé : le métré s'arrête aux quantités",
         "Ne donne aucun prix" in texte)

verifier("un tiret simple sert de puce, jamais un cadratin (même piège)",
         "—" not in texte and "–" not in texte)
verifier("il demande de joindre le plan", texte.count("Je joins un plan") == 1)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
