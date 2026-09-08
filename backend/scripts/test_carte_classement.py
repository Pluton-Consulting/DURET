"""
Banc « LA CARTE DU CLASSEMENT » (08/09 soir).

Demande de Noa : « analyser tout le drive pour avoir vraiment un schéma et
enregistrer toute l'architecture sous forme schématique dans la base de
données vectorisée, pour qu'il puisse savoir exactement où chercher ». Et,
dans l'export du même jour : « liste-moi les dossiers » → 60 s de balayage,
« ouvre le premier PDF » → un balayage de plus.

CE QUE CE BANC PROUVE (fonctions EXÉCUTÉES, sans stockage ni base) : les
entrées d'un classement (forme Drive : dossiers avec comptes ; forme NAS :
fichiers un à un) deviennent des morceaux qui NOMMENT les dossiers clients
jusqu'à la profondeur 4 ; la carte courte tient dans le prompt ; la recherche
en mémoire rend le chemin EXACT, sans accent ; le cycle de rafraîchissement
garde la carte et l'écrit en base sans jamais lever ; le skill `ou_chercher`
rend un tableau garanti et nomme le geste d'ouverture ; chez Symbiose, le
catalogue du Drive n'est balayé qu'une fois par heure ; le prompt, le
démarrage et la dérive sont câblés. Tombe sur la version d'avant.
"""
import ast
import asyncio
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(chemin, nom, espace_sup=None):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    if espace_sup:
        mod.__dict__.update(espace_sup)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    return mod


def fonctions(chemin, noms, espace):
    src = chemin.read_text(encoding="utf-8")
    arbre = ast.parse(src)
    morceaux = [ast.get_source_segment(src, n) for n in arbre.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms]
    manquantes = [n for n in noms if not any(m.startswith(("def " + n, "async def " + n)) for m in morceaux)]
    if manquantes:
        return manquantes
    exec(compile("from __future__ import annotations\n" + "\n\n".join(morceaux), str(chemin), "exec"), espace)
    return []


print(f"\n═══ LA CARTE DU CLASSEMENT — {BACKEND.parent}\n")

carte_src = BACKEND / "classement" / "carte.py"
verifier("le module socle `classement/carte.py` existe", carte_src.exists())
if not carte_src.exists():
    print("✗ rien à tester"); sys.exit(1)
carte = charger(carte_src, "carte_double")

# ── 1. Un classement d'essai, dans les deux formes ──
print("— les entrées deviennent une carte")
R = "Drive partagé « Symbiose Paysage »"
S = f"{R}/SYMBIOSE PAYSAGE"
clients = [f"33 LA TESTE - DUPONT", "33 ARCACHON - MARTIN", "33 GUJAN - Éric LEFÈVRE"] \
    + [f"33 BORDEAUX - CLIENT {i:03d}" for i in range(1, 121)]
entrees_drive = [
    {"chemin": R, "dossier": True},
    {"chemin": S, "dossier": True, "fichiers": 5, "octets": 5_000, "types": {"pdf": 5}},
    {"chemin": f"{S}/1-ÉTUDES", "dossier": True},
    {"chemin": f"{S}/1-ÉTUDES/Dossiers Études", "dossier": True, "fichiers": 2, "types": {"xlsx": 2}},
    {"chemin": f"{S}/2-PROJETS", "dossier": True},
    {"chemin": f"{S}/2-PROJETS/Dossiers chantiers", "dossier": True},
    {"chemin": f"{S}/2-PROJETS/Dossiers chantiers/33 BORDEAUX - ED1.1", "dossier": True, "fichiers": 3, "types": {"pdf": 3}},
    {"chemin": f"{S}/2-PROJETS/Dossiers chantiers/33 BORDEAUX - ED1.1/CCTP", "dossier": True, "fichiers": 12, "octets": 12_000_000, "types": {"pdf": 10, "docx": 2}},
    {"chemin": f"{S}/5-ADMINISTRATIF", "dossier": True, "fichiers": 40, "types": {"pdf": 30, "gsheet": 10}},
] + [{"chemin": f"{S}/1-ÉTUDES/Dossiers Études/{c}", "dossier": True, "fichiers": 4, "octets": 4_000, "types": {"pdf": 2, "dwg": 2}} for c in clients]
noeuds = carte.entrees_vers_arbre(entrees_drive)
verifier("forme Drive : chaque dossier est un nœud, les sous-dossiers rattachés au parent",
         set(noeuds[S]["sous"]) == {"1-ÉTUDES", "2-PROJETS", "5-ADMINISTRATIF"}
         and len(noeuds[f"{S}/1-ÉTUDES/Dossiers Études"]["sous"]) == len(clients))
