"""
Banc « L'ADMINISTRATION DES PROFILS » (14/09, Duret).

Demande de Noa : en admin, modifier ou supprimer complètement des profils ;
créer des profils sur une adresse dont la boîte n'est pas encore reliée et
choisir leurs dossiers du mail plus tard ; chacun se connecte avec son prénom
même sans boîte configurée ; les codes des cartes se posent à la création, se
VOIENT et se modifient ensuite en admin, et chacun change le sien depuis son
espace.

CE QUE CE BANC PROUVE (modules EXÉCUTÉS contre des doublures) :
  * les cartes ne dépendent plus de la boîte (avec ou sans, les mêmes) ;
  * le code se chiffre et se relit, un secret changé le rend illisible sans
    lever, l'empreinte reste la seule vérification ;
  * la suppression : refusée pour soi, hors hiérarchie, pour le dernier
    super_admin ; sinon les colonnes sans ON DELETE sont remises à NULL (ou
    leurs lignes effacées quand la colonne est obligatoire) AVANT le DELETE,
    dans une transaction, avec le contexte RLS ;
  * la modification : nom et adresse, doublon refusé sur une adresse partagée ;
  * le code personnel : lu et changé sans permission d'admin, 4 à 6 chiffres,
    la direction partagée ne le retire pas ;
  * la liste d'admin rend le code aux seuls profils que l'on gère ;
  * l'écran : colonne Code, Modifier, Supprimer (nom à retaper), dossiers sans
    boîte, section « Mon code de connexion ».
Tombe sur la version d'avant.

⚠️ Le chiffrement exige `cryptography` (présente dans l'image par
`pyjwt[crypto]`). Sans elle, le banc le DIT et saute ces contrôles.
"""
import ast
import asyncio
import pathlib
import sys
import types
from uuid import UUID

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel):
    return (RACINE / rel).read_text(encoding="utf-8")


print(f"\n═══ L'ADMINISTRATION DES PROFILS — {RACINE}\n")

# ── Le module des profils ────────────────────────────────────────────────
SECRET = {"v": "secret-du-banc"}
faux_config = types.ModuleType("config")
faux_config.settings = types.SimpleNamespace()
type(faux_config.settings)  # noqa
sys.modules["config"] = faux_config


class _Reglages:
    @property
    def jwt_secret_key(self):
        return SECRET["v"]


faux_config.settings = _Reglages()

chemin = BACKEND / "auth" / "profils.py"
profils = types.ModuleType("auth.profils")
exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), profils.__dict__)

print("— Les cartes, boîte reliée ou non")
TOUS = [
    {"id": "n", "email": "contact@exemple-sols.fr", "name": "Nathalie", "role": "administratif", "actif": True},
    {"id": "e", "email": "eric@exemple-sols.fr", "name": "Éric", "role": "terrain", "actif": True},
    {"id": "d", "email": "contact@exemple-sols.fr", "name": "Direction", "role": "direction", "actif": True, "a_code": True},
    {"id": "s", "email": "noa@exemple.fr", "name": "Noa", "role": "super_admin", "actif": True, "a_code": True},
]
avec = profils.cartes_de_connexion(TOUS, "contact@exemple-sols.fr")
sans = profils.cartes_de_connexion(TOUS, None)
verifier("sans boîte reliée, les cartes existent (Noa : « même si l'adresse n'est pas configurée »)",
         [c["id"] for c in sans] == ["n", "e", "d"], sans)
verifier("et ce sont les mêmes qu'avec la boîte", avec == sans)
verifier("un profil sur une autre adresse s'ouvre par sa carte",
         (profils.entree_par_carte(TOUS, None, "e") or {}).get("id") == "e")
verifier("le super_admin n'a toujours pas de carte", profils.entree_par_carte(TOUS, None, "s") is None)

print("— Le code chiffré")
try:
    import cryptography  # noqa: F401
    CRYPTO = True
except ImportError:
    CRYPTO = False
    print("  (cryptography absente de ce poste : contrôles du chiffrement sautés — "
          "présente dans l'image par pyjwt[crypto])")
if CRYPTO:
    c = profils.chiffrer_code("4821")
    verifier("EXÉCUTÉ — le code chiffré ne contient pas le code", c and "4821" not in c, c)
    verifier("il se relit", profils.dechiffrer_code(c) == "4821")
    verifier("deux chiffrements du même code diffèrent (pas un dictionnaire de 1 million d'entrées)",
             profils.chiffrer_code("4821") != c)
    SECRET["v"] = "autre-secret"
    verifier("un secret changé : illisible, sans lever", profils.dechiffrer_code(c) is None)
    SECRET["v"] = "secret-du-banc"
    verifier("rien à chiffrer : rien", profils.chiffrer_code("") is None and profils.dechiffrer_code(None) is None)
