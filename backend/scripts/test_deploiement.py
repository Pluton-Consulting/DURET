"""
Banc « SAUVEGARDER, LIVRER, RESTAURER » — audit du 15/09, fiches D-23/S-23, D-26/S-26, D-00/S-00.

CE QUI ÉTAIT FAUX :
  · `backup.sh` ne sauvait que la base et le `.env`. Les Word et Excel rendus,
    les VISUELS et le dossier des secrets des connecteurs restaient dehors :
    une base restaurée citait des fichiers qui n'existaient plus ;
  · `deploy.sh` démarrait TOUT, puis migrait — et une migration en échec était
    signalée pendant que la livraison continuait. Sur une base déjà en service
    au suivi vide, il marquait toutes les migrations « appliquées » sans
    regarder si leurs objets existaient : une migration manquée le restait ;
  · `/api/health` répondait « ok » avec un schéma incomplet, une base
    injoignable ou la mémoire des conversations en mode volatil.

CE BANC PROUVE, sans Docker ni base :
  1. la readiness EXÉCUTÉE contre des doublures : schéma incomplet, base
     muette, checkpointer volatil → pas prêt, et la cause est dite ; tout bon
     → prêt, avec le commit livré ;
  2. l'ORDRE du déploiement (construire, sauvegarder, base, migrer, vérifier,
     basculer, attendre) et le fait qu'un échec de migration ARRÊTE ;
  3. la ligne de base vérifiée : chaque migration du disque a son objet
     attendu, et les migrations de permissions ne se rejouent pas à l'aveugle ;
  4. la sauvegarde couvre base + volumes + secrets, vérifie avant de publier,
     et ne purge qu'après ;
  5. la restauration refuse la production, coupe toute sortie, et nomme les
     quatre objets à rouvrir.

Usage : python backend/scripts/test_deploiement.py [backend]
"""
import asyncio
import importlib.util
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
sys.path.insert(0,str(BACKEND))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ SAUVEGARDER, LIVRER, RESTAURER — {RACINE}\n")

print("1. Vivant n'est pas prêt : la readiness, exécutée")
# On prend de `main.py` les seules fonctions d'état : l'importer en entier
# tirerait FastAPI, le graphe et la base.
import ast

source = (BACKEND / "main.py").read_text(encoding="utf-8")
arbre = ast.parse(source)
voulus = {"version_livree", "_etat_du_service"}
morceaux = [n for n in arbre.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in voulus]
verifier("main.py porte la version livrée et l'état du service", len(morceaux) == 2, [n.name for n in morceaux])

MIGRATIONS = sorted(f.name for f in (BACKEND / "database" / "migrations").glob("[0-9]*.sql"))
ETAT = {"suivies": list(MIGRATIONS), "base_muette": False, "checkpointer": "AsyncPostgresSaver"}


class _Conn:
    async def fetchval(self, *a):
        if ETAT["base_muette"]:
            raise RuntimeError("connexion refusée")
        return 1

    async def fetch(self, *a):
        return [{"filename": n} for n in ETAT["suivies"]]


class _Db:
    async def __aenter__(self):
        if ETAT["base_muette"]:
            raise RuntimeError("connexion refusée")
        return _Conn()

    async def __aexit__(self, *a):
        return False


async def _checkpointer():
    return type(ETAT["checkpointer"], (), {})()


espace = {"__file__": str(BACKEND / "main.py")}
sys.modules["database"] = types.ModuleType("database")
sys.modules["database.connection"] = types.SimpleNamespace(get_db=lambda: _Db())
sys.modules["agents"] = types.ModuleType("agents")
sys.modules["agents.checkpointer"] = types.SimpleNamespace(get_checkpointer=_checkpointer)
async def _graphe(): return object()
sys.modules["agents.runtime"] = types.SimpleNamespace(get_graph=_graphe)
exec(compile(ast.Module(body=morceaux, type_ignores=[]), "main", "exec"), espace)
etat = asyncio.run(espace["_etat_du_service"]())
verifier("tout est en place → PRÊT", etat["pret"] and etat["schema"] and etat["base"] and etat["checkpointer"], etat)

ETAT["suivies"] = MIGRATIONS[:-2]
etat = asyncio.run(espace["_etat_du_service"]())
verifier("une migration du disque non appliquée → PAS prêt, et elle est NOMMÉE",
         not etat["pret"] and etat["manquantes"] == MIGRATIONS[-2:], etat.get("manquantes"))
