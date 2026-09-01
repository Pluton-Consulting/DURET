"""
Banc « un export Excel ne fait qu'UNE feuille » — 01/09 nuit.

Relevé de Noa : « à chaque fois que je demande des Excel, il me fait toujours
deux feuilles : une feuille avec un titre qui est inutile et une autre feuille
avec les vraies infos. Je comprends pas, deux feuilles c'est inutile. »

LA CAUSE. `_xlsx` ouvrait d'office une feuille au nom du titre et n'y écrivait
que ce titre ; ensuite, CHAQUE bloc `feuille` du document créait la sienne. Or
tous les exports de listes (`liste_clients fichier: true`, `liste_fournisseurs`,
la recherche documentaire en fichier) produisent exactement un bloc `feuille` :
le classeur sortait donc systématiquement avec un onglet vide devant.

CE QUE CE BANC EXIGE. La feuille d'accueil ne s'ouvre QUE si quelque chose y va.
Un document fait uniquement de blocs `feuille` n'en a plus ; un document fait de
tableaux et de paragraphes la garde (sinon il n'aurait aucun onglet) ; et un
document VIDE en garde une, parce qu'un classeur sans feuille est un fichier
qu'Excel refuse d'ouvrir.

`openpyxl` n'est pas installé hors du conteneur : le classeur est DOUBLÉ ici,
assez fidèlement pour que la logique de `_xlsx` s'exécute pour de vrai.
"""
import ast
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


# ── Le classeur doublé ───────────────────────────────────────────────────
class _Cell:
    def __init__(self):
        self.value = None
        self.font = None
        self.fill = None
        self.alignment = None


class _Zone:
    def __init__(self):
        self.text = ""


class _Bandeau:
    def __init__(self):
        self.right = _Zone()
        self.center = _Zone()
        self.left = _Zone()


class _Feuille:
    def __init__(self, titre):
        self.title = titre
        self.cases = {}
        self.oddHeader = _Bandeau()
        self.oddFooter = _Bandeau()
        self.freeze_panes = None
        self.column_dimensions = _Dimensions()

    def cell(self, row=1, column=1, value=None):
        c = self.cases.setdefault((row, column), _Cell())
        if value is not None:
            c.value = value
        return c

    @property
    def max_row(self):
        return max((r for r, _ in self.cases), default=1)

    @property
    def max_column(self):
        return max((c for _, c in self.cases), default=1)

    def valeurs(self):
        return [c.value for c in self.cases.values() if c.value not in (None, "")]


class _Workbook:
    def __init__(self):
        self.active = _Feuille("Feuil1")
        self.worksheets = [self.active]

    def remove(self, f):
        self.worksheets.remove(f)

    def create_sheet(self, titre):
        f = _Feuille(titre)
        self.worksheets.append(f)
        return f

    def save(self, chemin):
        self.sauve = chemin


class _Dim:
    """`column_dimensions[lettre]` se crée à la volée chez openpyxl."""
    width = 10


class _Dimensions(dict):
    def __missing__(self, cle):
        self[cle] = _Dim()
        return self[cle]


def _fabrique_modules():
    op = types.ModuleType("openpyxl")
    op.Workbook = _Workbook
    styles = types.ModuleType("openpyxl.styles")
    styles.Alignment = lambda **k: k
    styles.Font = lambda **k: k
    styles.PatternFill = lambda *a, **k: k
    utils = types.ModuleType("openpyxl.utils")
    utils.get_column_letter = lambda n: chr(64 + n)
    op.styles, op.utils = styles, utils
    modele = types.ModuleType("bureautique.modele")
    modele.MAX_FEUILLES = 20
    modele.COULEURS = {}
    modele.TAILLES = {}
    paquet = types.ModuleType("bureautique")
    paquet.__path__ = []
    return {"openpyxl": op, "openpyxl.styles": styles, "openpyxl.utils": utils,
            "bureautique": paquet, "bureautique.modele": modele}


sys.modules.update(_fabrique_modules())

# `_xlsx` est extraite du module livré : le reste de `rendu.py` importe des
# bibliothèques de PDF absentes ici.
arbre = ast.parse((BACKEND / "bureautique" / "rendu.py").read_text(encoding="utf-8"))
noeud = next(n for n in arbre.body
             if isinstance(n, ast.FunctionDef) and n.name == "_xlsx")
espace = {}
exec(compile(ast.Module(body=[noeud], type_ignores=[]), "rendu", "exec"), espace)
_xlsx = espace["_xlsx"]