verifier("la vérification reste sur l'empreinte",
         profils.code_correct("4821", profils.hacher_code("4821")))

# ── Les routes de users.py, extraites et exécutées ───────────────────────
print("— Les routes d'administration")
source = lire("backend/routers/users.py")
arbre = ast.parse(source)
NOMS = {"supprimer_utilisateur", "modifier_utilisateur", "mon_code", "changer_mon_code",
        "peut_ouvrir_pour", "_ident", "_poser_code"}
morceaux = []
for n in arbre.body:
    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in NOMS:
        n.decorator_list = []
        n.args.defaults = []  # `Depends(get_current_user)` ne s'évalue pas ici
        n.returns = None
        for a in n.args.args:
            a.annotation = None
        morceaux.append(n)
    elif isinstance(n, ast.Assign) and any(getattr(t, "id", "") in
                                             {"_REFERENCES_SANS_CASCADE", "DIRECTION_CREATABLE_ROLES"}
                                             for t in n.targets):
        morceaux.append(n)
trouves = {getattr(n, "name", None) for n in morceaux}
verifier("users.py porte supprimer, modifier, mon code (lire et changer)",
         {"supprimer_utilisateur", "modifier_utilisateur", "mon_code", "changer_mon_code"} <= trouves,
         sorted(x for x in trouves if x))


class HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        self.status_code, self.detail = status_code, detail


BASE = {
    "users": {
        "sa": {"id": "sa", "email": "noa@exemple.fr", "name": "Noa", "role": "super_admin", "actif": True},
        "sa2": {"id": "sa2", "email": "autre@exemple.fr", "name": "Autre", "role": "super_admin", "actif": True},
        "dir": {"id": "dir", "email": "contact@exemple-sols.fr", "name": "Direction", "role": "direction", "actif": True},
        "nat": {"id": "nat", "email": "contact@exemple-sols.fr", "name": "Nathalie", "role": "administratif", "actif": True},
        "eric": {"id": "eric", "email": "contact@exemple-sols.fr", "name": "Éric", "role": "terrain", "actif": True},
    },
    "code": {},
}
SQL = []
REFS = [{"tbl": "audit_log", "col": "user_id", "nullable": True},
        {"tbl": "api_usage_daily", "col": "user_id", "nullable": False},
        {"tbl": "trames", "col": "cree_par", "nullable": True}]


class _Tx:
    async def __aenter__(self):
        SQL.append("BEGIN")

    async def __aexit__(self, *x):
        SQL.append("COMMIT" if x[0] is None else "ROLLBACK")


class _Conn:
    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *a):
        uid = str(a[0])
        u = BASE["users"].get(uid)
        if not u:
            return None
        if "code_pin_hash" in sql:
            h, c = BASE["code"].get(uid, (None, None))
            return {**u, "code_pin_hash": h, "code_pin_chiffre": c}
        return dict(u)

    async def fetchval(self, sql, *a):
        if "super_admin" in sql:
            return sum(1 for u in BASE["users"].values()
                       if u["role"] == "super_admin" and u["actif"] and u["id"] != str(a[0]))
        return 0

    async def fetch(self, sql, *a):
        return REFS if "pg_constraint" in sql else []

    async def execute(self, sql, *a):
        SQL.append(" ".join(sql.split()))
        if sql.startswith("DELETE FROM users"):
            BASE["users"].pop(str(a[0]), None)
        if sql.startswith("UPDATE users SET name"):
            BASE["users"][str(a[2])].update(name=a[0], email=a[1])
        if "code_pin_hash = $1" in sql:
            BASE["code"][str(a[1])] = (a[0], a[2] if len(a) > 2 else None)


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *x):
        return False


JOURNAL = []


async def _log(**kw):
    JOURNAL.append(kw)


async def _profils_de(email, actifs=True):
    return [dict(u, a_code=bool(BASE["code"].get(u["id"], (None,))[0]))
            for u in BASE["users"].values() if u["email"].lower() == (email or "").lower()]


async def _adresse():
    return BOITE["v"]


BOITE = {"v": None}
doublure = types.ModuleType("auth.profils")
doublure.__dict__.update({k: v for k, v in profils.__dict__.items() if not k.startswith("__")})
doublure.profils_de = _profils_de
doublure.adresse_partagee = _adresse