ETAT["suivies"] = list(MIGRATIONS)
ETAT["checkpointer"] = "MemorySaver"
etat = asyncio.run(espace["_etat_du_service"]())
verifier("checkpointer volatil (la mémoire des conversations ne survit pas) → PAS prêt",
         not etat["pret"] and etat["checkpointer"] is False and etat["checkpointer_type"] == "MemorySaver", etat)
ETAT["checkpointer"] = "AsyncPostgresSaver"
ETAT["base_muette"] = True
etat = asyncio.run(espace["_etat_du_service"]())
verifier("base injoignable → PAS prêt, la raison est dite",
         not etat["pret"] and not etat["base"] and etat.get("erreur_base"), etat)
ETAT["base_muette"] = False
verifier("la readiness rend 503 tant que ça manque, la liveness ne parle que du processus",
         'status_code=200 if etat["pret"] else 503' in source
         and '"""LIVENESS : le processus répond. Ne dit RIEN de la base ni du schéma."""' in source)
verifier("le commit livré est rendu par les deux (on sait quelle version tourne)",
         "**version_livree()" in source and '"version": version_livree()' in source)

print("2. L'ordre du déploiement, et ce qui l'arrête")
deploy = (RACINE / "deploy.sh").read_text(encoding="utf-8")
etapes = [deploy.index(m) for m in ("==> 1/7  Version livrée", "==> 2/7  Construction des images",
                                    "==> 3/7  Sauvegarde", "==> 4/7  Base de données seule",
                                    "==> 5/7  Migrations", "==> 6/7  Bascule de l'application",
                                    "==> 7/7  L'application se déclare-t-elle PRÊTE")]
verifier("construire → sauvegarder → base → migrer → basculer → attendre la readiness",
         etapes == sorted(etapes))
verifier("la bascule vient APRÈS les migrations (avant, on démarrait tout puis on migrait)",
         deploy.index("$COMPOSE up -d\n") > deploy.index("==> 5/7  Migrations"))
verifier("une migration en échec ARRÊTE la livraison (elle ne « sera pas retentée plus tard »)",
         "LIVRAISON ARRÊTÉE" in deploy and "sera retentée au prochain deploy" not in deploy
         and deploy.count("exit 1") >= 4)
verifier("une sauvegarde ratée arrête aussi, et le contournement est explicite",
         "la sauvegarde a échoué — livraison arrêtée" in deploy and "SAUVEGARDE_AVANT=0" in deploy)
verifier("le schéma est vérifié complet avant la bascule",
         "migrations non appliquées" in deploy and "schéma complet" in deploy)
verifier("la readiness est attendue, et un échec dit le RETOUR ARRIÈRE",
         "/api/ready" in deploy and "RETOUR ARRIÈRE" in deploy)
# Le `.gitignore` peut vivre à la racine du PROJET (Duret) ou un cran au-dessus,
# à la racine du DÉPÔT (Symbiose, dont le projet est un sous-dossier).
def _ignore() -> str:
    for candidat in (RACINE / ".gitignore", RACINE.parent / ".gitignore"):
        if candidat.exists():
            return candidat.read_text(encoding="utf-8")
    return ""


verifier("le commit livré est écrit pour l'application, et jamais versionné",
         "backend/.version" in deploy and "backend/.version" in _ignore())

print("3. La ligne de base : vérifiée, jamais devinée")
attendus = {}
for ligne in (BACKEND / "database" / "migrations" / "attendus.tsv").read_text(encoding="utf-8").splitlines():
    if ligne.startswith("#") or "\t" not in ligne:
        continue
    nom, requete = ligne.split("\t", 1)
    attendus[nom.strip()] = requete.strip()
verifier("chaque migration du disque a son objet attendu (aucune oubliée)",
         set(MIGRATIONS) == set(attendus), sorted(set(MIGRATIONS) ^ set(attendus)))
verifier("les requêtes de contrôle sont des LECTURES, jamais des écritures",
         all(r.lower().startswith("select") and not any(mot in r.lower() for mot in
             (" insert ", " update ", " delete ", " drop ", " alter "))
             for r in attendus.values()))
verifier("le marquage ne dit plus « la base existe donc tout est appliqué »",
         "migrations jouées par un ancien deploy" not in deploy
         and "objet ABSENT → elle sera jouée" in deploy and "attendus.tsv" in deploy)

