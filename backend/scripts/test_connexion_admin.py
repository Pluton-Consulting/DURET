"""
Banc de la CONNEXION ADMIN PAR CODE — plus de lien magique chez Duret (15/09).

Demande de Noa : « enlève le système magic link même en admin et mets un code
"0000" pour le compte admin, mais laisse-le accessible après avoir cliqué sur
le bouton Admin ». Et, plus tôt : « chaque personne doit pouvoir changer son
propre mot de passe ».

CE QUE CE BANC PROUVE (base doublée, sans réseau) :
  · `cartes_admin` : les super_admin actifs, toujours à code, nom seul ;
  · `controler_code(…, defaut)` EXÉCUTÉ : sans code posé, « 0000 » ouvre, un
    autre code est refusé et compté, un code vide est « requis » ; un code posé
    remplace le défaut ; SANS `defaut` (les cartes ordinaires), rien ne change ;
  · la configuration coupe le lien magique et porte le code par défaut ;
  · les routes : `/connexion/admins`, `/connexion/admin`, la demande de lien et
    les liens d'accès refusés quand le lien est coupé ; l'administrateur peut
    changer son code (et ne peut pas le retirer) ;
  · l'écran : plus de formulaire de lien magique, le bouton Admin ouvre les
    cartes à code, `authorize` connaît l'entrée admin, l'onglet du code est à
    tous et l'onglet Google a disparu.
Tombe sur la version d'avant (`cartes_admin` absent).

Usage : python backend/scripts/test_connexion_admin.py [backend]
"""
import asyncio
import pathlib
import sys
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
front = racine.parent / "frontend"
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


LIGNES = {}


class Conn:
    async def fetchrow(self, sql, *a):
        return LIGNES.get(str(a[0]))

    async def execute(self, sql, *a):
        ligne = LIGNES.get(str(a[0]))
        if ligne is None:
            return
        if "code_pin_echecs = 0, code_pin_bloque_jusqu = NULL" in sql:
            ligne.update(code_pin_echecs=0, code_pin_bloque_jusqu=None)
        elif "code_pin_bloque_jusqu = $2" in sql:
            ligne.update(code_pin_echecs=0, code_pin_bloque_jusqu=a[1])
        elif "code_pin_echecs = $2" in sql:
            ligne.update(code_pin_echecs=a[1])


class Ctx:
    async def __aenter__(self):
        return Conn()

    async def __aexit__(self, *a):
        return False


connexion = types.ModuleType("database.connection")
connexion.get_db = lambda: Ctx()
connexion.schema_incomplet = lambda e: False
sys.modules["database"] = types.ModuleType("database")
sys.modules["database.connection"] = connexion
sys.modules["config"] = types.SimpleNamespace(settings=types.SimpleNamespace(code_admin_defaut="0000"))

print("1. Les cartes et le code")
try:
    import importlib
    P = importlib.import_module("auth.profils")
except Exception as e:  # noqa: BLE001
    P = None
    verifier("auth/profils.py s'importe", False, e)
if P is not None and not hasattr(P, "cartes_admin"):
    verifier("profils porte `cartes_admin`", False, "absent")
    P = None