async def _code_obligatoire(role, email):
    if role != "direction":
        return False
    return len(await _profils_de(email)) > 1


doublure.code_obligatoire = _code_obligatoire
sys.modules["auth"] = types.SimpleNamespace(profils=doublure)
sys.modules["auth.profils"] = doublure
faux_conn = types.ModuleType("database.connection")
faux_conn.schema_incomplet = lambda e: False
sys.modules["database"] = types.SimpleNamespace(connection=faux_conn)
sys.modules["database.connection"] = faux_conn

espace = {
    "get_db": lambda: _Db(), "HTTPException": HTTPException, "log_action": _log,
    "has_permission": lambda role, f: role in ("super_admin", "direction"),
    "UUID": UUID, "Optional": __import__("typing").Optional,
    "status": types.SimpleNamespace(HTTP_403_FORBIDDEN=403, HTTP_404_NOT_FOUND=404,
                                    HTTP_409_CONFLICT=409, HTTP_400_BAD_REQUEST=400),
}
if {"supprimer_utilisateur", "modifier_utilisateur", "mon_code", "changer_mon_code"} <= trouves:
    exec(compile(ast.Module(body=morceaux, type_ignores=[]), "users", "exec"), espace)

    def qui(uid, role):
        return types.SimpleNamespace(id=uid, role=role)

    def appel(coro):
        try:
            return asyncio.run(coro)
        except HTTPException as e:
            return e

    sup = espace["supprimer_utilisateur"]
    r = appel(sup("sa", qui("sa", "super_admin")))
    verifier("on ne se supprime pas soi-même", isinstance(r, HTTPException) and r.status_code == 403)
    r = appel(sup("dir", qui("dir2", "direction")))
    verifier("la direction ne supprime pas une direction", isinstance(r, HTTPException) and r.status_code == 403)
    BASE["users"]["sa2"]["actif"] = False
    r = appel(sup("sa", qui("dir", "super_admin")))
    verifier("le dernier super_admin actif ne se supprime pas", isinstance(r, HTTPException) and r.status_code == 409, r)
    BASE["users"]["sa2"]["actif"] = True
    verifier("et rien n'a été écrit pour ces refus", not any(s.startswith(("UPDATE", "DELETE")) for s in SQL), SQL)

    SQL.clear(); JOURNAL.clear()
    r = appel(sup("eric", qui("dir", "direction")))
    verifier("EXÉCUTÉ — la direction supprime un profil métier", r == {"status": "deleted", "user_id": "eric"}, r)
    verifier("le profil a disparu de la base", "eric" not in BASE["users"])
    i_del = next((i for i, s in enumerate(SQL) if s.startswith("DELETE FROM users")), -1)
    verifier("une transaction, avec le contexte RLS posé d'abord",
             SQL[0] == "BEGIN" and "app.current_role" in " ".join(SQL[:4]) and SQL[-1] == "COMMIT", SQL)
    verifier("une colonne facultative sans ON DELETE passe à NULL AVANT le DELETE",
             any(s.startswith('UPDATE audit_log SET "user_id" = NULL') for s in SQL[:i_del]), SQL)
    verifier("une colonne obligatoire voit ses lignes effacées AVANT le DELETE",
             any(s.startswith('DELETE FROM api_usage_daily WHERE "user_id"') for s in SQL[:i_del]), SQL)
    verifier("la suppression est journalisée", any(j.get("action") == "user_deleted" for j in JOURNAL))

    mod = espace["modifier_utilisateur"]
    corps = lambda **k: types.SimpleNamespace(**{"name": None, "email": None, **k})  # noqa: E731
    r = appel(mod("nat", corps(name="Nathalie B."), qui("dir", "direction")))
    verifier("EXÉCUTÉ — renommer un profil", isinstance(r, dict) and BASE["users"]["nat"]["name"] == "Nathalie B.", r)
    BASE["users"]["eric"] = {"id": "eric", "email": "eric@exemple.fr", "name": "Éric", "role": "terrain", "actif": True}
    r = appel(mod("eric", corps(email="contact@exemple-sols.fr", name="Nathalie B."), qui("sa", "super_admin")))
    verifier("rejoindre une adresse où le nom existe déjà : refusé", isinstance(r, HTTPException) and r.status_code == 409, r)
    r = appel(mod("eric", corps(email="contact@exemple-sols.fr"), qui("sa", "super_admin")))
    verifier("rejoindre l'adresse de l'entreprise, boîte non reliée : accepté",
             isinstance(r, dict) and BASE["users"]["eric"]["email"] == "contact@exemple-sols.fr", r)
    r = appel(mod("eric", corps(email="pas-une-adresse"), qui("sa", "super_admin")))
    verifier("une adresse invalide est refusée", isinstance(r, HTTPException) and r.status_code == 400)
    r = appel(mod("dir", corps(name="Chef"), qui("nat", "direction")))
    verifier("la direction ne modifie pas une autre direction", isinstance(r, HTTPException) and r.status_code == 403)

    lire_code, changer = espace["mon_code"], espace["changer_mon_code"]
    r = appel(changer(types.SimpleNamespace(code="12a4"), qui("nat", "administratif")))
    verifier("mon code : 4 à 6 chiffres", isinstance(r, HTTPException) and r.status_code == 400)
    SQL.clear()
    r = appel(changer(types.SimpleNamespace(code="2580"), qui("nat", "administratif")))
    verifier("EXÉCUTÉ — un profil métier change SON code, sans permission d'admin",
             isinstance(r, dict) and r["code"] == "2580" and BASE["code"]["nat"][0], r)
    verifier("l'empreinte ET le chiffré sont écrits",
             any("code_pin_chiffre = $3" in s for s in SQL), SQL)
    if CRYPTO:
        r = appel(lire_code(qui("nat", "administratif")))
        verifier("et il le relit dans son espace", r.get("code") == "2580" and r["a_code"] and r["possible"], r)
    BASE["code"]["dir"] = (profils.hacher_code("9999"), profils.chiffrer_code("9999"))
    r = appel(changer(types.SimpleNamespace(code=None), qui("dir", "direction")))
    verifier("la direction sur une adresse partagée ne retire pas son code",
             isinstance(r, HTTPException) and r.status_code == 409, r)
    r = appel(changer(types.SimpleNamespace(code="1234"), qui("sa", "super_admin")))
    verifier("le super_admin n'a pas de carte, donc pas de code", isinstance(r, HTTPException) and r.status_code == 409)

