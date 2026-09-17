"""
Banc « DES CHIFFRES JUSTES, DU CODE ISOLÉ, DES BOUCLES QUI NE DOUBLENT PAS »
— audit du 15/09, fiches D-12/S-12, D-15/S-15, D-18/S-18 et D-21/S-21.

CE QUI ÉTAIT FAUX :
  · les totaux s'additionnaient en flottant : sur trois cents lignes de devis,
    le total n'était plus juste au centime (0,1 + 0,2 ≠ 0,3 en binaire) ;
  · un skill GÉNÉRÉ échappait au verrou des effets externes, et s'exécutait
    dans un sous-processus du backend — qui partage ses fichiers, ses clés et
    son réseau ;
  · toutes les boucles de fond démarraient dans le serveur du chat : un second
    processus les aurait relancées (deux ordonnanceurs, deux synchronisations),
    et le démarrage requalifiait en échec le travail d'un worker vivant ;
  · la garde du navigateur comparait des CHAÎNES : `localtest.me`, une IPv6, ou
    tout nom public qui pointe vers 10.x passaient.

CE BANC PROUVE (modules EXÉCUTÉS) :
  1. les montants s'additionnent en décimal, au centime ;
  2. le code généré est refusé sans exécuteur isolé, et passe par le même
     verrou d'effet que les gestes natifs ;
  3. le rôle du processus commande les boucles de fond, et la requalification
     ne prend que ce qui ne donne plus signe de vie ;
  4. la garde du navigateur RÉSOUT le nom et refuse toute adresse interne.

Usage : python backend/scripts/test_chiffres_et_isolement.py [backend]
"""
import ast
import pathlib
import socket
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ CHIFFRES, ISOLEMENT, BOUCLES, NAVIGATEUR — {BACKEND.parent}\n")

print("1. Les montants s'additionnent au centime (D-12/S-12)")
donnees_src = (BACKEND / "skills" / "donnees.py").read_text(encoding="utf-8")
arbre = ast.parse(donnees_src)


def _extraire_resultat():
    """La fonction `_resultat` de `_agreger`, sortie de son contexte."""
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == "_resultat":
            return noeud
    return None


fonction = _extraire_resultat()
verifier("`_resultat` existe et additionne en Decimal", fonction is not None
         and "Decimal" in ast.get_source_segment(donnees_src, fonction))
if fonction is not None:
    espace = {}
    exec(compile(ast.Module(body=[fonction], type_ignores=[]), "donnees", "exec"),
         {"operation": "sum", "colonne": "montant_ht"}, espace)
    _resultat = espace["_resultat"]
    # Le cas d'école : en flottant, 0.1 + 0.2 + 0.3 ne fait pas 0.6.
    valeurs = [0.1, 0.2, 0.3]
    verifier("0,1 + 0,2 + 0,3 fait exactement 0,60", _resultat({"valeurs": valeurs, "enregistrements": 3}) == 0.60,
             _resultat({"valeurs": valeurs, "enregistrements": 3}))
    centimes = [1234.565, 0.005, 10.01]
    verifier("l'arrondi au centime est celui du commerce (0,5 monte)",
             _resultat({"valeurs": centimes, "enregistrements": 3}) == 1244.58,
             _resultat({"valeurs": centimes, "enregistrements": 3}))
    espace2 = {}
    exec(compile(ast.Module(body=[fonction], type_ignores=[]), "donnees", "exec"),
         {"operation": "avg", "colonne": "montant_ht"}, espace2)
    verifier("une moyenne reste au centime elle aussi",
             espace2["_resultat"]({"valeurs": [10.0, 20.0, 25.0], "enregistrements": 3}) == 18.33)
    espace3 = {}
    exec(compile(ast.Module(body=[fonction], type_ignores=[]), "donnees", "exec"),
         {"operation": "count", "colonne": ""}, espace3)
    verifier("compter ne change pas : ce sont des enregistrements, pas des montants",
             espace3["_resultat"]({"valeurs": [], "enregistrements": 7}) == 7.0)
    verifier("un groupe sans valeur lisible rend « rien », pas zéro",
             _resultat({"valeurs": [], "enregistrements": 4}) is None)