print("4. La sauvegarde : base, fichiers, secrets — vérifiée avant d'être publiée")
backup = (RACINE / "backup.sh").read_text(encoding="utf-8")
verifier("elle prend la base, le volume des documents (visuels compris) et les secrets",
         "pg_dump" in backup and "documents_produits" in backup and "backend/secrets" in backup)
verifier("un volume de documents introuvable ARRÊTE la sauvegarde (elle ne ment pas)",
         "introuvable" in backup and "n'est pas restaurable telle quelle" in backup)
verifier("elle écrit dans un dossier provisoire et ne publie qu'après contrôle",
         ".en-cours_" in backup and "gzip -t" in backup and "tar tzf" in backup
         and "sha256sum -c" in backup and backup.index("sha256sum -c") < backup.index('mv "$TMP" "$CIBLE"'))
verifier("le manifeste dit le commit, les migrations et les comptes",
         "commit du code" in backup and "migrations en base" in backup and "comptes" in backup)
verifier("les secrets sont chiffrables, et les fichiers privés (umask 077)",
         "umask 077" in backup and "BACKUP_PASSPHRASE" in backup and "openssl enc" in backup)
verifier("la purge ne tourne QU'APRÈS publication, et garde toujours les derniers jeux",
         backup.index("GARDER_AU_MOINS") < backup.index("Rétention")
         and backup.index('mv "$TMP" "$CIBLE"') < backup.rindex("rm -rf \"$jeu\""))
verifier("une copie hors de la machine est prévue, et son échec ne perd pas le jeu local",
         "BACKUP_DISTANT" in backup and "le jeu local, lui, est complet" in backup)

print("4 bis. La sauvegarde, EXÉCUTÉE (docker doublé)")
import os
import shutil
import subprocess
import tempfile

atelier = pathlib.Path(tempfile.mkdtemp(prefix="banc-sauvegarde-"))
faux_bin = atelier / "bin"
faux_bin.mkdir()
(faux_bin / "docker").write_text("""#!/usr/bin/env bash
# `docker` doublé : la base rend un dump, le volume rend une archive.
set -euo pipefail
if [ -n "${BANC_OPERATIONS:-}" ]; then
  echo "$*" >> "$BANC_OPERATIONS"
  case "${1:-}" in
    ps) case "$*" in *service=backend*) echo "backend-fictif";; esac; exit 0;;
    stop|start) exit 0;;
  esac
fi
if [ "${1:-}" = "volume" ] && [ "${2:-}" = "inspect" ]; then
  case "$3" in *_documents_produits) exit 0;; *) exit 1;; esac
fi
if [ "${1:-}" = "run" ]; then
  sortie=""; fichier=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -v) case "$2" in *:/sortie) sortie="${2%%:*}";; esac; shift;;
      czf) fichier="$2"; shift;;
    esac
    shift
  done
  atelier="$(mktemp -d)"
  printf 'un devis rendu' > "$atelier/devis.docx"
  tar czf "$sortie/$(basename "$fichier")" -C "$atelier" .
  exit 0
fi
if [ "${1:-}" = "compose" ]; then
  for a in "$@"; do
    case "$a" in
      config) echo '{"name":"duret-sols","services":{"postgres":{"environment":{"POSTGRES_USER":"duret_user","POSTGRES_DB":"duret_sols"}}}}'; exit 0;;
      pg_dump) [ "${BANC_DUMP_ECHOUE:-0}" = "0" ] || exit 9; echo "-- dump de la base"; echo "CREATE TABLE users();"; exit 0;;
      psql) echo "001_initial_schema.sql 043_lecons.sql"; exit 0;;
    esac
  done
fi
exit 0
""", encoding="utf-8")
# Un projet fictif distinct par banc évite la collision de deux recettes parallèles.
(faux_bin / "docker").write_text((faux_bin / "docker").read_text().replace("duret-sols", atelier.name))
(faux_bin / "docker").chmod(0o755)

projet = atelier / "projet"
shutil.copytree(RACINE, projet, ignore=shutil.ignore_patterns(
    "node_modules", ".next", ".git", "frontend", "*.pyc", "__pycache__"))
(projet / ".env").write_text("POSTGRES_USER=duret_user\nPOSTGRES_DB=duret_sols\nCOMPOSE_PROJECT_NAME=duret-sols\n"
                             "GOOGLE_API_KEY=faux\n", encoding="utf-8")
