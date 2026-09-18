"""
Banc du CATALOGUE DU NAS QUI SURVIT (18/09). Mesuré en production : « catalogue partiel — 60 341
entrées en 916 s » à chaque heure, donc chaque recherche par nom disait « parcours interrompu » ;
et chaque redéploiement repartait de zéro. Ici : écriture et relecture sur disque, âge porté,
un relevé partiel ne remplace pas un catalogue complet. Sans réseau ; NAS jamais appelé.

    python backend/scripts/test_catalogue_persistant.py backend
"""
import json, os, sys, tempfile, time
from pathlib import Path

BACKEND = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
for k, v in {"DATABASE_URL": "postgresql://x:x@localhost/x", "JWT_SECRET_KEY": "x" * 40, "RESEND_API_KEY": "x",
             "SYNOLOGY_USER": "u", "SYNOLOGY_PASSWORD": "p"}.items():
    os.environ.setdefault(k, v)
os.environ["DOCUMENTS_DIR"] = tempfile.mkdtemp()
ECHECS = []


def verifier(nom, condition, detail=""):
    print(("  ✓ " if condition else "  ✗ ") + nom + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        ECHECS.append(nom)


from nas import acces

verifier("le catalogue vit dans un SOUS-dossier de DOCUMENTS_DIR (jamais un .json à la racine : l'atelier le prendrait pour une fiche)",
         acces._chemin_catalogue().startswith(os.environ["DOCUMENTS_DIR"] + "/cache/") and acces._chemin_catalogue().endswith(".json"))
verifier("rien sur le disque : rien à restaurer, état vide", acces.restaurer_catalogue() is False and acces._CATALOGUE["etat"] == "vide")
entrees = [{"nom": f"AFF {i}", "chemin": f"/home/Drive/x/AFF {i}", "dossier": True} for i in range(50)]
acces._ecrire_catalogue(entrees, True)
data = json.load(open(acces._chemin_catalogue()))
verifier("l'écriture pose un fichier complet, daté, d'un bloc", data["complet"] is True and len(data["entrees"]) == 50 and abs(time.time() - data["construit_le"]) < 5
         and not [f for f in os.listdir(os.path.dirname(acces._chemin_catalogue())) if f.endswith(".tmp")])
# Un « nouveau processus » : mémoire vide, le disque a le catalogue.
acces._CATALOGUE.update({"etat": "vide", "entrees": [], "construit_le": 0.0, "complet": False, "age_s": 0.0})
verifier("au démarrage, le catalogue du disque est RELU et servi tout de suite", acces.restaurer_catalogue() and acces._CATALOGUE["etat"] == "restaure" and len(acces.catalogue_pret() or []) == 50)
verifier("un catalogue complet et récent ne se reconstruit pas avant six heures", acces._CATALOGUE["complet"] and acces._CATALOGUE["age_s"] < 60 and acces.CATALOGUE_DUREE_COMPLET_S == 6 * 3600)
verifier("les plafonds laissent le relevé aller au bout d'un serveur de 60 000 entrées", acces.CATALOGUE_DELAI_S >= 2400 and acces.CATALOGUE_DOSSIERS_MAX >= 200000)
src = (BACKEND / "nas" / "acces.py").read_text(encoding="utf-8")
verifier("un relevé PARTIEL ne remplace pas un catalogue complet déjà en mémoire", "if complet or len(entrees) >= len(_CATALOGUE[\"entrees\"]) or not _CATALOGUE.get(\"complet\"):" in src)
verifier("la tâche de fond relit le disque avant de balayer, et attend si le catalogue est complet et récent", "restaurer_catalogue()\n    # Un catalogue complet" in src and "await asyncio.sleep(max(60.0, CATALOGUE_DUREE_COMPLET_S" in src)
verifier("`catalogue_attendu` (synchronisations) accepte un catalogue restauré", '("pret", "partiel", "restaure")' in src and src.count('("pret", "partiel", "restaure")') >= 2)
# fichier illisible : pas de plantage
open(acces._chemin_catalogue(), "w").write("{pas du json")
acces._CATALOGUE.update({"etat": "vide", "entrees": [], "construit_le": 0.0, "complet": False})
verifier("un fichier abîmé ne casse rien : on repart sans catalogue", acces.restaurer_catalogue() is False and acces._CATALOGUE["etat"] == "vide")

print(("✗ %d échec(s) : %s" % (len(ECHECS), ", ".join(ECHECS))) if ECHECS else "✓ 0 échec")
sys.exit(1 if ECHECS else 0)