if P is not None:
    profils = [{"id": "a1", "name": "Noa", "role": "super_admin", "actif": True},
               {"id": "d1", "name": "Éric", "role": "direction", "actif": True},
               {"id": "t1", "name": "Nathalie", "role": "terrain", "actif": True},
               {"id": "a2", "name": "Ancien", "role": "super_admin", "actif": False}]
    cartes = P.cartes_admin(profils)
    verifier("les cartes admin : les super_admin ACTIFS, à code, nom seul",
             cartes == [{"id": "a1", "nom": "Noa", "code": True}], cartes)
    verifier("le code par défaut se lit dans la configuration", P.code_admin_defaut() == "0000")

    LIGNES["a1"] = {"code_pin_hash": None, "code_pin_echecs": 0, "code_pin_bloque_jusqu": None}
    run = asyncio.run
    verifier("sans code posé, « 0000 » ouvre le compte admin",
             run(P.controler_code("a1", "0000", defaut="0000")) is None)
    verifier("un autre code est refusé", run(P.controler_code("a1", "1234", defaut="0000")) == "code_faux")
    verifier("… et compté", LIGNES["a1"]["code_pin_echecs"] == 1, LIGNES["a1"])
    verifier("un code vide est requis", run(P.controler_code("a1", "", defaut="0000")) == "code_requis")
    LIGNES["a1"]["code_pin_hash"] = P.hacher_code("4821")
    verifier("un code POSÉ remplace le défaut : « 0000 » ne marche plus",
             run(P.controler_code("a1", "0000", defaut="0000")) == "code_faux")
    verifier("… et le code posé ouvre", run(P.controler_code("a1", "4821", defaut="0000")) is None)
    LIGNES["t1"] = {"code_pin_hash": None, "code_pin_echecs": 0, "code_pin_bloque_jusqu": None}
    verifier("une carte ordinaire sans code (pas de `defaut`) reste ouverte d'un clic",
             run(P.controler_code("t1", None)) is None)
    LIGNES["a1"].update(code_pin_hash=None, code_pin_echecs=0)
    for _ in range(P.ESSAIS_CODE_MAX):
        dernier = run(P.controler_code("a1", "9999", defaut="0000"))
    verifier("cinq essais faux bloquent la carte admin", dernier == "code_bloque", dernier)

print("2. La configuration et les routes")
conf = (racine / "config.py").read_text(encoding="utf-8")
verifier("le lien magique est coupé par défaut, le code admin vaut « 0000 »",
         "lien_magique_actif: bool = False" in conf and 'code_admin_defaut: str = "0000"' in conf)
auth = (racine / "routers" / "auth.py").read_text(encoding="utf-8")
i = auth.index("async def request_magic_link")
verifier("la demande de lien magique est refusée quand il est coupé",
         "lien_magique_actif" in auth[i:i + 900] and "HTTP_410_GONE" in auth[i:i + 900])
verifier("les routes admin existent", '@router.get("/connexion/admins")' in auth and '@router.post("/connexion/admin")' in auth)
j = auth.index("async def entrer_en_admin")
verifier("l'entrée admin vérifie le code avec le défaut et ne passe que par les cartes admin",
         "defaut=_profils.code_admin_defaut()" in auth[j:j + 2000] and "cartes_admin(tous)" in auth[j:j + 2000])
users = (racine / "routers" / "users.py").read_text(encoding="utf-8")
k = users.index("async def creer_lien_connexion")
verifier("les liens d'accès sont refusés quand le lien magique est coupé", "lien_magique_actif" in users[k:k + 2500])
verifier("chacun peut changer son code, administrateur compris (plus de 409 « pas de carte »)",
         "Un super administrateur n'a pas de carte" not in users and '"possible": True' in users)

print("3. L'écran")
login = (front / "app" / "(auth)" / "login" / "page.tsx").read_text(encoding="utf-8")
verifier("plus de formulaire de lien magique sur la page de connexion",
         "magic-link/request" not in login and "Recevoir un lien" not in login)
verifier("le bouton Admin ouvre les cartes administrateur, à code",
         "connexion/admins" in login and 'admin: "1"' in login and "CodeCarte" in login)
lib = (front / "lib" / "auth.ts").read_text(encoding="utf-8")
verifier("`authorize` connaît l'entrée admin", "/api/auth/connexion/admin`" in lib and "admin: { type:" in lib)
reglages = (front / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
verifier("l'onglet « Mon code » est à tous, l'onglet Google a disparu",
         '{ key: "code", label: "Mon code de connexion" }' in reglages and "GoogleTab" not in reglages)
verifier("le bouton « Lien d'accès » a quitté la liste des utilisateurs",
         "setLienPour({ id: user.id" not in reglages)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