entrees_nas = [
    {"chemin": "/home/Drive", "dossier": True},
    {"chemin": "/home/Drive/ETUDES EN COURS", "dossier": True},
    {"chemin": "/home/Drive/ETUDES EN COURS/2029 AIRBORNE/1 - DCE/2029 RC VF.pdf", "dossier": False, "octets": 347_078},
    {"chemin": "/home/Drive/ETUDES EN COURS/2029 AIRBORNE/1 - DCE/AOS - DCE.zip", "dossier": False, "octets": 179_337_215},
    {"chemin": "/home/Drive/ETUDES EN COURS/IKOS VILLAGE/CCTP/17_IKOS - CCTP17 - PLATRERIE.pdf", "dossier": False, "taille": 975_000},
    {"chemin": "/home/Drive/COMPTA/factures 2026.xlsx", "dossier": False, "octets": 20_000},
]
noeuds_nas = carte.entrees_vers_arbre(entrees_nas)
verifier("forme NAS : les fichiers comptent dans leur dossier, avec leurs types et leur taille",
         noeuds_nas["home/Drive/ETUDES EN COURS/2029 AIRBORNE/1 - DCE"]["fichiers"] == 2
         and noeuds_nas["home/Drive/ETUDES EN COURS/2029 AIRBORNE/1 - DCE"]["types"] == {"pdf": 1, "zip": 1}
         and noeuds_nas["home/Drive/ETUDES EN COURS/IKOS VILLAGE/CCTP"]["octets"] == 975_000)
verifier("…et les dossiers intermédiaires (jamais listés comme tels) existent quand même",
         "IKOS VILLAGE" in noeuds_nas["home/Drive/ETUDES EN COURS"]["sous"]
         and "COMPTA" in noeuds_nas["home/Drive"]["sous"])

chunks = carte.construire_chunks(entrees_drive)
par_chemin = {}
for c in chunks:
    par_chemin.setdefault(c["chemin"], []).append(c)
verifier("un morceau par dossier jusqu'à la profondeur 3 (racine = 0), aucun au-delà",
         f"{S}/1-ÉTUDES/Dossiers Études" in par_chemin
         and f"{S}/1-ÉTUDES/Dossiers Études/{clients[0]}" not in par_chemin
         and f"{S}/2-PROJETS/Dossiers chantiers/33 BORDEAUX - ED1.1" not in par_chemin)
etudes = par_chemin[f"{S}/1-ÉTUDES/Dossiers Études"]
verifier("123 dossiers clients : DEUX morceaux (suite 1/2, 2/2), aucun nom perdu",
         len(etudes) == 2 and all(f"(suite {i + 1}/2)" in etudes[i]["texte"] for i in range(2))
         and all(any(cl in e["texte"] for e in etudes) for cl in clients))
verifier("le morceau porte l'emplacement, les comptes et les types (« pdf 2, dwg 2 » remontés des enfants ? non : ceux du dossier)",
         "Emplacement : Drive partagé « Symbiose Paysage » › SYMBIOSE PAYSAGE › 1-ÉTUDES › Dossiers Études" in etudes[0]["texte"]
         and "123 dossiers en tout" in etudes[0]["texte"]
         and "494 fichiers en tout" in etudes[0]["texte"]   # 123 × 4 + 2
         and "types de fichiers : xlsx 2" in etudes[0]["texte"])
