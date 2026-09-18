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

print("— Le relevé INCRÉMENTAL : un dossier dont la date n'a pas bougé n'est pas relisté")
import asyncio
ARBRE = {"/home/Drive": [{"nom": "A", "chemin": "/home/Drive/A", "dossier": True, "modifie": 100},
                         {"nom": "B", "chemin": "/home/Drive/B", "dossier": True, "modifie": 200}],
         "/home/Drive/A": [{"nom": "a1.pdf", "chemin": "/home/Drive/A/a1.pdf", "dossier": False, "modifie": 5, "octets": 1}],
         "/home/Drive/B": [{"nom": "b1.pdf", "chemin": "/home/Drive/B/b1.pdf", "dossier": False, "modifie": 6, "octets": 1},
                           {"nom": "C", "chemin": "/home/Drive/B/C", "dossier": True, "modifie": 300}],
         "/home/Drive/B/C": [{"nom": "c1.pdf", "chemin": "/home/Drive/B/C/c1.pdf", "dossier": False, "modifie": 7, "octets": 1}]}
LISTES = []
async def _faux_lister(client, base, sid, chemin, tout=False):
    LISTES.append(chemin); return {"entrees": ARBRE.get(chemin, [])}
acces._lister_ouvert = _faux_lister
acces._CACHE_LISTAGE.clear()
entrees, complet = asyncio.run(acces._balayer(None, "", "", ["/home/Drive"], lambda e: True, delai_s=60, dossiers_max=1000, profondeur=10))
verifier("premier relevé : tout est listé (4 dossiers), 6 entrées, complet", len(LISTES) == 4 and len(entrees) == 6 and complet, str((len(LISTES), len(entrees), complet)))
acces._CATALOGUE.update({"entrees": entrees, "complet": True, "etat": "pret"})
connu = acces._releve_precedent()
verifier("le relevé précédent donne la date de chaque dossier et ses enfants", connu["dates"]["/home/Drive/A"] == 100 and len(connu["enfants"]["/home/Drive/B"]) == 2)
# B a changé (un fichier ajouté) ; A n'a pas bougé
ARBRE["/home/Drive"][1]["modifie"] = 201
ARBRE["/home/Drive/B"].append({"nom": "b2.pdf", "chemin": "/home/Drive/B/b2.pdf", "dossier": False, "modifie": 8, "octets": 1})
LISTES.clear(); acces._CACHE_LISTAGE.clear(); progres = {}
entrees2, complet2 = asyncio.run(acces._balayer(None, "", "", ["/home/Drive"], lambda e: True, delai_s=60, dossiers_max=1000, profondeur=10, progres=progres, connu=connu))
verifier("second relevé : A et C repris sans listage, B relisté, le nouveau fichier vu",
         sorted(LISTES) == ["/home/Drive", "/home/Drive/B"] and len(entrees2) == 7 and complet2 and progres.get("reutilises") == 2, str((sorted(LISTES), len(entrees2), progres.get("reutilises"))))
verifier("la synchronisation demande un relevé COMPLET (les dates des fichiers ne se voient pas dans celle d'un dossier)",
         "relire_tout=True" in (BACKEND / "ingestion" / "connectors" / "synology.py").read_text(encoding="utf-8")
         and "def construire_catalogue(relire_tout: bool = False)" in src.replace("async ", ""))
verifier("l'avancement dit les dossiers repris", "dossiers repris du relevé précédent" in acces.decrire_progression({"debut": 0.0, "delai_s": 60, "reutilises": 12}))

print("— Les fichiers les plus récents, d'après le catalogue")
acces._CATALOGUE.update({"etat": "pret", "complet": False, "construit_le": 10 ** 9, "entrees": [
    {"nom": "a.pdf", "chemin": "/home/Drive/x/a.pdf", "dossier": False, "modifie": 1700000000, "octets": 3},
    {"nom": "b.pdf", "chemin": "/home/Drive/y/b.pdf", "dossier": False, "modifie": 1800000000, "octets": 3},
    {"nom": "y", "chemin": "/home/Drive/y", "dossier": True, "modifie": 1800000000}]})
acces.dossiers_autorises = lambda: ["/home/Drive"]; acces.verifier = lambda c: c
import nas.niveaux as _nv; _nv.filtrer = lambda e, r: e
r = acces.plus_recents(None, 5)
verifier("`plus_recents` rend les FICHIERS du plus récent au plus ancien, datés en clair, et dit si le relevé est partiel",
         [x["nom"] for x in r["resultats"]] == ["b.pdf", "a.pdf"] and r["resultats"][0]["modifie_le"].startswith("15/01/2027") and "PARTIEL" in r["note"], str(r)[:200])