(projet / "backend" / "secrets").mkdir(parents=True, exist_ok=True)
(projet / "backend" / "secrets" / "site_credentials.json").write_text("{}", encoding="utf-8")
depot = atelier / "sauvegardes"
milieu = {**os.environ, "PATH": f"{faux_bin}:{os.environ['PATH']}", "BACKUP_DIR": str(depot),
          "GARDER_AU_MOINS": "1", "RETENTION_DAYS": "0"}
lance = subprocess.run(["bash", "backup.sh"], cwd=projet, env=milieu, capture_output=True, text=True)
verifier("backup.sh va au bout et publie un jeu", lance.returncode == 0, lance.stderr[-300:])
import re as _re
_m = _re.search(r'CIBLE="\$BACKUP_DIR/([A-Za-z0-9_-]+)_\$STAMP"', backup)
PREFIXE = _m.group(1) if _m else "jeu"
verifier("les jeux portent un préfixe lisible dans backup.sh", bool(_m), backup[:200])
jeux = sorted(depot.glob(f"{PREFIXE}_*"))
verifier("le jeu porte la base, les documents, les secrets, le manifeste et les empreintes",
         len(jeux) == 1 and {f.name for f in jeux[0].iterdir()} >=
         {"base.sql.gz", "documents.tar.gz", "secrets.tar.gz", "manifeste.txt", "EMPREINTES.sha256"},
         [f.name for f in jeux[0].iterdir()] if jeux else lance.stdout[-300:])
if jeux:
    controle = subprocess.run(["sha256sum", "-c", "--quiet", "EMPREINTES.sha256"], cwd=jeux[0],
                              capture_output=True, text=True)
    verifier("les empreintes du jeu se vérifient", controle.returncode == 0, controle.stdout[-200:])
    manifeste = (jeux[0] / "manifeste.txt").read_text(encoding="utf-8")
    verifier("le manifeste dit le commit et les migrations du jeu",
             "commit du code" in manifeste and "001_initial_schema" in manifeste, manifeste[:200])
    verifier("aucun dossier provisoire ne traîne", not list(depot.glob(".en-cours_*")))
    verifier("le raccourci DERNIER pointe le jeu publié",
             (depot / "DERNIER").resolve() == jeux[0].resolve())
    # Un second passage : la rétention ne doit pas emporter le jeu qu'on vient d'écrire.
    subprocess.run(["bash", "backup.sh"], cwd=projet, env=milieu, capture_output=True, text=True)
    restants = sorted(depot.glob(f"{PREFIXE}_*"))
    verifier("la rétention garde au moins le dernier jeu, même avec RETENTION_DAYS=0",
             len(restants) >= 1, [f.name for f in restants])
# Les producteurs sont repris, y compris si pg_dump échoue au milieu.
operations = atelier / "operations.log"
for echoue in (False, True):
    operations.write_text("")
    r = subprocess.run(["bash", "backup.sh"], cwd=projet,
        env={**milieu, "BANC_OPERATIONS": str(operations), "BANC_DUMP_ECHOUE": "1" if echoue else "0"},
        capture_output=True, text=True)
    lignes = operations.read_text().splitlines()
    stops = [i for i,l in enumerate(lignes) if l.startswith("stop ")]
    dumps = [i for i,l in enumerate(lignes) if " pg_dump " in l]
    starts = [i for i,l in enumerate(lignes) if l.startswith("start ")]
    verifier(f"sauvegarde {'échouée' if echoue else 'réussie'} : arrêt avant dump et reprise ensuite",
             bool(stops and dumps and starts) and stops[0] < dumps[0] < starts[-1]
             and ((r.returncode != 0) == echoue), r.stderr[-300:])
    verifier("un service déjà arrêté ne démarre pas par la sauvegarde",
             not any(l.startswith("start ") and "backend-fictif" not in l for l in lignes))
# Sans le volume des documents, la sauvegarde REFUSE au lieu de mentir.
(faux_bin / "docker").write_text((faux_bin / "docker").read_text(encoding="utf-8").replace(
    "case \"$3\" in *_documents_produits) exit 0;; *) exit 1;; esac", "exit 1"), encoding="utf-8")
sans_volume = subprocess.run(["bash", "backup.sh"], cwd=projet, env=milieu, capture_output=True, text=True)
verifier("sans le volume des documents, elle s'arrête et le DIT",
         sans_volume.returncode != 0 and "introuvable" in sans_volume.stderr, sans_volume.stderr[-200:])