projets = par_chemin[f"{S}/2-PROJETS/Dossiers chantiers"][0]
verifier("un sous-dossier nommé porte ses comptes (« 33 BORDEAUX - ED1.1 (1 dossier, 15 fichiers) »)",
         "33 BORDEAUX - ED1.1 (1 dossier, 15 fichiers)" in projets["texte"], projets["texte"][-200:])

courte = carte.carte_courte(entrees_drive)
verifier("la carte courte replie la racine à enfant unique et nomme les premiers dossiers avec leurs comptes",
         courte.startswith(f"{R}/SYMBIOSE PAYSAGE : 1-ÉTUDES (124 doss., 494 fich.) ; 2-PROJETS")
         and "5-ADMINISTRATIF (40 fich.)" in courte, courte)
verifier("elle tient dans le prompt (≤ 700 caractères)", len(courte) <= 700)
grosse = [{"chemin": "R", "dossier": True}] + [{"chemin": f"R/Dossier numéro {i} très long", "dossier": True} for i in range(80)]
verifier("une carte trop longue est coupée à une frontière et le dit (« ; … »)",
         carte.carte_courte(grosse).endswith(" ; …") and len(carte.carte_courte(grosse)) <= 705)

print("— chercher dans la carte, en mémoire")
t = carte.chercher_dans_la_carte(chunks, "dupont")
verifier("« dupont » rend le chemin EXACT du dossier client (profondeur 4), en premier",
         t and t[0]["chemin"] == f"{S}/1-ÉTUDES/Dossiers Études/33 LA TESTE - DUPONT", t[:2])
t = carte.chercher_dans_la_carte(chunks, "Lefevre")
verifier("sans accent ni casse : « Lefevre » trouve « Éric LEFÈVRE »",
         t and t[0]["chemin"].endswith("33 GUJAN - Éric LEFÈVRE"))
tous = carte.construire_chunks(entrees_drive, profondeur=None)
verifier("en mémoire, TOUS les dossiers ont leur morceau (la base ne reçoit que la profondeur 3)",
         len(tous) > len(chunks) and any(c["chemin"].endswith("33 BORDEAUX - ED1.1") for c in tous))
t = carte.chercher_dans_la_carte(tous, "cctp")
verifier("« cctp » rend le dossier CCTP par son chemin exact (profondeur 5)",
         t and t[0]["chemin"].endswith("33 BORDEAUX - ED1.1/CCTP"), t[:2])
verifier("…sur les seuls morceaux de la base (profondeur 3), « cctp » n'existe pas : c'est POURQUOI la mémoire garde tout",
         carte.chercher_dans_la_carte(chunks, "cctp") == [])
t = carte.chercher_dans_la_carte(chunks, "dossiers etudes")
verifier("plusieurs mots : tous exigés, le dossier « Dossiers Études » sort en tête",
         t and t[0]["chemin"] == f"{S}/1-ÉTUDES/Dossiers Études", t[:2])
verifier("un sujet vide ou trop court ne rend rien", carte.chercher_dans_la_carte(chunks, "") == []
         and carte.chercher_dans_la_carte(chunks, "de") == [])
verifier("un sujet inconnu ne rend rien (pas de dossier inventé)", carte.chercher_dans_la_carte(chunks, "zzzz") == [])

# ── 2. Le cycle : la carte se garde et s'écrit sans jamais lever ──
print("— le cycle de rafraîchissement")
verifier("avant tout relevé, la carte est vide et le prompt ne reçoit rien",
         carte.carte_prete() == "" and carte.chunks_prets() == [])
source = types.ModuleType("classement.source")


async def _entrees_ok():
    return entrees_drive, True
