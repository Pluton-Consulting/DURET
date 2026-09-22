"""
Banc du FRAGMENT TROP DENSE — le quantitatif qui échouait huit fois (22/09).

Relevé en production chez Duret : un CCTP de revêtements porte plus de 120
faits utiles dans un fragment de 18 000 caractères. Le modèle, sommé de
regrouper sans rien perdre, ne pouvait pas ; `_json` levait « 120 faits
maximum par fragment » après deux essais, et le travail repartait toutes les
quinze minutes, huit fois, sans jamais aboutir.

CE QUE CE BANC PROUVE (sans réseau, modèle doublé) :
  · un fragment qui passe au premier coup passe EXACTEMENT comme avant :
    un seul appel, la même consigne, l'étape partielle rangée ;
  · un fragment trop dense est lu en deux moitiés, les numéros de lignes de
    la seconde recalés sur le fragment entier, toutes les étapes partielles
    rendues pour être effacées ;
  · une autre erreur ne déclenche AUCUN découpage (elle remonte telle quelle) ;
  · la profondeur est bornée.

Usage : python backend/scripts/test_fragment_dense.py [backend]
"""
import asyncio
import pathlib
import sys

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, ok):
    print(("  ✓ " if ok else "  ✗ ") + nom)
    if not ok:
        echecs.append(nom)


try:
    import skills.documents_dossier as dd
except Exception as e:  # noqa: BLE001
    print(f"SKIP : module inimportable ici ({type(e).__name__}: {e})")
    sys.exit(0)

verifier("`_analyse_du_fragment` et `_deux_moities` existent",
         hasattr(dd, "_analyse_du_fragment") and hasattr(dd, "_deux_moities"))
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)

# — doublures : étapes en mémoire, réparation neutre, modèle programmé
etapes = {}


class Dossiers:
    TAILLE_FRAGMENT = 18000

    @staticmethod
    def etape(uid, fil, tache, cle, valeur=None):
        if valeur is None:
            return etapes.get(cle)
        etapes[cle] = valeur


async def reparer(r, texte):
    return r


appels = []


def programme(regle):
    async def faux_json(consigne, donnees, verifier=None, *, extraction=False):
        lignes = donnees["texte_numerote"]
        appels.append((consigne, donnees["fragment"], len(lignes)))
        return regle(lignes)
    return faux_json


dd.dossiers = Dossiers
dd._reparer_citations = reparer
TEXTE = "".join(f"Ligne {i} : revêtement PVC, local {i}, 12 m²\n" for i in range(1, 401))  # ~17 000 car.


def trop(lignes):
    if len(lignes) > 250:
        raise ValueError("Réponse documentaire non vérifiable après deux essais ; étapes précédentes conservées. "
                         "Le résultat précédent était invalide : 120 faits maximum par fragment.")
    return {"faits": [{"fait": "f", "ligne_debut": 1, "ligne_fin": 1},
                      {"fait": "g", "ligne_debut": len(lignes), "ligne_fin": len(lignes)}], "limites": ["l"]}


print("— un fragment ordinaire : rien ne change")
etapes.clear(); appels.clear()
dd._json = programme(lambda lignes: {"faits": [{"fait": "x", "ligne_debut": 2, "ligne_fin": 3}], "limites": []})
r, cles = asyncio.run(dd._analyse_du_fragment("demande", "CCTP.pdf", 3, TEXTE, "u", "f", "t", "analyse_partielle:s:3"))
verifier("un seul appel", len(appels) == 1)
verifier("la consigne est celle du module", appels[0][0] is dd.CONSIGNE_ANALYSE)
verifier("les faits sont rendus tels quels", r["faits"] == [{"fait": "x", "ligne_debut": 2, "ligne_fin": 3}])
verifier("l'étape partielle est rangée puis rendue à effacer",
         "analyse_partielle:s:3" in etapes and cles == ["analyse_partielle:s:3"])

print("— un fragment trop dense : lu en deux moitiés")
etapes.clear(); appels.clear()
dd._json = programme(trop)
r, cles = asyncio.run(dd._analyse_du_fragment("demande", "CCTP.pdf", 3, TEXTE, "u", "f", "t", "analyse_partielle:s:3"))
verifier("trois appels : l'entier refusé, puis chaque moitié", len(appels) == 3)
verifier("les moitiés sont numérotées 3.1 et 3.2", [a[1] for a in appels[1:]] == ["3.1", "3.2"])
moitie1, moitie2 = dd._deux_moities(TEXTE)
n1 = len(moitie1.splitlines())
verifier("les deux moitiés font le fragment entier", moitie1 + moitie2 == TEXTE)
verifier("quatre faits, deux par moitié", len(r["faits"]) == 4)
verifier("les lignes de la seconde moitié sont recalées sur le fragment",
         r["faits"][2]["ligne_debut"] == 1 + n1 and r["faits"][3]["ligne_fin"] == len(TEXTE.splitlines()))
verifier("la citation recalée désigne la même ligne",
         TEXTE.splitlines()[r["faits"][2]["ligne_debut"] - 1] == moitie2.splitlines()[0])
verifier("les limites des deux moitiés sont gardées", r["limites"] == ["l", "l"])
verifier("toutes les étapes partielles sont rendues à effacer",
         set(cles) == {"analyse_partielle:s:3", "analyse_partielle:s:3.1", "analyse_partielle:s:3.2"})

print("— une autre erreur ne découpe rien")
etapes.clear(); appels.clear()


def autre(lignes):
    raise ValueError("Citations absentes du fragment")


dd._json = programme(autre)
try:
    asyncio.run(dd._analyse_du_fragment("demande", "CCTP.pdf", 1, TEXTE, "u", "f", "t", "p"))
    verifier("l'erreur remonte", False)
except ValueError as e:
    verifier("l'erreur remonte telle quelle, un seul appel", "Citations absentes" in str(e) and len(appels) == 1)

print("— la profondeur est bornée")
etapes.clear(); appels.clear()


def toujours_trop(lignes):
    raise ValueError("120 faits maximum par fragment.")


dd._json = programme(toujours_trop)
try:
    asyncio.run(dd._analyse_du_fragment("demande", "CCTP.pdf", 1, TEXTE, "u", "f", "t", "p"))
    verifier("l'échec finit par remonter", False)
except ValueError:
    verifier("l'échec remonte dès la première moitié qui échoue : trois appels, pas de boucle", len(appels) == 3)
verifier("un texte court ne se coupe pas", dd._deux_moities("court\n" * 10) is None)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