verifier("sous un dossier précis : seulement ce qui vit dessous", [x["nom"] for x in acces.plus_recents("/home/Drive/x", 5)["resultats"]] == ["a.pdf"])
acces._CATALOGUE.update({"etat": "vide", "entrees": []}); acces.restaurer_catalogue = lambda: False
verifier("sans catalogue : rien d'inventé, la limite est dite", acces.plus_recents(None, 5)["resultats"] == [] and "pas encore construit" in acces.plus_recents(None, 5)["note"])
sk = (BACKEND / "skills" / "nas.py").read_text(encoding="utf-8")
verifier("`nas_chercher` expose `plus_recents` au catalogue et n'exige plus `motif`", '"plus_recents"' in sk and 'requis=[], optionnels=["motif", "dossier", "plus_recents", "par_affaire"]' in sk)
verifier("le listage porte la date des dossiers, et la recherche affiche « Modifié le »", '"modifie": (add.get("time") or {}).get("mtime"),' in src and '"Modifié le"' in (BACKEND / "skills" / "affichage.py").read_text(encoding="utf-8"))

print("— Plusieurs dossiers du même nom : on ne devine pas")
import outils.nas as onas
async def _pas_de_chemin(client, base, sid, chemin):
    if chemin in ("/home/Drive",): return []
    raise acces.NasRefuse("inexistant")
onas._enfants_dossiers = _pas_de_chemin
acces.dossiers_autorises = lambda: ["/home/Drive"]
acces._CATALOGUE.update({"etat": "pret", "complet": True, "construit_le": 10 ** 9, "entrees": [
    {"nom": "AFF 102-24 Bloc sanitaire college Dheurle La Teste", "chemin": "/home/Drive/04-Chantiers a executer/CHANTIERS 2024/AFF 102-24 Bloc sanitaire college Dheurle La Teste", "dossier": True, "modifie": 1700000000},
    {"nom": "construction 29 lgts sociaux la test de buch 18-09-2026", "chemin": "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/construction 29 lgts sociaux la test de buch 18-09-2026", "dossier": True, "modifie": 1800000000},
    {"nom": "AFF 093-25 ALSH LA TESTE DE BUCH", "chemin": "/home/Drive/02-Devis-affaires/12-Affaires 2025/AFF 093-25 ALSH LA TESTE DE BUCH", "dossier": True, "modifie": 1750000000},
    {"nom": "Photos", "chemin": "/home/Drive/04-Chantiers a executer/CHANTIERS 2024/AFF 102-24 Bloc sanitaire college Dheurle La Teste/Photos", "dossier": True, "modifie": 1},
    {"nom": "ETUDES EN COURS", "chemin": "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS", "dossier": True, "modifie": 1}]})
try:
    print("   résolu à tort :", asyncio.run(onas._resoudre(None, "", "", "La Teste"))); refus = ""
except Exception as e:
    refus = f"{type(e).__name__}: {e}"
# 18/09 : le dossier des 29 logements s'écrit « la test de buch » sur le serveur (une faute). Il
# n'était jamais proposé pour « La Teste » — l'appel d'offres EN COURS manquait à la liste. À une
# lettre finale près, il y est, le plus récent en tête.
verifier("« La Teste » vit dans trois affaires : REFUS qui les liste, la plus récente d'abord — « la test de buch » compris",
         "Plusieurs dossiers" in refus and -1 < refus.find("29 lgts") < refus.find("ALSH") < refus.find("Dheurle"), refus[:400])
verifier("la tolérance ne vaut que pour une lettre FINALE (s, e, x) sur un mot d'au moins quatre lettres",
         acces._mot_proche("teste", "test") and acces._mot_proche("chantiers", "chantier") and not acces._mot_proche("de", "des")
         and not acces._mot_proche("test", "texte") and not acces._mot_proche("lot", "lots"))
verifier("un nom qui ne désigne qu'un dossier se résout toujours", asyncio.run(onas._resoudre(None, "", "", "ETUDES EN COURS")) == "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS")
verifier("des candidats emboîtés (un dossier et son sous-dossier) ne sont pas une ambiguïté : le plus haut gagne",
         asyncio.run(onas._resoudre(None, "", "", "Dheurle")).endswith("Dheurle La Teste"))

# 18/09 : relais en 502, la racine ne se listait pas → « home » partait en recherche par nom et
# attrapait « …custHOME » (sous-chaîne) → fausse ambiguïté.
acces._CATALOGUE["entrees"] += [
    {"nom": "AFF 100-20 eiffage sinistre custDRIVE", "chemin": "/home/Drive/03-Appel d'offres etudes/AFF 100-20 eiffage sinistre custDRIVE", "dossier": True, "modifie": 5},
    {"nom": "AFF 100-20 eiffage sinistre custDRIVE", "chemin": "/home/Drive/04-Chantiers a executer/AFF 100-20 eiffage sinistre custDRIVE", "dossier": True, "modifie": 6}]