# ── Contrats de source ───────────────────────────────────────────────────
print("— Contrats")
verifier("« /me/code » est déclarée AVANT « /{user_id}/code » (« me » n'est pas un UUID)",
         source.index('@router.get("/me/code")') < source.index('@router.put("/{user_id}/code")')
         and source.index('@router.put("/me/code")') < source.index('@router.put("/{user_id}")'))
verifier("la liste rend le code déchiffré aux seuls profils gérés",
         "_profils.dechiffrer_code(" in source and "peut_ouvrir_pour(current_user.role, d[\"role\"])" in source)
verifier("la création partagée suit les règles des cartes même sans boîte",
         "partagee = _profils.meme_adresse(body.email, boite) or bool(existants)" in source)
verifier("migration 042 : le code chiffré", "code_pin_chiffre" in lire("backend/database/migrations/042_code_profil_lisible.sql"))
auth_src = lire("backend/routers/auth.py")
verifier("la page de connexion lit TOUS les profils, plus seulement la boîte",
         "cartes_de_connexion(await _profils.profils_tous())" in auth_src
         and "boite_absente" not in auth_src)

ecran = lire("frontend/app/(app)/parametres/SettingsClient.tsx")
verifier("écran : colonne Code visible et modifiable", '"Code"' in ecran and "codesVisibles" in ecran)
verifier("écran : Modifier le profil (nom, adresse)", "enregistrerProfil" in ecran and 'method: "PUT"' in ecran)
verifier("écran : Supprimer, nom à retaper", 'method: "DELETE"' in ecran
         and "aSupprimer.saisie.trim() !== aSupprimer.nom.trim()" in ecran)
verifier("écran : les dossiers du mail se choisissent sans boîte reliée (plus tard)",
         '"Dossiers mail", "Code"' in ecran and "se choisiront plus tard" in ecran)
verifier("écran : le code se pose à la création, boîte ou non",
         'form.role !== "super_admin" && (' in ecran)
page = lire("frontend/app/(app)/profil/page.tsx")
# 14/09 : la section vit dans un composant partagé avec Paramètres.
code_perso = lire("frontend/components/settings/MonCode.tsx")
verifier("mon espace : « Mon code de connexion », lu et changé par /me/code",
         "<MonCode jeton={jeton} />" in page and "Mon code de connexion" in code_perso
         and "/api/users/me/code" in code_perso)
verifier("le panneau mène toujours à Mon profil",
         "Mon profil" in lire("frontend/components/nav/EnTete.tsx"))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