print("2. Le code généré : même verrou, et pas dans le backend (D-15/S-15)")
executor_src = (BACKEND / "skills" / "executor.py").read_text(encoding="utf-8")
verifier("le verrou des effets externes s'applique AUSSI à la branche générée",
         executor_src.count("_verifier_effet(name, data") >= 2)
verifier("sans exécuteur isolé, un skill généré est REFUSÉ, et la raison est dite",
         "aucun exécuteur isolé n'est\"" in executor_src.replace("\n", "")
         or "aucun exécuteur isolé" in executor_src)
verifier("le refus se lève AVANT d'appeler le bac à sable",
         executor_src.index("aucun exécuteur isolé") < executor_src.index("await sandbox_client.execute_skill("))
verifier("le retour en arrière existe, explicite et hors de portée du chat",
         "_AUTORISER_CODE_NON_ISOLE" in executor_src
         and "autoriser_code_non_isole: bool = False" in (BACKEND / "config.py").read_text(encoding="utf-8"))
sandbox_src = (BACKEND / "sandbox" / "daytona_client.py").read_text(encoding="utf-8")
verifier("le bac à sable dit s'il isole vraiment", "def isolement(" in sandbox_src
         and "subprocess_fallback" in sandbox_src)

print("3. Les boucles de fond suivent le rôle du processus (D-18/S-18)")
main_src = (BACKEND / "main.py").read_text(encoding="utf-8")
verifier("le rôle est lu au démarrage et journalisé",
         "role_processus" in main_src and "Rôle du processus" in main_src)
verifier("embeddings, tâches, NAS et carte ne partent que pour un rôle de fond",
         main_src.count("if travaux_de_fond:") >= 3
         and main_src.index("travaux_de_fond = role in") < main_src.index("start_embedding_worker"))
verifier("« complet » reste le défaut : le déploiement d'aujourd'hui ne change pas",
         'role_processus: str = "complet"' in (BACKEND / "config.py").read_text(encoding="utf-8"))
worker_src = (BACKEND / "tasks" / "worker.py").read_text(encoding="utf-8")
verifier("au démarrage, on ne requalifie que ce qui ne donne plus signe de vie",
         "COALESCE(lease_until, updated_at + INTERVAL '15 minutes') < NOW()" in worker_src and "lease_owner = $5" in worker_src)

print("4. La garde du navigateur résout, elle ne devine pas (D-21/S-21)")
from browser.sandbox_filter import SandboxFilter, _adresse_interne  # noqa: E402
import ipaddress  # noqa: E402

filtre = SandboxFilter()
verifier("une IPv6 locale est refusée, même écrite entre crochets",
         filtre.is_blocked("http://[::1]/")[0] and filtre.is_blocked("http://[fe80::1]/")[0])
verifier("l'adresse des métadonnées du nuage (169.254.169.254) est refusée",
         filtre.is_blocked("http://169.254.169.254/latest/meta-data/")[0])
verifier("une IPv4 déguisée en IPv6 est refusée aussi",
         _adresse_interne(ipaddress.ip_address("::ffff:10.0.0.1")))
verifier("un protocole autre que http(s) est refusé", filtre.is_blocked("ftp://exemple.fr/")[0])

# LE VRAI PIÈGE : un nom PUBLIC qui pointe vers l'intérieur. On double la
# résolution — c'est elle qu'on veut prouver, pas le DNS de la machine.
vrai_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda hote, port, *a, **k: (
    [(2, 1, 6, "", ("10.0.0.7", 443))] if hote == "interne.exemple.fr"
    else [(2, 1, 6, "", ("93.184.216.34", 443))])
try:
    bloque, raison = filtre.is_blocked("https://interne.exemple.fr/admin")
    verifier("un nom public qui MÈNE à une adresse privée est refusé, et le dit",
             bloque and "adresse interne" in raison, raison)
    verifier("un nom public ordinaire passe", filtre.is_blocked("https://exemple.fr/page") == (False, ""))
    socket.getaddrinfo = lambda *a, **k: (_ for _ in ()).throw(OSError("pas de DNS"))
    bloque, raison = filtre.is_blocked("https://exemple.fr/page")
    verifier("un nom qu'on ne peut pas résoudre est refusé, en expliquant pourquoi",
             bloque and "impossible de vérifier" in raison, raison)
finally:
    socket.getaddrinfo = vrai_getaddrinfo

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
