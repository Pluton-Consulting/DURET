"""
Banc du TABLEAU JOINT — un Excel de 95 clients doit en donner 95, pas 30.

LE CAS (Symbiose, 03/09). Un fichier « tableau client entretien.xlsx » joint au
chat, avec la demande d'un mail personnalisé à chaque client. L'assistant en a
préparé 30. Trois causes empilées, aucune visible à l'écran :

  1. L'INVITE NE REPRODUISAIT QUE 40 LIGNES (`lignes[:40]`), avec une note qui
     renvoyait la personne vers l'écran d'import. Le modèle ne pouvait pas
     savoir ce qu'il y avait après la ligne 40.
  2. LE MODÈLE DEVAIT RECOPIER CHAQUE CLIENT dans son bloc ```action : sur 40
     lignes vues, il en a recopié 30 — un modèle qui recopie un mur de données
     s'arrête avant la fin, comme pour les transcriptions (`@message`).
  3. LES CELLULES SOUS UN EN-TÊTE VIDE ÉTAIENT JETÉES. Le fichier a huit
     colonnes nommées, puis — pour la moitié des lignes, collées depuis un
     autre export — l'adresse mail en colonne AG, sous un en-tête vide. Ces
     clients existaient SANS adresse : impossible de leur écrire.

CE QUE CE BANC PROUVE, le code livré EXÉCUTÉ sur un classeur doublé qui a la
forme du vrai : toutes les colonnes qui portent une valeur sont lues, l'adresse
est retrouvée où qu'elle soit, `{prenom}` se retrouve dans « Prénom », et les
lignes complètes voyagent jusqu'aux actions par `@tableau`. La lecture Excel
elle-même (openpyxl) est doublée : la bibliothèque n'est pas sur ce poste, et
ce n'est pas elle qu'on teste.
"""
import ast
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LE TABLEAU JOINT — {BACKEND.parent}\n")

# ── LE CLASSEUR DOUBLÉ : la forme exacte du fichier de Noa ────────────────
# Ligne 1 : huit en-têtes nommés (B..I), le reste vide. Lignes « anciennes » :
# l'adresse en I. Lignes « collées » : I vide, l'adresse en AG (indice 32),
# sous un en-tête VIDE, avec quarante colonnes d'export derrière.
ENTETES = [None, "Civilité", "Type de client", "Nom ?", "Prénom", "Ville", "Code postal",
           "Téléphone", "E-mail"] + [None] * 40
def _ancienne(i):
    return [None, "Mme", "Particulier", f"CLIENT{i}", f"Prenom{i}", "SALLES", "33770",
            "06 00 00 00 00", f"client{i}@exemple.fr"] + [None] * 40
def _collee(i):
    ligne = [None, "M.", None, f"COLLE{i}", f"Herve{i}", "TALENCE", "33400", "06 11 11 11 11", None]
    ligne += [None] * 23
    ligne += [f"herve{i}@gmail.com", "Client Particulier", "Saison 2023"] + [None] * 14
    return ligne
LIGNES = [ENTETES] + [_ancienne(i) for i in range(1, 51)] + [_collee(i) for i in range(1, 46)]
LIGNES.append([None] * 49)          # une ligne vide en fin de fichier : ignorée

class _Feuille:
    def iter_rows(self, values_only=True):
        for l in LIGNES:
            yield tuple(l)
class _Classeur:
    active = _Feuille()
    def close(self): pass
mod_openpyxl = types.ModuleType("openpyxl")
mod_openpyxl.load_workbook = lambda *a, **k: _Classeur()
sys.modules["openpyxl"] = mod_openpyxl

# ── 1. LA LECTURE EXCEL DU MODULE LIVRÉ ───────────────────────────────────
src_parsers = (BACKEND / "ingestion" / "parsers.py").read_text(encoding="utf-8")
arbre = ast.parse(src_parsers)
voulu = {"lire_excel", "_lettre_colonne", "MAX_LIGNES", "MAX_COLONNES", "FichierNonSupporte",
         "ligne_en_texte"}
gardes = [n for n in arbre.body
          if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in voulu)
          or (isinstance(n, ast.Assign) and any(isinstance(c, ast.Name) and c.id in voulu for c in n.targets))]
import io, logging
espace = {"io": io, "logger": logging.getLogger("banc")}
exec(compile(ast.fix_missing_locations(ast.Module(body=gardes, type_ignores=[])), "parsers", "exec"), espace)
verifier("`_lettre_colonne` existe et parle Excel",
         "_lettre_colonne" in espace and espace["_lettre_colonne"](0) == "A"
         and espace["_lettre_colonne"](25) == "Z" and espace["_lettre_colonne"](26) == "AA"
         and espace["_lettre_colonne"](32) == "AG")

