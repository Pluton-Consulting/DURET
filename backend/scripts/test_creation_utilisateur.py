"""
Banc « créer un utilisateur » — 01/09 nuit.

Relevé de Noa : « j'ai une erreur quand j'essaie de créer un utilisateur ».
Journaux du VPS :

    asyncpg.exceptions.NotNullViolationError: null value in column
    "quota_mensuel" of relation "users" violates not-null constraint
      File "/app/routers/users.py", line 125, in create_user

LE PIÈGE, et il est classique. `quota_mensuel` est déclarée
`INTEGER NOT NULL DEFAULT 50` (migration 001). Le formulaire de création
n'envoie aucun quota, donc le modèle rend `None`, et l'INSERT le passait
EXPLICITEMENT. Or en SQL, un DEFAULT ne s'applique QUE si la colonne est
ABSENTE de l'INSERT : écrire `VALUES (..., NULL)` écrase le défaut et heurte la
contrainte. La création échouait donc à tous les coups — et c'est le premier
geste d'un déploiement chez des salariés.

CE QUE CE BANC EXIGE : que la colonne soit OMISE quand aucun quota n'est donné,
et présente quand il y en a un. Le pool est doublé, les requêtes sont
interceptées : aucune base n'est nécessaire.

Il porte aussi un CONTRÔLE DE FAMILLE : recenser les endroits où un champ
facultatif d'un modèle de requête peut atterrir dans une colonne `NOT NULL`.
Le même piège ailleurs se paierait le même jour, avec la même erreur illisible.
"""
import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ CRÉER UN UTILISATEUR — {BACKEND.resolve().parent}\n")

src = (BACKEND / "routers" / "users.py").read_text(encoding="utf-8")

# ── 1. Les deux INSERT, lus dans le source livré ─────────────────────────
inserts = re.findall(r"INSERT INTO users \(([^)]*)\)", src)
verifier("deux formes d'INSERT : avec quota, et sans", len(inserts) == 2, str(inserts))
sans = [i for i in inserts if "quota_mensuel" not in i]
avec = [i for i in inserts if "quota_mensuel" in i]
verifier("l'une OMET la colonne — c'est ce qui laisse le DEFAULT agir",
         len(sans) == 1 and "email" in sans[0] and "role" in sans[0], str(sans))
verifier("l'autre la porte, pour un quota explicitement demandé",
         len(avec) == 1, str(avec))
verifier("le choix se fait sur l'absence de valeur, pas sur une valeur nulle",
         "if body.quota_mensuel is None:" in src)
verifier("le pourquoi est écrit : un DEFAULT ne s'applique pas à un NULL explicite",
         "N'ACTIVE PAS le défaut" in src)
# Le défaut (50) vit dans la migration : le recopier ici en ferait un second
# endroit à tenir à jour, et le jour où il change, les deux se contrediraient.
_corps_creation = src.split("async def create_user")[1].split("\n@router")[0]
# Le CODE seul : le commentaire, lui, a le droit de citer le défaut pour
# expliquer le piège — c'est même son rôle.
_code_creation = "\n".join(l for l in _corps_creation.splitlines()
                           if not l.strip().startswith("#"))
verifier("et l'on n'a PAS recopié le défaut de la base dans le code",
         "COALESCE" not in _code_creation and "50" not in _code_creation)

# ── 2. LA CRÉATION, EXÉCUTÉE sur un pool doublé ──────────────────────────
REQUETES: list = []


class _Conn:
    async def fetchrow(self, sql, *args):
        REQUETES.append((" ".join(sql.split()), args))
        if "SELECT id FROM users WHERE email" in sql:
            return None                     # l'adresse est libre
        return {"id": "u-1", "email": args[0], "name": args[1], "role": args[2],
                "actif": True, "quota_mensuel": 50, "created_at": None}

    async def fetch(self, sql, *args):
        return []


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


