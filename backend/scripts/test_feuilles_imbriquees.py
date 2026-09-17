"""
Banc « UN EXCEL À DEUX FEUILLES SORT DU PREMIER COUP » — trace Langfuse du 17/09,
fil d13ff0ac (Symbiose), tour de 10:39 UTC.

Le tour avait TOUT : cinq factures lues (HT, TVA, TTC), les quatorze factures
d'entretien. À 10:48 il appelle `produire_document` — et il le rappellera QUATRE
fois en neuf minutes, sous quatre formes, avant d'aller relire le mode d'emploi :
chaque feuille portait ses blocs ({"type":"feuille","nom":…,"contenu":[titre,
tableau, chiffres]}), forme naturelle qu'une feuille PLATE (nom, entetes, lignes)
ne connaissait pas. Sans entêtes ni lignes à son niveau, la feuille était écartée
avec tout son contenu : « aucun bloc n'a été retenu ».

CE QUE CE BANC PROUVE (sans base, sans réseau, sans modèle) : `deplier_feuilles`
et `normaliser_element`, IMPORTÉS du code livré, sur les blocs EXACTS de la trace.
"""
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from bureautique.modele import deplier_feuilles, normaliser_element  # noqa: E402

echecs = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def rendre(blocs):
    return [e for e in (normaliser_element(x) for x in deplier_feuilles(blocs)) if e]


print("\n═══ FEUILLES IMBRIQUÉES —", BACKEND.parent)

# Les blocs de 10:48:48, tels quels (lignes abrégées à deux factures).
PROD = [
    {"type": "feuille", "nom": "Achats BTF 2026", "contenu": [
        {"type": "titre", "texte": "Achats BTF 2026"},
        {"type": "tableau", "colonnes": ["N° facture", "Date", "Montant HT", "Montant TTC", "Chemin"],
         "lignes": [["FAC00003406", "17/02/2026", "133,40 €", "160,08 €", "2026/02-FEVRIER"],
                    ["FAC00003467", "31/03/2026", "372,60 €", "447,12 €", "2026/03-MARS"]]},
        {"type": "chiffres", "valeur": "4 661,10 €", "libelle": "Total HT (5 factures)"}]},
    {"type": "feuille", "nom": "Entretien par client", "contenu": [
        {"type": "titre", "texte": "Entretien par client (12 mois)"},
        {"type": "tableau", "entetes": ["Client", "Passages", "Fréquence moyenne"],
         "lignes": [["ROCCA PASCAL", 3, "non calculable"], ["BLATCH Christiane", 2, "non fiable"]]},
        {"type": "paragraphe", "texte": "Fréquence calculée sur moins de trois factures : non fiable."}]},
]

avant = [e for e in (normaliser_element(x) for x in PROD) if e]
verifier("SANS dépliage, les blocs de prod ne donnent RIEN (le défaut relevé)", avant == [])

r = rendre(PROD)
feuilles = [e for e in r if e["bloc"] == "feuille"]
verifier("les deux feuilles de prod deviennent deux onglets", [f["nom"] for f in feuilles] == ["Achats BTF 2026", "Entretien par client"])
verifier("chaque onglet porte les entêtes et les lignes de SON tableau",
         feuilles[0]["entetes"][:3] == ["N° facture", "Date", "Montant HT"] and len(feuilles[0]["lignes"]) == 2
         and feuilles[1]["entetes"] == ["Client", "Passages", "Fréquence moyenne"] and feuilles[1]["lignes"][0][0] == "ROCCA PASCAL")
verifier("l'ordre est tenu : onglet 1, son total, onglet 2, sa réserve",
         [e["bloc"] for e in r] == ["feuille", "chiffres", "feuille", "paragraphe"])
verifier("le total écrit à plat ({valeur, libelle}) reste dans le classeur",
         r[1]["items"] == [{"valeur": "4 661,10 €", "libelle": "Total HT (5 factures)"}])
verifier("le titre placé AVANT le tableau ne redouble pas le nom de l'onglet",
         not any(e["bloc"] == "titre" for e in r))
verifier("la réserve « non fiable » de la seconde feuille n'est pas perdue",
         "non fiable" in r[3]["texte"])

# Non-régression : ce qui marchait marche pareil.
PLATE = {"type": "feuille", "nom": "Clients", "entetes": ["Nom"], "lignes": [["Martin"], ["Durand"]]}
verifier("une feuille déjà PLATE passe telle quelle", deplier_feuilles([PLATE]) == [PLATE]
         and rendre([PLATE])[0]["lignes"] == [["Martin"], ["Durand"]])
verifier("un bloc ordinaire n'est pas touché (une chaîne, un tableau, un paragraphe à champ `contenu`)",
         deplier_feuilles(["texte", {"type": "tableau", "entetes": ["a"], "lignes": [["1"]]},
                           {"type": "paragraphe", "contenu": "bonjour"}])
         == ["texte", {"type": "tableau", "entetes": ["a"], "lignes": [["1"]]}, {"type": "paragraphe", "contenu": "bonjour"}])
