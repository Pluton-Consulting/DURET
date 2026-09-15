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

(16/09, audit D-22) Il vérifie EN PLUS ce que l'audit a trouvé : le filtre était
posé sur le seul logger RACINE, par lequel les enregistrements des autres
loggers ne passent pas — ils remontent vers ses HANDLERS. Et une exception
(`exc_info`) sort par le formateur, jamais par `msg`.

Ni base, ni réseau : le masquage vit dans `security/secrets.py`, chargé tel quel.

  python3 scripts/test_secrets_journaux.py backend
"""
import sys, importlib.util, io, logging, pathlib

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
SOURCE = pathlib.Path(BACKEND) / "security" / "secrets.py"

VERT, ROUGE, GRIS, RAZ = "\x1b[92m", "\x1b[91m", "\x1b[90m", "\x1b[0m"
echecs = 0


def controle(titre, ok, detail=""):
    global echecs
    if ok:
        print(f"  {VERT}✓{RAZ} {titre}")
    else:
        echecs += 1
        print(f"  {ROUGE}✗{RAZ} {titre}" + (f"{GRIS} — {detail}{RAZ}" if detail else ""))


# Le module livré, chargé tel quel : il ne dépend que de `logging` et `re`.
spec = importlib.util.spec_from_file_location("security_secrets_double", SOURCE)
secrets_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secrets_module)
masquer = secrets_module.masquer
Filtre = secrets_module.FiltreSecrets

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

# ── LE FILTRE EST-IL POSÉ LÀ OÙ LES ENREGISTREMENTS PASSENT ? (audit D-22) ──
print("\n\x1b[1mLE FILTRE COUVRE TOUT CE QUI S'ÉCRIT\x1b[0m\n")
tampon = io.StringIO()
handler = logging.StreamHandler(tampon)
handler.setFormatter(logging.Formatter("%(message)s"))
racine = logging.getLogger("banc_secrets")
racine.handlers = [handler]
racine.propagate = False
racine.setLevel(logging.INFO)
enfant = logging.getLogger("banc_secrets.mail.envoi")
secrets_module.poser_filtre(racine)
def ecrit():
    """Ce qui vient d'être écrit dans le journal (et remet le tampon à zéro)."""
    texte = tampon.getvalue()
    tampon.truncate(0)
    tampon.seek(0)
    return texte


enfant.info("appel vers https://api/x?key=%s", CLE)
controle("un journal d'un logger ENFANT est masqué (il ne passe pas par les filtres du parent)",
         CLE not in (sortie := ecrit()), sortie[-70:])
# LE PIÈGE : le secret n'est ni dans le message ni dans l'argument — il n'existe
# qu'une fois les deux réunis.
enfant.info("clé refusée : key=%s", CLE)
controle("un secret coupé entre le message et son argument est masqué au recollage",
         CLE not in (sortie := ecrit()) and "XYZ999" in sortie, sortie[-70:])
try:
    raise RuntimeError(f"échec de l'appel avec api_key={CLE}")
except RuntimeError:
    enfant.exception("l'appel a échoué")
sortie = ecrit()
controle("la TRACE d'une exception est masquée elle aussi", CLE not in sortie, sortie[-90:])
controle("le reste de la trace reste lisible", "RuntimeError" in sortie)
principal = (pathlib.Path(BACKEND) / "main.py").read_text(encoding="utf-8")
controle("le serveur pose le filtre sur les handlers, et le repose au démarrage",
         principal.count("_poser_filtre_secrets()") >= 2)
langfuse = (pathlib.Path(BACKEND) / "observability" / "langfuse_client.py").read_text(encoding="utf-8")
controle("les traces exportées passent par le même masquage",
         "from security.secrets import masquer_arbre" in langfuse and "masquer_arbre(walk(data))" in langfuse)
controle("le masque des traces ne promet plus ce qu'il ne fait pas",
         "AUCUNE PII ne quitte le système" not in langfuse)
arbre_masque = secrets_module.masquer_arbre(
    {"prompt": f"clé api_key={CLE}", "liste": [f"token={CLE}"], "nombre": 12})
controle("le masquage descend dans les structures (état du graphe, métadonnées)",
         CLE not in str(arbre_masque) and arbre_masque["nombre"] == 12, arbre_masque)

print()
if echecs:
    print(f"{ROUGE}{echecs} contrôle(s) en échec.{RAZ}")
    sys.exit(1)
print(f"{VERT}Tous les contrôles passent.{RAZ}")
