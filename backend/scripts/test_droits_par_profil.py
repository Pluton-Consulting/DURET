"""
Banc « CHAQUE PROFIL SES DROITS, MÊME AVEC LE MÊME MAIL » (13/09, Duret).

Demande de Noa : même si tout le monde partage la boîte Gmail de l'entreprise,
chaque profil doit être réglable (permissions, plages, rôle : direction,
commercial, administratif…), et ce que « Enrichir » tire du NAS doit être
classé par permission pour cacher des informations à certains. Choix de Noa :
la direction peut avoir sa carte derrière un CODE, et le niveau d'accès se
règle PAR DOSSIER du NAS.

CE QUE CE BANC PROUVE (modules EXÉCUTÉS contre des doublures) :
  * le code d'une carte : empreinte salée jamais égale au code, 4 à 6 chiffres,
    la direction n'a de carte qu'avec un code, le super_admin jamais ; les
    règles de création/changement de rôle sur la boîte ; cinq essais faux
    bloquent la carte (controler_code contre une base doublée) ;
  * le niveau par dossier : la règle du plus long chemin, accents et casse
    ignorés, un niveau inconnu ferme au lieu d'ouvrir, le système voit tout ;
  * le chat : `verifier` refuse un dossier réservé au rôle qui lit, un listage
    le fait disparaître (entrée ET compte), le système (catalogue, synchro)
    voit tout, et un geste lancé par un profil ne filtre pas le catalogue ;
  * la carte du classement : écrite par palier, le morceau ouvert à tous ne
    nomme pas le sous-dossier réservé ; la carte d'un rôle ne le nomme pas ;
  * les goulots : l'exécuteur de skills pose le lecteur, la synchronisation
    écrit le niveau du dossier, le rôle se change par une route ;
  * l'écran : code sur les cartes, rôle modifiable, écran des niveaux.
Tombe sur la version d'avant.
"""
import asyncio
import json
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
sys.path.insert(0, str(BACKEND))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel):
    p = RACINE / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


print(f"\n═══ CHAQUE PROFIL SES DROITS, MÊME AVEC LE MÊME MAIL — {RACINE}\n")

# ── Doublures : configuration, réglages, base ──
REGLAGES = {"nas_niveaux": ""}
config = types.ModuleType("config")
config.settings = types.SimpleNamespace(synology_folders="/home", synology_access_level="all",
                                        synology_source_type="nas")
sys.modules["config"] = config
reglages = types.ModuleType("llm.reglages")
reglages.valeur = lambda nom: REGLAGES.get(nom)
llm = types.ModuleType("llm")
llm.reglages = reglages
sys.modules["llm"] = llm
sys.modules["llm.reglages"] = reglages

# ── 1. Le code d'une carte ──
print("— Le code d'une carte")
try:
    from auth import profils
except Exception as e:  # noqa: BLE001
    profils = None
    verifier("auth/profils se charge", False, e)