shutil.rmtree(atelier, ignore_errors=True)

print("5. La restauration : à CÔTÉ de la production, sans rien qui sorte")
restaurer = (RACINE / "restaurer.sh").read_text(encoding="utf-8")
verifier("elle refuse de tourner sous le projet de production",
         "REFUS" in restaurer and "est le projet de PRODUCTION" in restaurer)
verifier("elle vérifie les empreintes du jeu avant d'y toucher",
         "sha256sum -c" in restaurer and "jeu abîmé" in restaurer)
verifier("elle vide les clés du .env ET de la base : une copie ne peut rien envoyer",
         "DELETE FROM cles_api" in restaurer and "MAIL_IMAP_" in restaurer and "RESEND_API_KEY" in restaurer)
verifier("elle coupe les tâches planifiées, dans le .env ET en base",
         "AGENT_TASKS_ENABLED=false" in restaurer
         and "agent_tasks SET enabled = false" in restaurer)
verifier("elle coupe la lecture automatique du socle documentaire",
         "connexions_google" in restaurer or "nas_integration_continue" in restaurer)
verifier("chaque coupure part SÉPARÉMENT (une table absente n'annule pas les autres)",
         restaurer.count("couper \"") >= 3)
verifier("elle monte d'autres ports et d'autres volumes (projet distinct)",
         "PORT_FRONT" in restaurer and "$PROJET_COPIE" in restaurer
         and "${PROJET_COPIE}_documents_produits" in restaurer)
verifier("elle nomme les quatre objets à rouvrir, et demande le temps de reprise",
         all(mot in restaurer for mot in ("CONVERSATION", "TRAME", "DOCUMENT avec image", "BROUILLON"))
         and "dernier point restaurable" in restaurer)
verifier("elle sait s'arrêter sans effacer ce qu'elle a restauré", "--arreter" in restaurer)

print("6. La procédure : ce que Noa lance, et dans quel ordre")
recette = (RACINE / "RECETTE-LOT1.md")
verifier("la procédure de recette du lot existe", recette.exists())
if recette.exists():
    texte = recette.read_text(encoding="utf-8")
    verifier("elle donne les commandes du serveur (sauvegarde, déploiement, restauration)",
             all(c in texte for c in ("./backup.sh", "./deploy.sh", "./restaurer.sh")))
    # LES FICHES DU LOT NE SONT PAS LES MÊMES DES DEUX CÔTÉS (le code
    # administrateur est propre à l'un, le connecteur du stockage à l'autre) :
    # on ne fige pas une liste ici, on vérifie que CHAQUE fiche annoncée en tête
    # du document a bien sa place plus bas. Une fiche citée et jamais reprise
    # est exactement ce qu'on veut interdire.
    import re as _re
    entete = texte.split("---", 1)[0]
    annoncees = sorted(set(_re.findall(r"\b[DS]-\d{2}\b", entete)))
    corps = texte.split("---", 1)[1] if "---" in texte else ""
    orphelines = [f for f in annoncees if f not in corps]
    verifier("elle annonce les fiches du lot", len(annoncees) >= 4, annoncees)
    verifier("chaque fiche annoncée est reprise plus bas (rien n'est cité pour mémoire)",
             not orphelines, orphelines)
    # LE SCHÉMA SE DIT. Soit le lot apporte une migration et la NOMME, soit il
    # n'en apporte pas et le dit — c'est ce qu'on regarde en premier quand une
    # livraison se passe mal. Une migration citée doit exister sur le disque.
    import re as _re2
    numeros = {p.name[:3] for p in (RACINE / "backend/database/migrations").glob("[0-9]*.sql")}
    citees = set(_re2.findall(r"\*\*(\d{3})\*\*|migration (\d{3})|la \*\*(\d{3})\*\*", texte))
    citees = {n for triplet in citees for n in triplet if n}
    verifier("elle dit ce que le schéma fait dans ce lot",
             bool(citees) or "aucune migration" in texte.lower(), "aucune migration nommée")
    verifier("les migrations qu'elle nomme existent", citees <= numeros, sorted(citees - numeros))
    verifier("elle dit ce qu'on regarde à l'écran, pas seulement ce qu'on tape",
             "À VÉRIFIER" in texte.upper() and "retour arrière" in texte.lower())

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