source.entrees_du_classement = _entrees_ok
source.niveau_de = lambda chemin: "direction_only" if "5-ADMINISTRATIF" in chemin else "all"
source.NOM_STOCKAGE, source.GESTE_LISTER, source.GESTE_CHERCHER = "Drive d'essai", "drive_apercu", "drive_chercher"
sys.modules["classement"] = types.ModuleType("classement")
sys.modules["classement.source"] = source
sys.modules["classement.carte"] = carte
ECRITS = []


async def _enregistrer(chunks_, niveau_de):
    ECRITS.extend((c["chemin"], niveau_de(c["chemin"])) for c in chunks_)
    return len(chunks_)
carte.enregistrer = _enregistrer
etat = asyncio.run(carte.rafraichir_carte())
verifier("après le relevé : prête, comptes justes, morceaux en mémoire ET écrits en base",
         etat["etat"] == "pret" and etat["dossiers"] == len(entrees_drive) - 1 and etat["fichiers"] == 5 + 2 + 3 + 12 + 40 + 123 * 4
         and len(etat["chunks"]) == len(carte.construire_chunks(entrees_drive, profondeur=None))
         and etat["en_base"] == len(chunks), {k: v for k, v in etat.items() if k != "chunks"})
verifier("chaque morceau part avec le niveau d'accès de SON dossier",
         any(n == "direction_only" for c, n in ECRITS if "5-ADMINISTRATIF" in c)
         and all(n == "all" for c, n in ECRITS if "1-ÉTUDES" in c))
verifier("le prompt reçoit la carte courte", carte.carte_prete() == courte)


async def _enregistrer_casse(chunks_, niveau_de):
    raise RuntimeError("base absente")
carte.enregistrer = _enregistrer_casse
etat = asyncio.run(carte.rafraichir_carte())
verifier("une base absente ne casse rien : la carte reste en mémoire", etat["etat"] == "pret" and carte.carte_prete())


async def _entrees_ko():
    raise RuntimeError("Drive injoignable")
source.entrees_du_classement = _entrees_ko
etat = asyncio.run(carte.rafraichir_carte())
verifier("un stockage injoignable ne lève pas : l'erreur est notée, l'ancienne carte reste servie",
         "injoignable" in etat["erreur"] and carte.carte_prete() == courte and not etat["en_cours"])

# ── 3. Le skill ──
print("— le skill `ou_chercher`")
registre = types.ModuleType("skills.registre")


class Declaration:
    def __init__(self, **kw):
        self.__dict__.update(kw)
registre.Declaration = Declaration
sys.modules["skills"] = types.ModuleType("skills")
sys.modules["skills.registre"] = registre
source.entrees_du_classement = _entrees_ok
carte.enregistrer = _enregistrer
asyncio.run(carte.rafraichir_carte())
sk = charger(BACKEND / "skills" / "classement.py", "skills_classement_double")
decl = sk.SKILLS["ou_chercher"]
verifier("déclaré en LECTURE (aucun accord demandé pour regarder la carte), avec son libellé",
         decl.effet == "lecture" and decl.libelle.startswith("je ") and "sujet" in decl.optionnels)
res = asyncio.run(sk.ou_chercher({"sujet": "dupont"}, None))
verifier("« dupont » : un tableau GARANTI avec le chemin exact, et le geste d'ouverture nommé",
         res.get("bloc_garanti") is True and res["bloc_ui"]["type"] == "table"
         and res["bloc_ui"]["rows"][0][1].endswith("33 LA TESTE - DUPONT")
         and "`drive_apercu`" in res["a_faire"] and "Ne devine jamais" in res["a_faire"], res)
res = asyncio.run(sk.ou_chercher({}, None))
verifier("sans sujet : la carte des racines et les comptes", res.get("carte") == courte and res["dossiers"] == len(entrees_drive) - 1)
res = asyncio.run(sk.ou_chercher({"sujet": "zzzz"}, None))
verifier("rien trouvé : pas de bloc, et la suite proposée (un mot, la recherche par nom, le contenu)",
         "bloc_ui" not in res and "drive_chercher" in res["a_faire"] and "rechercher_documents" in res["a_faire"])