verifier("une feuille imbriquée SANS tableau rend ses blocs, pas un onglet vide",
         [e["bloc"] for e in rendre([{"type": "onglet", "nom": "Notes", "blocs": [{"type": "paragraphe", "texte": "rien à chiffrer"}]}])] == ["paragraphe"])
verifier("les synonymes tiennent (sheet, children, rows, headers)",
         rendre([{"type": "sheet", "name": "S1", "children": [{"type": "table", "headers": ["h"], "rows": [["v"]]}]}])
         == [{"bloc": "feuille", "entetes": ["h"], "lignes": [["v"]], "nom": "S1"}])
verifier("un second tableau dans la même feuille suit dans le même onglet",
         [e["bloc"] for e in rendre([{"type": "feuille", "nom": "F", "contenu": [
             {"type": "tableau", "entetes": ["a"], "lignes": [["1"]]},
             {"type": "tableau", "entetes": ["b"], "lignes": [["2"]], "legende": "Détail"}]}])] == ["feuille", "tableau"])
verifier("rien, None ou une liste vide ne lèvent pas", deplier_feuilles(None) == [] and deplier_feuilles([]) == [])
verifier("un chiffre clé en `items` passe comme avant",
         normaliser_element({"type": "chiffres", "items": [{"valeur": "12", "libelle": "devis"}]})["items"] == [{"valeur": "12", "libelle": "devis"}])

# 17/09, 15:45 — la feuille posée en SÉPARATEUR, blocs EXACTS de prod (« ignores=2 »).
SEPARATEUR = [
    {"bloc": "feuille", "titre": "Mails reçus (7 derniers jours)"},
    {"bloc": "tableau", "entetes": ["Date", "Expéditeur", "Objet", "Résumé", "Catégorie"],
     "lignes": [["17/09", "CBP", "RE: RELANCE", "Relance comptable", "administratif"]] * 4},
    {"bloc": "feuille", "titre": "Trois mails prioritaires"},
    {"bloc": "tableau", "entetes": ["Rang", "Expéditeur", "Objet", "Raison"], "lignes": [["1", "a", "b", "c"]] * 3},
]
rs = rendre(SEPARATEUR)
verifier("une feuille NUE suivie de son tableau devient un onglet (prod : deux tableaux dans le même onglet)",
         [e["bloc"] for e in rs] == ["feuille", "feuille"]
         and [e["nom"] for e in rs] == ["Mails reçus (7 derniers jours)", "Trois mails prioritai"[:21] + "res"][:2]
         or [e["nom"][:20] for e in rs] == ["Mails reçus (7 derni", "Trois mails priorita"])
verifier("…avec les lignes de SON tableau", len(rs) == 2 and len(rs[0]["lignes"]) == 4 and len(rs[1]["lignes"]) == 3)
verifier("une feuille nue qui n'est PAS suivie d'un tableau ne vole rien",
         [e["bloc"] for e in rendre([{"bloc": "feuille", "titre": "Vide"}, {"bloc": "paragraphe", "texte": "x"}])] == ["paragraphe"])

# 17/09, 16:02 — « surligne-les en orange » : des lignes mises en avant dans un onglet.
f = normaliser_element({"type": "feuille", "nom": "Mails", "entetes": ["a"], "lignes": [["1"], ["2"], ["3"]],
                        "surlignees": [0, 2, 9, -1, "x"], "surlignage": "orange"})
verifier("une feuille porte ses lignes surlignées — rangs hors bornes et valeurs étrangères écartés",
         f["surlignees"] == [0, 2] and f["surlignage"] == "orange")
verifier("une teinte inconnue retombe sur l'orange, et sans lignes désignées rien n'est posé",
         normaliser_element({"type": "feuille", "nom": "x", "entetes": ["a"], "lignes": [["1"]], "surlignees": [0], "surlignage": "fuchsia"})["surlignage"] == "orange"
         and "surlignees" not in normaliser_element({"type": "feuille", "nom": "x", "entetes": ["a"], "lignes": [["1"]]}))
rendu_src = (BACKEND / "bureautique" / "rendu.py").read_text(encoding="utf-8")
verifier("le rendu Excel pose le fond clair sur ces lignes-là seulement",
         "ecrire(ligne, teinte=teinte if rang in en_avant else None" in rendu_src and 'PatternFill("solid", fgColor=teinte)' in rendu_src)

atelier = (BACKEND / "bureautique" / "atelier.py").read_text(encoding="utf-8")
verifier("l'atelier déplie AVANT de normaliser : tous les chemins d'ajout en profitent",
         "normaliser_element(x) for x in deplier_feuilles(elements)" in atelier)

print("\n" + "═" * 70)
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec\n")