async def _tout_en_panne(client, base, sid, chemin):
    raise RuntimeError("502 Bad Gateway")
onas._enfants_dossiers = _tout_en_panne
verifier("une racine qui ne répond pas reste la racine quand le catalogue prouve qu'elle existe",
         asyncio.run(onas._resoudre(None, "", "", "Drive")) == "/home/Drive")
# 18/09 : le chemin EXACT de l'appel d'offres en cours, relais en 502 → recherche de « home » par nom
# → « plusieurs dossiers correspondent à « home » ». Un chemin du périmètre qui ne répond pas le DIT.
import httpx
async def _relais_502(client, base, sid, chemin):
    raise httpx.ConnectError("502 Bad Gateway")
onas._enfants_dossiers = _relais_502
_verif = acces.verifier
acces.verifier = lambda c: "/" + c.strip("/") if ("/" + c.strip("/")).startswith("/home/Drive") else (_ for _ in ()).throw(acces.NasRefuse("hors"))
try:
    asyncio.run(onas._resoudre(None, "", "", "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/construction 29 lgts"))
    r_502 = "résolu"
except Exception as e:
    r_502 = f"{type(e).__name__}: {e}"
verifier("un chemin exact du périmètre qui ne répond pas (502) → « serveur indisponible », pas une recherche de « home »",
         r_502.startswith("NasIndisponible") and "home »" not in r_502, r_502[:160])
acces.verifier = _verif
onas._enfants_dossiers = _pas_de_chemin
try:
    r_mot = asyncio.run(onas._resoudre(None, "", "", "eiffage"))
except Exception as e:
    r_mot = f"{type(e).__name__}: {e}"
verifier("…et « drive » n'attrape plus « custDRIVE » quand un nom correspond mot pour mot",
         acces._nom_correspond("AFF 100-20 eiffage sinistre custDRIVE", "drive", mots_entiers=True) is False
         and acces._nom_correspond("2029 AIRBORNE SONOVISION", "airborne", mots_entiers=True) is True)

# 18/09 : l'appel d'offres de La Teste a QUITTÉ « ETUDES EN COURS » le jour de sa remise. Le chemin
# exact d'un listage du matin rendait « aucun dossier de ce nom », sans piste : le refus propose
# désormais les dossiers du catalogue qui portent les mêmes mots.
ARBRE = {"/home": ["Drive"], "/home/Drive": ["03-Appel d'offres etudes"],
         "/home/Drive/03-Appel d'offres etudes": ["ETUDES EN COURS", "ETUDES TERMINEE"],
         "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS": ["AFF 00 Dossier Modèle"]}
async def _arbre(client, base, sid, chemin):
    if chemin in ARBRE:
        return [{"nom": n, "chemin": chemin.rstrip("/") + "/" + n, "dossier": True} for n in ARBRE[chemin]]
    raise RuntimeError("ce dossier ou fichier N'EXISTE PAS sur le NAS")
onas._enfants_dossiers = _arbre
acces.dossiers_autorises = lambda: ["/home"]
acces._CATALOGUE["entrees"] += [
    {"nom": "AFF 150-26 construction 29 lgts sociaux la test de buch", "chemin": "/home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE/- AFF 2026/AFF 150-26 construction 29 lgts sociaux la test de buch", "dossier": True, "modifie": 1900000000}]
try:
    asyncio.run(onas._resoudre(None, "", "", "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/construction 29 lgts sociaux la test de buch 18-09-2026 emarches publics"))
    r_dep = "résolu"
except Exception as e:
    r_dep = f"{type(e).__name__}: {e}"
verifier("un dossier DÉPLACÉ : le refus dit « déplacé ou renommé » et propose le nouvel emplacement, le plus récent d'abord",
         "DÉPLACÉ" in r_dep and "ETUDES TERMINEE/- AFF 2026/AFF 150-26" in r_dep
         and r_dep.find("AFF 150-26") < r_dep.find("ETUDES EN COURS/construction 29 lgts sociaux la test de buch 18-09-2026\"") if "18-09-2026\"" in r_dep else "AFF 150-26" in r_dep, r_dep[:500])