# Seule `create_user` est extraite : le module entier tire FastAPI et la base.
arbre = ast.parse(src)
noeud = next(n for n in arbre.body
             if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_user")
noeud.decorator_list = []          # `@router.post` n'a pas de sens hors de FastAPI


class _Corps:
    def __init__(self, **kw):
        self.email = kw.get("email")
        self.name = kw.get("name")
        self.role = kw.get("role", "terrain")
        self.quota_mensuel = kw.get("quota_mensuel")


class _Moi:
    id = "admin-1"
    role = "super_admin"


class _Http(Exception):
    def __init__(self, status_code=400, detail=""):
        self.status_code, self.detail = status_code, detail


async def _log(**kw):
    return None


espace = {
    "get_db": lambda: _Db(),
    "has_permission": lambda role, quoi: True,
    "SUPER_ADMIN_CREATABLE_ROLES": ["direction", "terrain", "commercial"],
    "DIRECTION_CREATABLE_ROLES": ["terrain", "commercial"],
    "HTTPException": _Http,
    "status": type("s", (), {"HTTP_403_FORBIDDEN": 403, "HTTP_409_CONFLICT": 409}),
    "log_action": _log,
    "_effective_permissions": lambda role, d: {},
    "User": object,
    "Depends": lambda f: None,
    "get_current_user": None,
    # L'annotation `body: CreateUserRequest` est évaluée à la définition.
    "CreateUserRequest": _Corps,
}
exec(compile(ast.Module(body=[noeud], type_ignores=[]), "users", "exec"), espace)
creer = espace["create_user"]

import asyncio  # noqa: E402

REQUETES.clear()
asyncio.run(creer(_Corps(email="jean@symbiose-paysage.fr", name="Jean", role="terrain"),
                  _Moi()))
inserts_joues = [r for r in REQUETES if r[0].startswith("INSERT INTO users")]
verifier("EXÉCUTÉ — sans quota, un seul INSERT part", len(inserts_joues) == 1)
verifier("et il N'ÉCRIT PAS dans quota_mensuel (le défaut de la base s'applique)",
         inserts_joues and "quota_mensuel)" not in inserts_joues[0][0].split("VALUES")[0],
         inserts_joues[0][0][:90] if inserts_joues else "")
verifier("aucun None ne part vers la base",
         inserts_joues and None not in inserts_joues[0][1][:3],
         str(inserts_joues[0][1]) if inserts_joues else "")

REQUETES.clear()
asyncio.run(creer(_Corps(email="marie@symbiose-paysage.fr", name="Marie",
                         role="commercial", quota_mensuel=200), _Moi()))
inserts_joues = [r for r in REQUETES if r[0].startswith("INSERT INTO users")]
verifier("EXÉCUTÉ — avec quota, la colonne est bien écrite",
         inserts_joues and "quota_mensuel)" in inserts_joues[0][0].split("VALUES")[0])
verifier("et la valeur demandée arrive telle quelle",
         inserts_joues and inserts_joues[0][1][3] == 200)

# ── 3. Les refus restent des refus ───────────────────────────────────────
try:
    asyncio.run(creer(_Corps(email="x@y.fr", role="super_admin"), _Moi()))
    refuse = False
except _Http as e:
    refuse = e.status_code == 403
verifier("un rôle hors de ce qu'on peut créer est toujours refusé", refuse)

# ── 4. CONTRÔLE DE FAMILLE : le même piège ailleurs ──────────────────────
# Une colonne `NOT NULL DEFAULT` qui reçoit un champ FACULTATIF d'un modèle de
# requête, c'est la même erreur en attente. On les recense pour qu'elles soient
# regardées, sans juger à leur place : beaucoup passent une vraie valeur.
sql = "".join(p.read_text(encoding="utf-8")
              for p in (BACKEND / "database" / "migrations").glob("*.sql"))
piegees = set(re.findall(r"^\s+(\w+)\s+[\w()\[\] ]+NOT NULL DEFAULT", sql, re.M))
verifier("des colonnes NOT NULL à défaut existent bien (sinon le banc ne prouve rien)",
         len(piegees) > 10, str(len(piegees)))

facultatifs = set()
for f in (BACKEND / "routers").glob("*.py"):
    a = ast.parse(f.read_text(encoding="utf-8"))
    for n in ast.walk(a):
        if isinstance(n, ast.ClassDef):
            for x in n.body:
                if isinstance(x, ast.AnnAssign) and isinstance(x.target, ast.Name):
                    if isinstance(x.value, ast.Constant) and x.value.value is None:
                        facultatifs.add(x.target.id)
communs = sorted(piegees & facultatifs)
verifier("`quota_mensuel` était bien de cette famille — le banc vise juste",
         "quota_mensuel" in communs, str(communs))
print(f"\n     À SURVEILLER (facultatif côté requête, NOT NULL côté base) :"
      f"\n     {', '.join(communs) if communs else 'aucun'}")
print("     Ce n'est pas une liste de bugs : la plupart reçoivent une vraie")
print("     valeur. C'est la liste de ce qui casserait de la même façon.")

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
