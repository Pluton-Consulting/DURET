"""
Banc des JOURNAUX — aucune clé ne doit s'y retrouver.

Relevé le 27/08 en lisant `docker compose logs backend` : la clé Google
s'affichait EN CLAIR, dans l'URL d'une requête journalisée par httpx en INFO.
Aucune ligne du projet ne l'écrivait — c'est la bibliothèque HTTP qui recopiait
l'adresse complète, et les API Google portent la clé dans la query string.
N'importe qui ouvrant les journaux, ou en postant une capture d'écran, la
récupérait.

Ce banc exerce le filtre sur les formes réellement rencontrées : la clé dans une
URL, un en-tête d'autorisation, un dictionnaire de configuration, et une clé
passée en argument de log (`%s`) — celle-là échappe à tout filtre qui ne
regarderait que le message.

Il vérifie aussi que le filtre n'abîme PAS les journaux ordinaires : un filtre
trop gourmand qui masquerait des mots courants rendrait les traces illisibles,
et on le désactiverait au premier incident.

Ni base, ni réseau : on charge le filtre depuis main.py par AST.

  python3 scripts/test_secrets_journaux.py backend
"""
import sys, ast, logging, pathlib, re

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
SOURCE = pathlib.Path(BACKEND) / "main.py"

VERT, ROUGE, GRIS, RAZ = "\x1b[92m", "\x1b[91m", "\x1b[90m", "\x1b[0m"
echecs = 0


def controle(titre, ok, detail=""):
    global echecs
    if ok:
        print(f"  {VERT}✓{RAZ} {titre}")
    else:
        echecs += 1
        print(f"  {ROUGE}✗{RAZ} {titre}" + (f"{GRIS} — {detail}{RAZ}" if detail else ""))


# On prend du module livré la seule partie qui nous intéresse : le motif, la
# fonction de masquage et la classe de filtre. Importer main.py entier tirerait
# FastAPI, la base et le graphe.
arbre = ast.parse(SOURCE.read_text(encoding="utf-8"))
espace = {"logging": logging, "_re_logs": re}
VOULUS = {"_SECRETS", "_masquer", "_FiltreSecrets"}
pris = set()
for n in arbre.body:
    nom = None
    if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
        nom = n.name
    elif isinstance(n, ast.Assign):
        for c in n.targets:
            if isinstance(c, ast.Name) and c.id in VOULUS:
                nom = c.id
    if nom in VOULUS:
        exec(compile(ast.Module([n], []), str(SOURCE), "exec"), espace)
        pris.add(nom)

manquants = VOULUS - pris
if manquants:
    print(f"{ROUGE}Absent de main.py : {', '.join(sorted(manquants))}{RAZ}")
    sys.exit(1)

masquer = espace["_masquer"]
Filtre = espace["_FiltreSecrets"]

# La clé d'exemple a la FORME d'une vraie (longueur, alphabet) mais chaque
# caractère est fabriqué pour le banc : une clé réelle ici serait précisément
# la fuite que ce banc interdit — et GitHub (push protection) la bloquerait.
CLE = "AA.Banc0faux0jeton0fabrique0pour0le0banc0de0test0XYZ999"

print("\n\x1b[1mAUCUNE CLÉ DANS LES JOURNAUX\x1b[0m\n")

url = f"HTTP Request: POST https://generativelanguage.googleapis.com/v1beta/models/x:batchEmbedContents?key={CLE} \"HTTP/1.1 429\""
sortie = masquer(url)
controle("la clé d'une URL est masquée", CLE not in sortie, sortie[-70:])
controle("les six derniers caractères restent, pour identifier la clé",
         "XYZ999" in sortie, sortie[-40:])
controle("le reste de la ligne est intact",
         "429" in sortie and "batchEmbedContents" in sortie)

for forme, texte in (
    ("api_key=", f"appel avec api_key={CLE}"),
    ("token=", f"redirect?token={CLE}&next=/"),
    ("en JSON", f'{{"api_key": "{CLE}"}}'),
    ("password", f"password={CLE}"),
    ("encodé %3D", f"key%3D{CLE}"),
):
    controle(f"masquée sous la forme {forme}", CLE not in masquer(texte), masquer(texte)[:60])

# LE PIÈGE : une clé passée en ARGUMENT, pas dans le message.
enregistrement = logging.LogRecord("x", logging.INFO, "f", 1,
                                   "appel vers %s", (f"https://api/x?key={CLE}",), None)
Filtre().filter(enregistrement)
controle("une clé passée en argument (%s) est masquée elle aussi",
         CLE not in str(enregistrement.args), str(enregistrement.args)[-60:])

# Et ce qui ne doit PAS bouger.
for ordinaire in (
    "Runtime LangGraph initialise",
    "Historique VIDE alors que le fil porte 12 messages",
    "GET /api/file/etat HTTP/1.1 200 OK",
    "client: BARRIER Jean-Pierre, montant: 2092.80",
):
    controle(f"journal ordinaire intact : « {ordinaire[:38]}… »",
             masquer(ordinaire) == ordinaire, masquer(ordinaire))

controle("un mot court après « key= » n'est pas masqué (pas un secret)",
         masquer("key=abc") == "key=abc", masquer("key=abc"))

print()
if echecs:
    print(f"{ROUGE}{echecs} contrôle(s) en échec.{RAZ}")
    sys.exit(1)
print(f"{VERT}Tous les contrôles passent.{RAZ}")