verifier("un nom d'un seul mot significatif ne propose rien au hasard", onas._deplace_ailleurs("PDF") == [])
# 18/09 (navigateur) : la racine ouverte est /home/Drive, le chemin exact d'une affaire a disparu
# pendant une réorganisation du NAS → la résolution cherchait le NOM « home » et rendait « plusieurs
# dossiers correspondent à home » (les deux « …custHOME »). Elle part désormais de la racine.
ARBRE["/home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE"] = ["- AFF 2020"]
ARBRE["/home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE/- AFF 2020"] = ["AFF 100-20 eiffage sinistre custHOME"]
acces.dossiers_autorises = lambda: ["/home/Drive"]
acces._CATALOGUE["entrees"] += [
    {"nom": "AFF 100-20 eiffage sinistre custHOME", "chemin": "/home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE/- AFF 2020/AFF 100-20 eiffage sinistre custHOME", "dossier": True, "modifie": 5},
    {"nom": "AFF 100-20 eiffage sinistre custHOME", "chemin": "/home/Drive/04-Chantiers a executer/AFF 100-20 eiffage sinistre custHOME", "dossier": True, "modifie": 6}]
try:
    asyncio.run(onas._resoudre(None, "", "", "/home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE/- AFF 2020/AFF 145-20 CIS St Aguilin"))
    r_home = "résolu"
except Exception as e:
    r_home = f"{type(e).__name__}: {e}"
verifier("un chemin sous la racine /home/Drive se descend depuis elle : le segment manquant est NOMMÉ, jamais « home »",
         "« home »" not in r_home and "Aucun dossier « AFF 145-20 CIS St Aguilin » dans /home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE/- AFF 2020" in r_home,
         r_home[:300])

# 18/09 (banc Duret, Q6) : « combien de DPGF par affaire » → 200 résultats et aucun décompte.
aff = acces.affaire_du_chemin
verifier("l'affaire d'un fichier : le dossier « AFF … » le plus haut",
         aff("/home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE/- AFF 2020/AFF 145-20 CIS St Aguilin/Piéces techniques/DPGF lot 01.xlsx")
         == ("AFF 145-20 CIS St Aguilin", "/home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE/- AFF 2020/AFF 145-20 CIS St Aguilin"))
verifier("sans dossier AFF : le dossier sous la dernière catégorie de classement",
         aff("/home/Drive/03-Appel d'offres etudes/ETUDE PERDU/LE COL - OPERATION SARAH/dpgf_lot 11.xls")[0] == "LE COL - OPERATION SARAH"
         and aff("/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/Construction 12 lgts Vayres 21-09-2026 emarchepublics/1 - DCE/DPGF.pdf")[0]
         == "Construction 12 lgts Vayres 21-09-2026 emarchepublics")
acces._CATALOGUE.update({"etat": "pret", "complet": False, "construit_le": 10 ** 9, "entrees": [
    {"nom": "DPGF lot 01.xlsx", "chemin": "/home/Drive/E/ETUDES TERMINEE/- AFF 2020/AFF 145-20 CIS/P/DPGF lot 01.xlsx", "dossier": False},
    {"nom": "DPGF lot 11.xlsx", "chemin": "/home/Drive/E/ETUDES TERMINEE/- AFF 2020/AFF 145-20 CIS/P/DPGF lot 11.xlsx", "dossier": False},
    {"nom": "dpgf_lot 11.xls", "chemin": "/home/Drive/E/ETUDE PERDU/LE COL/dpgf_lot 11.xls", "dossier": False},
    {"nom": "DPGF", "chemin": "/home/Drive/E/ETUDE PERDU/LE COL/DPGF", "dossier": True},
    {"nom": "CCTP.pdf", "chemin": "/home/Drive/E/ETUDE PERDU/LE COL/CCTP.pdf", "dossier": False}]})
acces.dossiers_autorises = lambda: ["/home"]
compte = acces.compter_par_affaire("DPGF")
verifier("le décompte porte sur tout le catalogue, fichiers seuls, groupé et trié par affaire",
         compte["total"] == 3 and [(g["affaire"], g["fichiers"]) for g in compte["groupes"]] == [("AFF 145-20 CIS", 2), ("LE COL", 1)],
         compte)
verifier("un catalogue partiel se DIT dans le décompte", "PARTIEL" in (compte.get("note") or ""))

# 18/09 : « RC » remontait « ARCHIVES », « Planning masse chantier… ».
nc = acces._nom_correspond
verifier("un sigle court se cherche en MOT entier : « RC » trouve « RC.pdf », « 01.NVAQ392-RC.pdf », pas « ARCHIVES »",
         nc("RC.pdf", "RC") and nc("01.NVAQ392-RC.pdf", "RC") and not nc("ARCHIVES 2024", "RC")
         and not nc("Planning masse chantier 2024.xlsx", "RC"))
verifier("au-delà de trois caractères, le morceau de mot reste permis (« dpgf » dans « CDPGF »)",
         nc("AAS 4207 - ECO DCE - CDPGF Lot 212.xlsx", "DPGF") and nc("Dpgf_lot 11.xls", "dpgf"))

print(("✗ %d échec(s) : %s" % (len(ECHECS), ", ".join(ECHECS))) if ECHECS else "✓ 0 échec")
sys.exit(1 if ECHECS else 0)