carte.ETAT.update({"etat": "vide", "chunks": [], "courte": ""})
res = asyncio.run(sk.ou_chercher({"sujet": "dupont"}, None))
verifier("carte pas encore relevée : dit, avec le repli", "pas encore relevée" in res["message_final"] and "drive_chercher" in res["a_faire"])

# ── 4. Le câblage ──
print("— le câblage")
src_source = BACKEND / "classement" / "source.py"
verifier("la source propre au client existe et expose le contrat (entrées, niveau, noms des gestes)",
         src_source.exists() and all(x in src_source.read_text(encoding="utf-8") for x in
                                     ("async def entrees_du_classement", "def niveau_de", "NOM_STOCKAGE", "GESTE_LISTER", "GESTE_CHERCHER")))
ag1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("agent1 : `_consigne_classement` existe et entre dans le prompt du tour",
         "def _consigne_classement" in ag1 and "system_prompt += _consigne_classement()" in ag1)
verifier("agent1 : le prompt dit d'appeler `ou_chercher` AVANT de parcourir l'arborescence",
         "`ou_chercher` dit D'ABORD" in ag1)
esp = {}
manque = fonctions(BACKEND / "agents" / "agent1.py", ["_consigne_classement"], esp)
if not manque:
    carte.ETAT.update({"etat": "pret", "courte": courte})
    consigne = esp["_consigne_classement"]()
    verifier("la consigne porte la carte courte, le nom du stockage et l'interdiction de deviner",
             courte in consigne and "Drive d'essai" in consigne and "Ne devine jamais un emplacement" in consigne)
    carte.ETAT.update({"etat": "vide", "courte": ""})
    verifier("sans carte, aucune consigne (on ne décrit pas ce qu'on n'a pas vu)", esp["_consigne_classement"]() == "")
main_src = (BACKEND / "main.py").read_text(encoding="utf-8")
verifier("main.py lance la carte au démarrage, en fond, sans pouvoir casser le démarrage",
         "from classement.carte import demarrer_carte" in main_src and "asyncio.create_task(demarrer_carte())" in main_src)
decl_txt = (BACKEND.parent / "scripts" / "derive.declaration.txt").read_text(encoding="utf-8")
verifier("la dérive déclare `classement/source.py` (connecteur), pas `carte.py` (socle)",
         "backend/classement/source.py" in decl_txt and "backend/classement/carte.py" not in decl_txt)