if profils is not None and hasattr(profils, "hacher_code"):
    h = profils.hacher_code("4821")
    verifier("l'empreinte n'est pas le code, et deux empreintes du même code diffèrent (sel)",
             "4821" not in h and h != profils.hacher_code("4821"))
    verifier("le bon code passe, un autre non", profils.code_correct("4821", h)
             and not profils.code_correct("4822", h) and not profils.code_correct("", h))
    verifier("4 à 6 chiffres seulement", profils.code_valide("1234") and profils.code_valide("123456")
             and not profils.code_valide("123") and not profils.code_valide("12a4") and not profils.code_valide("1234567"))

    BOITE = "contact@exemple-sols.fr"
    TOUS = [
        {"id": "n", "email": BOITE, "name": "Nathalie", "role": "administratif", "actif": True, "a_code": False},
        {"id": "b", "email": BOITE, "name": "Benoît", "role": "bureau_etudes", "actif": True, "a_code": True},
        {"id": "d", "email": BOITE, "name": "Direction", "role": "direction", "actif": True, "a_code": True},
        {"id": "d2", "email": BOITE, "name": "Direction 2", "role": "direction", "actif": True, "a_code": False},
        {"id": "s", "email": BOITE, "name": "Noa", "role": "super_admin", "actif": True, "a_code": True},
    ]
    c = {x["id"]: x for x in profils.cartes_de_connexion(TOUS, BOITE)}
    verifier("la direction a sa carte avec un code, jamais sans", "d" in c and c["d"]["code"] and "d2" not in c, c)
    verifier("le super_admin n'a jamais de carte, même avec un code", "s" not in c)
    verifier("un profil métier peut avoir un code facultatif", c.get("b", {}).get("code") is True
             and c.get("n", {}).get("code") is False)
    verifier("la direction à code s'ouvre par sa carte (le code se vérifie ensuite)",
             (profils.entree_par_carte(TOUS, BOITE, "d") or {}).get("id") == "d")
    verifier("les cartes d'un lien magique marquent le code (elles en sont retirées côté route)",
             all("code" in x for x in profils.cartes(TOUS)))

    rsb = profils.refus_sur_boite
    verifier("boîte : direction sans code refusée, avec code acceptée",
             rsb("direction", "Claire", False, []) is not None and rsb("direction", "Claire", True, []) is None)
    verifier("boîte : super_admin refusé", rsb("super_admin", "Noa", True, []) is not None)
    verifier("boîte : deux profils du même nom refusés, sauf soi-même (changement de rôle)",
             rsb("terrain", "Nathalie", False, TOUS) is not None
             and rsb("commercial", "Nathalie", False, TOUS, soi="n") is None)

    # controler_code contre une base doublée
    LIGNE = {"code_pin_hash": h, "code_pin_echecs": 0, "code_pin_bloque_jusqu": None}

    class _C:
        async def fetchrow(self, sql, *a):
            return dict(LIGNE)

        async def execute(self, sql, *a):
            if "code_pin_bloque_jusqu = $2" in sql:
                LIGNE.update(code_pin_echecs=0, code_pin_bloque_jusqu=a[1])
            elif "code_pin_echecs = $2" in sql:
                LIGNE["code_pin_echecs"] = a[1]
            elif "code_pin_echecs = 0" in sql:
                LIGNE.update(code_pin_echecs=0, code_pin_bloque_jusqu=None)

    class _Db:
        def __call__(self):
            return self

        async def __aenter__(self):
            return _C()

        async def __aexit__(self, *a):
            return False

    dbmod = types.ModuleType("database.connection")
    dbmod.get_db = _Db()
    dbmod.schema_incomplet = lambda e: False
    sys.modules["database"] = types.ModuleType("database")
    sys.modules["database.connection"] = dbmod
    cc = lambda code: asyncio.run(profils.controler_code("d", code))  # noqa: E731
    verifier("sans code : code_requis", cc(None) == "code_requis")
    verifier("bon code : entrée", cc("4821") is None)
    reponses = [cc("0000") for _ in range(profils.ESSAIS_CODE_MAX)]
    verifier("cinq codes faux : quatre « faux » puis la carte se bloque",
             reponses[:-1] == ["code_faux"] * (profils.ESSAIS_CODE_MAX - 1) and reponses[-1] == "code_bloque", reponses)
    verifier("bloquée, même le bon code est refusé", cc("4821") == "code_bloque")
    LIGNE["code_pin_bloque_jusqu"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    verifier("le blocage passé, le bon code rouvre", cc("4821") is None)
else:
    verifier("auth/profils porte le code des cartes", False)

# ── 2. Le niveau par dossier ──
print("— Le niveau par dossier")
try:
    from nas import niveaux
except Exception as e:  # noqa: BLE001
    niveaux = None
    verifier("nas/niveaux existe", False, e)

REGLES_BRUTES = [
    {"chemin": "/home/Drive/Compta", "niveau": "direction_only"},
    {"chemin": "/home/Drive/Compta/Modèles", "niveau": "all"},
    {"chemin": "/home/Drive/03-Appel d'offres études", "niveau": "bureau_etudes_plus"},
    {"chemin": "/home/Drive/Secret", "niveau": "niveau_invente"},
]
if niveaux is not None:
    R = niveaux.lire_regles(json.dumps(REGLES_BRUTES))
    ndc = lambda c: niveaux.niveau_du_chemin(c, R, "all")  # noqa: E731
    verifier("un fichier prend le niveau de son dossier", ndc("/home/Drive/Compta/2026/bilan.pdf") == "direction_only")
    verifier("la règle la plus précise l'emporte (sous-dossier rouvert)", ndc("/home/Drive/Compta/Modèles/devis.docx") == "all")
    verifier("accents et casse ignorés", ndc("/home/drive/03-APPEL D'OFFRES ETUDES/rc.pdf") == "bureau_etudes_plus")
    verifier("« Compta2 » n'est pas dans « Compta »", ndc("/home/Drive/Compta2/x.pdf") == "all")
    verifier("un niveau inconnu FERME (le plus restrictif)", ndc("/home/Drive/Secret/a.txt") == "admin_only")
    verifier("sans règle : le niveau par défaut", niveaux.niveau_du_chemin("/home/Drive/Chantiers/a", R, "commercial_plus") == "commercial_plus")
    verifier("un réglage illisible n'applique rien (et ne plante pas)", niveaux.lire_regles("{pas du json") == [])
    vis = lambda c, role: niveaux.visible(c, role, R, "all")  # noqa: E731
    verifier("terrain ne voit pas la compta, la direction si", not vis("/home/Drive/Compta/x", "terrain")
             and vis("/home/Drive/Compta/x", "direction"))
    verifier("bureau d'études voit les appels d'offres, le commercial non",
             vis("/home/Drive/03-Appel d'offres études/a", "bureau_etudes") and not vis("/home/Drive/03-Appel d'offres études/a", "commercial"))
    verifier("le système (aucun lecteur) voit tout", vis("/home/Drive/Secret/a", None))
    verifier("un rôle vide est une personne au plus bas niveau, pas le système", not vis("/home/Drive/Compta/x", ""))
    verifier("chemin_de_source : chemin direct, empreinte par le catalogue, autre source ignorée",
             niveaux.chemin_de_source("synology:/home/Drive/a.pdf", {}) == "/home/Drive/a.pdf"
             and niveaux.chemin_de_source("synology:#abc:fin", {"synology:#abc:fin": "/home/long"}) == "/home/long"
             and niveaux.chemin_de_source("gdrive:x", {}) is None)

# ── 3. Le chat : verifier, listage, catalogue ──
print("— Le chat ne voit que son niveau")
REGLAGES["nas_niveaux"] = json.dumps(REGLES_BRUTES)
try:
    from security import lecteur
    from nas import acces
except Exception as e:  # noqa: BLE001
    lecteur = acces = None
    verifier("security/lecteur et nas/acces se chargent", False, e)

if lecteur is not None and acces is not None and niveaux is not None:
    Terrain = types.SimpleNamespace(role="terrain")
    with lecteur.au_nom_de(Terrain):
        try:
            acces.verifier("/home/Drive/Compta/bilan.pdf")
            refuse = False
        except acces.NasRefuse as e:
            refuse = "réservé" in str(e) and "direction" not in str(e).lower()
        ouvert = acces.verifier("/home/Drive/Chantiers/a.pdf") == "/home/Drive/Chantiers/a.pdf"
    verifier("terrain : la compta est refusée sans dire à qui elle est réservée", refuse)
    verifier("terrain : un dossier ouvert passe", ouvert)
    verifier("hors d'un geste (système) : la compta passe", acces.verifier("/home/Drive/Compta/bilan.pdf").endswith("bilan.pdf"))
    verifier("verifier_role : un rôle qui voit au moins un niveau du serveur entre",
             acces.verifier_role(Terrain) is None)

    FICHIERS = [{"name": "Compta", "path": "/home/Drive/Compta", "isdir": True},
                {"name": "Chantiers", "path": "/home/Drive/Chantiers", "isdir": True},
                {"name": "rc.pdf", "path": "/home/Drive/rc.pdf", "isdir": False, "additional": {"size": 10}}]

    async def _appel(client, base, api, methode, version, **kw):
        return {"files": FICHIERS, "total": len(FICHIERS)}

    conn_mod = types.ModuleType("ingestion.connectors.synology")
    conn_mod._appel = _appel
    sys.modules.setdefault("ingestion", types.ModuleType("ingestion"))
    sys.modules.setdefault("ingestion.connectors", types.ModuleType("ingestion.connectors"))
    sys.modules["ingestion.connectors"].synology = conn_mod
    sys.modules["ingestion.connectors.synology"] = conn_mod

    async def lister(role_user):
        if role_user is None:
            return await acces._lister_ouvert(None, "", "", "/home/Drive")
        with lecteur.au_nom_de(role_user):
            return await acces._lister_ouvert(None, "", "", "/home/Drive")

    r_t = asyncio.run(lister(Terrain))
    r_s = asyncio.run(lister(None))
    noms_t = [e["nom"] for e in r_t["entrees"]]
    verifier("listage terrain : « Compta » n'apparaît pas, ni dans le compte",
             "Compta" not in noms_t and r_t["total"] == 2, r_t)
    verifier("listage du système : tout", len(r_s["entrees"]) == 3)

    async def depuis_un_geste():
        # Un geste d'un profil lance une tâche : elle hérite du contexte.
        with lecteur.au_nom_de(Terrain):
            async def tache():
                with lecteur.en_systeme():
                    return lecteur.role_lecteur()
            return await asyncio.get_running_loop().create_task(tache()), lecteur.role_lecteur()
    sys_role, geste_role = asyncio.run(depuis_un_geste())
    verifier("en_systeme() rend la vue entière à une tâche lancée depuis un geste", sys_role is None and geste_role == "terrain")
    src_acces = lire("backend/nas/acces.py")
    verifier("le catalogue se construit en système", "with en_systeme():" in src_acces)
    verifier("la recherche filtre ses trouvailles", "trouves = niveaux.filtrer(trouves, role_lecteur())" in src_acces)
    verifier("la résolution par le catalogue filtre ses candidats",
             "niveaux.filtrer([e for e in cat if _correspond(e)], role_lecteur())" in lire("backend/outils/nas.py"))

# ── 4. La carte du classement ──
print("— La carte du classement")
try:
    from classement import carte
except Exception as e:  # noqa: BLE001
    carte = None
    verifier("classement/carte se charge", False, e)
if carte is not None and hasattr(carte, "chunks_par_palier") and niveaux is not None:
    ENTREES = [{"chemin": "/home/Drive", "dossier": True, "octets": 0},
               {"chemin": "/home/Drive/Compta", "dossier": True, "octets": 0},
               {"chemin": "/home/Drive/Compta/bilan.pdf", "dossier": False, "octets": 5},
               {"chemin": "/home/Drive/Chantiers", "dossier": True, "octets": 0},
               {"chemin": "/home/Drive/Chantiers/a.pdf", "dossier": False, "octets": 5}]
    ch = carte.chunks_par_palier(ENTREES, niveaux.niveau, profondeur=3)
    ouverts = [c for c in ch if c["acces"] == "all"]
    racine_all = [c for c in ouverts if c["chemin"] == "home/Drive"]
    racine_dir = [c for c in ch if c["chemin"] == "home/Drive" and c["acces"] == "direction_only"]
    verifier("le morceau ouvert à tous ne nomme pas « Compta »",
             racine_all and all("Compta" not in c["texte"] for c in ouverts), [c["texte"] for c in ouverts])
    verifier("la version direction du même dossier le nomme", racine_dir and "Compta" in racine_dir[0]["texte"])
    verifier("un morceau identique d'un palier à l'autre n'est pas réécrit",
             len([c for c in ch if c["chemin"] == "home/Drive/Chantiers"]) == 1)
    src = types.ModuleType("classement.source")
    src.visible = lambda chemin, role: niveaux.visible_pour(chemin, role)
    src.signature_droits = lambda role: str(role)
    sys.modules["classement.source"] = src
    carte.ETAT.update(etat="pret", entrees=ENTREES, courte=carte.carte_courte(ENTREES),
                      chunks=carte.construire_chunks(ENTREES, profondeur=40), construit_le=1.0)
    verifier("carte courte d'un profil terrain : pas de « Compta »", "Compta" not in carte.carte_prete("terrain"))
    verifier("carte courte de la direction : « Compta »", "Compta" in carte.carte_prete("direction"))
    verifier("ou_chercher d'un terrain ne trouve pas la compta",
             carte.chercher_dans_la_carte(carte.chunks_prets("terrain"), "compta") == [])
    verifier("le prompt et ou_chercher passent le rôle",
             "_consigne_classement(state.get(\"user_role\")" in lire("backend/agents/agent1.py")
             and "chunks_prets(role)" in lire("backend/skills/classement.py"))
else:
    verifier("classement/carte écrit la carte par palier", False)

# ── 5. Les goulots et les routes ──
print("— Goulots et routes")
verifier("l'exécuteur de skills pose le lecteur", "with au_nom_de(user):" in lire("backend/skills/executor.py"))
verifier("la synchronisation tourne en système, même lancée depuis le chat",
         "with en_systeme():\n        return await _sync(dossiers, avancer)" in lire("backend/ingestion/connectors/synology.py"))
verifier("la synchronisation écrit le niveau du dossier", "access_level=_niveau_nas(f[\"chemin\"])" in lire("backend/ingestion/connectors/synology.py"))
verifier("la carte en base prend le niveau du dossier", "from nas.niveaux import niveau" in lire("backend/classement/source.py"))
users = lire("backend/routers/users.py")
verifier("le rôle se change (route, pas soi-même, règles de la boîte)",
         '@router.put("/{user_id}/role")' in users and "On ne change pas son propre rôle" in users
         and "refus_sur_boite(body.role, cible[\"name\"]" in users)
verifier("le code se pose et se retire, la direction de la boîte le garde",
         '@router.put("/{user_id}/code")' in users and "garde un code" in users)
auth_src = lire("backend/routers/auth.py")
verifier("la carte et le changement de profil exigent le code",
         auth_src.count("await _exiger_code(retenu, body.code") == 2)
verifier("un profil à code ne s'ouvre pas par le lien magique d'une adresse partagée",
         "protégé par un code" in auth_src and "if not c[\"code\"]" in auth_src)
nn = lire("backend/routers/nas_niveaux.py")
verifier("routes des niveaux : lire, enregistrer + reclasser, reprendre les connaissances",
         "reclasser_documents()" in nn and "retirer_connaissances_des_documents()" in nn
         and '"manage_system"' in nn)
verifier("main.py monte la route des niveaux", "nas_niveaux_router" in lire("backend/main.py"))
verifier("migration 041 : empreinte, essais, blocage",
         all(x in lire("backend/database/migrations/041_code_profil.sql")
             for x in ("code_pin_hash", "code_pin_echecs", "code_pin_bloque_jusqu")))

# ── 6. L'écran ──
print("— L'écran")
login = lire("frontend/app/(auth)/login/page.tsx")
verifier("login : une carte à code ouvre la saisie du code", "<CodeCarte" in login and "carte?.code && !code" in login)
verifier("changer de profil : même saisie", "<CodeCarte" in lire("frontend/app/(app)/profil/page.tsx"))
verifier("next-auth fait remonter la raison du code", "class CodeRefuse extends CredentialsSignin" in lire("frontend/lib/auth.ts"))
reg = lire("frontend/app/(app)/parametres/SettingsClient.tsx")
verifier("Paramètres : rôle modifiable par profil", "/role`" in reg and "changerRole(user.id" in reg)
verifier("Paramètres : code à la création et par profil", "code_pin:" in reg and "/code`" in reg)
verifier("Paramètres : l'écran des niveaux du NAS", "<NiveauxNas" in reg and "/api/nas-niveaux" in lire("frontend/components/settings/NiveauxNas.tsx"))

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ tout est vert")
