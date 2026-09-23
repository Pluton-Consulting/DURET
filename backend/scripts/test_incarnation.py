"""
Banc « SE CONNECTER EN TANT QUE » (23/09, Duret).

Demande de Noa : « en admin dans les paramètres, on peut se connecter sur le profil de
n'importe quel autre utilisateur sans connaître son code ».

CE QUE CE BANC PROUVE : la route EXÉCUTÉE contre une base doublée — super_admin seul,
jamais soi-même, jamais un profil désactivé ni un autre super_admin, chaque ouverture
tracée, un jeton COURT (2 h) qui porte `incarne_par` et aucun jeton d'appareil (la
session ne survit pas) ; nginx envoie la route au backend ; l'écran propose le bouton au
seul super_admin et montre un bandeau tant que la session dure.
"""
import ast
import asyncio
import pathlib
import sys
import types
from contextlib import asynccontextmanager
from datetime import timedelta

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ SE CONNECTER EN TANT QUE — {RACINE}\n")
source = (BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")


class HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        self.status_code, self.detail = status_code, detail


PROFILS = {
    "11111111-1111-1111-1111-111111111111": {"id": "11111111-1111-1111-1111-111111111111", "email": "b@x.fr",
                                             "name": "Benoît", "role": "appels_offres", "actif": True},
    "22222222-2222-2222-2222-222222222222": {"id": "22222222-2222-2222-2222-222222222222", "email": "o@x.fr",
                                             "name": "Ancien", "role": "administratif", "actif": False},
    "33333333-3333-3333-3333-333333333333": {"id": "33333333-3333-3333-3333-333333333333", "email": "a@x.fr",
                                             "name": "Autre admin", "role": "super_admin", "actif": True},
}
JOURNAL, JETONS = [], []


class Conn:
    async def fetchrow(self, sql, uid):
        return PROFILS.get(uid)


@asynccontextmanager
async def get_db():
    yield Conn()


async def log_action(**k):
    JOURNAL.append(k)


def create_access_token(data, expires_delta=None):
    JETONS.append((data, expires_delta))
    return "jeton"


class _Routeur:
    def post(self, *a, **k):
        return lambda f: f


espace = {"HTTPException": HTTPException, "status": types.SimpleNamespace(
    HTTP_403_FORBIDDEN=403, HTTP_404_NOT_FOUND=404, HTTP_409_CONFLICT=409),
    "get_db": get_db, "log_action": log_action, "create_access_token": create_access_token,
    "timedelta": timedelta, "router": _Routeur(), "Depends": lambda f=None: None,
    "get_current_user": None, "User": object, "BaseModel": object, "IncarnerRequest": object}
arbre = ast.parse(source)
noeuds = [n for n in arbre.body if (isinstance(n, ast.AsyncFunctionDef) and n.name == "incarner")
          or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DUREE_INCARNATION")]
verifier("la route /incarner existe", len(noeuds) == 2)
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "auth", "exec"), espace)
incarner = espace["incarner"]


def essai(role, cible, moi="99999999-9999-9999-9999-999999999999"):
    try:
        return asyncio.run(incarner(types.SimpleNamespace(user_id=cible),
                                    types.SimpleNamespace(id=moi, role=role)))
    except HTTPException as e:
        return e.status_code


r = essai("super_admin", "11111111-1111-1111-1111-111111111111")
verifier("super_admin → la session du profil", isinstance(r, dict) and r["user_id"].startswith("1111")
         and r["role"] == "appels_offres", r)
verifier("le jeton porte qui s'est connecté à la place", JETONS and JETONS[-1][0].get("incarne_par", "").startswith("9999"))
verifier("le jeton est court (2 h)", JETONS and JETONS[-1][1] == timedelta(hours=2))
verifier("aucun jeton d'appareil : la session ne survit pas", isinstance(r, dict) and r["refresh_token"] is None)
verifier("chaque ouverture est tracée", JOURNAL and JOURNAL[-1]["action"] == "incarnation")
verifier("direction : refusé", essai("direction", "11111111-1111-1111-1111-111111111111") == 403)
verifier("profil métier : refusé", essai("appels_offres", "11111111-1111-1111-1111-111111111111") == 403)
verifier("soi-même : refusé", essai("super_admin", "11111111-1111-1111-1111-111111111111",
                                    moi="11111111-1111-1111-1111-111111111111") == 409)
verifier("profil désactivé : refusé", essai("super_admin", "22222222-2222-2222-2222-222222222222") == 404)
verifier("autre super_admin : refusé", essai("super_admin", "33333333-3333-3333-3333-333333333333") == 403)
verifier("profil inconnu : refusé", essai("super_admin", "44444444-4444-4444-4444-444444444444") == 404)

nginx = (RACINE / "nginx" / "nginx.conf").read_text(encoding="utf-8")
verifier("nginx : /api/auth/incarner part au backend",
         "^/api/auth/(connexion|profils|appareils|refresh|incarner)(/|$)" in nginx)
ecran = (RACINE / "frontend" / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
verifier("écran : le bouton pour le seul super_admin, sur un profil actif non administrateur",
         'currentRole === "super_admin" && user.role !== "super_admin" && user.actif' in ecran
         and "Se connecter en tant que" in ecran)
lay = (RACINE / "frontend" / "app" / "(app)" / "layout.tsx").read_text(encoding="utf-8")
verifier("écran : un bandeau tant que la session dure", "user?.incarnePar && <BandeauIncarnation" in lay)

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