drive = BACKEND / "outils" / "drive.py"
if drive.exists():
    print("— Symbiose : le catalogue du Drive n'est balayé qu'une fois par heure")
    src = drive.read_text(encoding="utf-8")
    verifier("`arborescence` et `chercher` lisent le catalogue gardé, plus le balayage direct",
             src.count("await _catalogue(service, identite)") == 2
             and "catalogue, dossiers_partiels = await _balayer_dossiers(service)" not in src)
    verifier("le compte des fichiers relève aussi le nom et le type MIME (types par dossier)",
             'fields="nextPageToken, files(parents,size,name,mimeType)"' in src)
    APPELS = {"dossiers": 0, "fichiers": 0}

    async def _bal(service):
        APPELS["dossiers"] += 1
        return {"d1": {"nom": "A", "parents": ["root"]}}, False

    async def _cpt(service):
        APPELS["fichiers"] += 1
        return {"d1": [3, 300, {"pdf": 3}]}, False
    espd = {"_balayer_dossiers": _bal, "_compter_fichiers": _cpt, "asyncio": asyncio,
            "logger": types.SimpleNamespace(info=lambda *a, **k: None),
            "_CATALOGUES": {}, "CATALOGUE_DRIVE_DUREE_S": 3600}
    manque = fonctions(drive, ["_cle_client", "_copie_catalogue", "_construire_catalogue", "_catalogue", "_type_de_fichier"], espd)
    verifier("les fonctions du catalogue existent", not manque, manque)
    if not manque:
        async def _deux_fois():
            a = await espd["_catalogue"](None, None)
            b = await espd["_catalogue"](None, None)
            return a, b
        a, b = asyncio.run(_deux_fois())
        verifier("deux gestes de suite : UN seul balayage (dossiers ET fichiers)", APPELS == {"dossiers": 1, "fichiers": 1}, APPELS)
        verifier("le résultat porte dossiers, partialité, comptes avec types",
                 a[0] == {"d1": {"nom": "A", "parents": ["root"]}} and a[1] is False and a[2]["d1"][2] == {"pdf": 3})
        a[0]["d1"]["parents"] = ["__orphelins__"]
        verifier("un appelant qui modifie les parents ne touche pas le catalogue gardé",
                 espd["_CATALOGUES"]["service"]["dossiers"]["d1"]["parents"] == ["root"])
        import time as _time
        espd["_CATALOGUES"]["service"]["construit_le"] = _time.monotonic() - 7200   # périmé depuis deux heures

        async def _perime():
            c = await espd["_catalogue"](None, None)
            await asyncio.sleep(0.01)
            return c
        c = asyncio.run(_perime())
        verifier("périmé : l'ancien est servi tout de suite, la reconstruction part en fond",
                 c[0]["d1"]["nom"] == "A" and APPELS["dossiers"] == 2)

        async def _perso():
            return await espd["_catalogue"](None, "u1")
        asyncio.run(_perso())
        verifier("une autre identité a SON catalogue (jamais celui d'une autre personne)",
                 "perso:u1" in espd["_CATALOGUES"] and APPELS["dossiers"] == 3)
        verifier("le type d'un fichier : extension, ou nature Google",
                 espd["_type_de_fichier"]("devis.PDF", "application/pdf") == "pdf"
                 and espd["_type_de_fichier"]("Planning", "application/vnd.google-apps.spreadsheet") == "gsheet"
                 and espd["_type_de_fichier"]("README", "text/plain") == "sans extension")
    print("— Symbiose : le niveau d'accès suit les périmètres du Drive")
    gd = types.ModuleType("ingestion.connectors.google_drive")
    sys.modules["ingestion"] = types.ModuleType("ingestion")
    sys.modules["ingestion.connectors"] = types.ModuleType("ingestion.connectors")
    sys.modules["ingestion.connectors.google_drive"] = gd
    esps = {}
    fonctions(src_source, ["_nu", "niveau_de"], esps)
    esps["unicodedata"] = __import__("unicodedata")
    gd.perimetres = lambda: [("5-ADMINISTRATIF", "direction_only"), ("2-PROJETS", "all")]
    verifier("un dossier sous un périmètre nommé prend son niveau ; hors de tout périmètre : admin seul",
             esps["niveau_de"](f"{S}/5-ADMINISTRATIF/Juridique") == "direction_only"
             and esps["niveau_de"](f"{S}/2-PROJETS/Dossiers chantiers") == "all"
             and esps["niveau_de"](f"{S}/1-ÉTUDES") == "admin_only")
    gd.perimetres = lambda: [(None, "commercial_plus")]
    verifier("sans périmètre nommé : le niveau unique du Drive", esps["niveau_de"](f"{S}/1-ÉTUDES") == "commercial_plus")
else:
    print("— Duret : le niveau d'accès est celui du serveur")
    cfg = types.ModuleType("config")
    cfg.settings = types.SimpleNamespace(synology_access_level="bureau_etudes_plus")
    sys.modules["config"] = cfg
    espn = {}
    fonctions(src_source, ["niveau_de"], espn)
    verifier("chaque morceau prend le niveau du NAS", espn["niveau_de"]("/home/Drive/X") == "bureau_etudes_plus")
    verifier("la source attend le catalogue de fond au lieu de relancer un balayage",
             "catalogue_pret()" in src_source.read_text(encoding="utf-8") and "ATTENTE_CATALOGUE_S" in src_source.read_text(encoding="utf-8"))

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