# Les feuilles créées sont récupérées en interceptant `create_sheet`.
_creees: list = []
_vrai_create = _Workbook.create_sheet


def _espionne(self, titre):
    f = _vrai_create(self, titre)
    _creees.append(f)
    return f


_Workbook.create_sheet = _espionne
ENTETE = {"titre": "Liste des clients", "entete": "", "pied": "", "numeroter": False}


def rendre(elements):
    _creees.clear()
    _xlsx(ENTETE, elements, "/tmp/faux.xlsx")
    return list(_creees)


print(f"\n═══ UN EXPORT EXCEL NE FAIT QU'UNE FEUILLE — {BACKEND.resolve().parent}\n")

# ── 1. LE CAS DE NOA : un export de liste ────────────────────────────────
feuilles = rendre([{"bloc": "feuille", "nom": "Clients",
                    "entetes": ["Nom", "E-mail"],
                    "lignes": [["Dupont", "a@b.fr"], ["Martin", "c@d.fr"]]}])
verifier("un export de liste ne rend QU'UNE feuille",
         len(feuilles) == 1, f"{len(feuilles)} : {[f.title for f in feuilles]}")
verifier("et c'est celle des données, pas celle du titre",
         feuilles and feuilles[0].title == "Clients", feuilles[0].title if feuilles else "")
verifier("le titre du document ne s'y invite pas en première ligne",
         feuilles and feuilles[0].cell(row=1, column=1).value == "Nom")
verifier("les données sont bien là",
         feuilles and "Dupont" in feuilles[0].valeurs()
         and "c@d.fr" in feuilles[0].valeurs())

# ── 2. Plusieurs listes : une feuille chacune, toujours pas de titre ─────
feuilles = rendre([
    {"bloc": "feuille", "nom": "Clients", "entetes": ["Nom"], "lignes": [["A"]]},
    {"bloc": "feuille", "nom": "Fournisseurs", "entetes": ["Nom"], "lignes": [["B"]]},
])
verifier("deux listes → deux feuilles, sans onglet de titre",
         [f.title for f in feuilles] == ["Clients", "Fournisseurs"],
         str([f.title for f in feuilles]))

# ── 3. Un document ordinaire garde SA feuille — sinon il n'en aurait aucune ──
feuilles = rendre([
    {"bloc": "titre", "texte": "Récapitulatif", "niveau": 1},
    {"bloc": "tableau", "legende": "", "entetes": ["Poste", "Montant"],
     "lignes": [["Terrasse", "1200"]]},
])
verifier("un document de tableaux et de titres garde une feuille",
         len(feuilles) == 1, str([f.title for f in feuilles]))
verifier("elle porte le titre du document, et son contenu",
         feuilles and feuilles[0].cell(row=1, column=1).value == "Liste des clients"
         and "Terrasse" in feuilles[0].valeurs())

# ── 4. Un mélange : la note SUIT la liste, elle n'ouvre pas d'onglet ─────
# Comportement voulu, et il va dans le sens de la demande : ouvrir un onglet
# « Liste des clients » ne contenant qu'une note de bas serait exactement le
# genre de feuille inutile qu'on vient de supprimer.
feuilles = rendre([
    {"bloc": "feuille", "nom": "Données", "entetes": ["A"], "lignes": [["1"]]},
    {"bloc": "titre", "texte": "Note de bas", "niveau": 2},
])
verifier("une note qui suit une liste s'écrit À LA SUITE, sans nouvel onglet",
         [f.title for f in feuilles] == ["Données"],
         str([f.title for f in feuilles]))
verifier("et la note est bien dans la feuille des données",
         feuilles and "Note de bas" in feuilles[0].valeurs())

# ── 5. Un document VIDE reste ouvrable ───────────────────────────────────
feuilles = rendre([])
verifier("un document vide garde UNE feuille (un classeur sans feuille ne s'ouvre pas)",
         len(feuilles) == 1, str([f.title for f in feuilles]))

# ── 6. La règle, lue dans le source ──────────────────────────────────────
src = (BACKEND / "bureautique" / "rendu.py").read_text(encoding="utf-8")
verifier("la feuille d'accueil est PARESSEUSE, et le code dit pourquoi",
         "def garantir()" in src and "SEULEMENT si quelque chose y va" in src)
verifier("plus aucune ouverture d'office avant la boucle",
         "nouvelle(entete[\"titre\"])\n    ecrire(" not in src)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