entetes, lignes = espace["lire_excel"](b"peu importe")
verifier("TOUTES les lignes sont lues (95, pas 40, pas 30)", len(lignes) == 95, str(len(lignes)))
verifier("les cellules sous un en-tête VIDE ne sont plus jetées",
         any("Colonne AG" in l for l in lignes))
collee = next(l for l in lignes if l.get("Nom ?") == "COLLE1")
verifier("le client « collé » garde son adresse, en colonne AG",
         collee.get("Colonne AG") == "herve1@gmail.com", str(collee))
verifier("les colonnes découvertes entrent dans la liste des en-têtes",
         "Colonne AG" in entetes and "E-mail" in entetes)

# ── 2. LE PUBLIPOSTAGE RETROUVE L'ADRESSE ET LES VARIABLES ────────────────
src_pp = (BACKEND / "mail" / "publipostage.py").read_text(encoding="utf-8")
arbre = ast.parse(src_pp)
voulu = {"_ADRESSE", "_VARIABLE", "MANQUANT", "PAR_PAGE", "_plat", "_substituer",
         "_adresse_dans", "_normaliser", "construire_cartes"}
gardes = [n for n in arbre.body
          if (isinstance(n, ast.FunctionDef) and n.name in voulu)
          or (isinstance(n, ast.Assign) and any(isinstance(c, ast.Name) and c.id in voulu for c in n.targets))]
import re
espace_pp = {"re": re}
exec(compile(ast.fix_missing_locations(ast.Module(body=gardes, type_ignores=[])), "publipostage", "exec"), espace_pp)
normaliser = espace_pp["_normaliser"]
substituer = espace_pp["_substituer"]
dests = normaliser(lignes)
verifier("chaque ligne du tableau devient un destinataire", len(dests) == 95)
verifier("L'ADRESSE EST RETROUVÉE OÙ QU'ELLE SOIT : 95 adresses sur 95",
         sum(1 for d in dests if d.get("email")) == 95,
         f"{sum(1 for d in dests if d.get('email'))} adresses")
verifier("l'adresse d'un client « collé » vient bien de la colonne AG",
         next(d for d in dests if d.get("Nom ?") == "COLLE7")["email"] == "herve7@gmail.com")
verifier("`{prenom}` se retrouve dans « Prénom », `{nom}` dans « Nom ? »",
         substituer("Bonjour {prenom} {nom}", dests[0]) == "Bonjour Prenom1 CLIENT1")
verifier("une variable vraiment absente reste visible, jamais devinée",
         substituer("{societe}", dests[0]) == espace_pp["MANQUANT"])
verifier("une valeur qui contient une adresse mais n'en est pas la colonne n'est prise qu'à défaut",
         espace_pp["_adresse_dans"]({"note": "voir x@y.fr", "E-mail": "vrai@z.fr"}) == "vrai@z.fr")
r = espace_pp["construire_cartes"]("Objet {prenom}", "Bonjour {prenom}", lignes, page=1)
verifier("les cartes se construisent depuis les lignes BRUTES du tableau",
         r["nombre"] == 95 and len(r["cartes"]) == 95 and r["pages"] == 1)

# ── 3. LA CHAÎNE : de l'invite aux actions ────────────────────────────────
chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
verifier("l'invite ne s'arrête plus à 40 lignes : un budget de caractères, dit quand il coupe",
         "BUDGET_TABLEAU_INVITE" in chat and "lignes[:40]" not in chat
         and "faute de place" in chat)
verifier("l'invite apprend au modèle à passer `@tableau` plutôt que recopier",
         "@tableau" in chat and "ne les recopie jamais toi-même" in chat)
verifier("les lignes complètes accompagnent le tour (attachment_rows)",
         chat.count("attachment_rows=tableau_joint") == 2)
runtime = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
verifier("le tableau n'est posé que s'il y en a un — il SURVIT au tour suivant sinon",
         'if attachment_rows:\n        etat["dernier_tableau"] = attachment_rows' in runtime
         and '"dernier_tableau": None' not in runtime)
etat = (BACKEND / "agents" / "state.py").read_text(encoding="utf-8")
verifier("l'état connaît `dernier_tableau`", "dernier_tableau: Optional[dict]" in etat)
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le serveur remplace `@tableau` par les lignes, AVANT l'empreinte",
         "_est_jeton_tableau(v)" in agent1
         and agent1.find("_est_jeton_tableau(v)") < agent1.find('empreinte = hash_payload(action["skill"], args)'))
verifier("plusieurs écritures du jeton sont acceptées",
         '"@tableau"' in agent1 and '"@lignes"' in agent1 and '"@excel"' in agent1)
skills = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("`preparer_envois` dit quoi faire quand le jeton n'a trouvé aucun tableau",
         "Aucun tableau n'est joint" in skills)
verifier("son message d'erreur nomme `@tableau`", '`\\"@tableau\\"`' in skills)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
