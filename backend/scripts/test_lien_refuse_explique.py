"""
Banc « UN LIEN REFUSÉ DIT POURQUOI » (08/09).

Relevé de Noa (Symbiose) : une employée n'arrive pas à se connecter. L'écran
répondait « Lien invalide ou expiré » dans TOUS les cas, alors que le serveur
distingue quatre situations qui appellent des gestes différents : lien
inconnu, lien déjà utilisé, lien périmé, compte désactivé (et adresse sans
compte). Sans la raison, il faut ouvrir la base pour savoir laquelle — même
faute que le 429 sans cause de Nano Banana (`74e51ba`) ou le refus Drive muet
(`d31262c`).

CE QUE CE BANC PROUVE : `POST /api/auth/magic-link/etat` est EXÉCUTÉE contre
une base doublée sur les six cas ; elle ne MODIFIE jamais rien (aucun
`UPDATE`/`INSERT` ne part) ; elle reste générique sur un jeton inventé
(anti-énumération) ; et l'écran affiche le message rendu. Tombe sur la version
d'avant.
"""
import asyncio
import ast
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ UN LIEN REFUSÉ DIT POURQUOI — {BACKEND.parent}\n")

# ── Une base doublée : une ligne de jeton, un drapeau `actif`, et un journal
#    de tout ce qui a été ÉCRIT (la route ne doit rien écrire). ──
ECRITURES = []


class _Conn:
    def __init__(self, base):
        self.base = base

    async def fetchrow(self, sql, *args):
        if "verification_tokens" in sql:
            return self.base.jeton
        return None

    async def fetchval(self, sql, *args):
        if "actif" in sql:
            return self.base.actif
        return None

    async def execute(self, sql, *args):
        ECRITURES.append(sql.strip()[:60])
        return "UPDATE 1"


class _Base:
    jeton = None
    actif = True

    def __call__(self):
        return self

    async def __aenter__(self):
        return _Conn(self)

    async def __aexit__(self, *a):
        return False


BASE = _Base()

# ── La route, extraite du fichier livré (routers/auth.py tire FastAPI, la
#    base, les mails : on n'exécute QUE la fonction). ──
source = (BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
espace = {
    "get_db": BASE,
    "datetime": datetime, "timezone": timezone,
    "MAGIC_LINK_EXPIRE_MINUTES": 15,
    "router": types.SimpleNamespace(post=lambda *a, **k: (lambda f: f)),
    "VerifyTokenRequest": lambda **kw: types.SimpleNamespace(**kw),
}
trouvee = None
for n in ast.parse(source).body:
    if isinstance(n, ast.AsyncFunctionDef) and n.name == "etat_magic_link":
        n.decorator_list = []
        trouvee = n
verifier("la route `etat_magic_link` existe dans routers/auth.py", trouvee is not None)

if trouvee is not None:
    exec(compile(ast.Module(body=[trouvee], type_ignores=[]), "auth", "exec"), espace)
    etat = espace["etat_magic_link"]

    def demander(**champs):
        ECRITURES.clear()
        return asyncio.run(etat(types.SimpleNamespace(token="T", email="employee@exemple.fr", **champs)))

    futur = datetime.now(timezone.utc) + timedelta(minutes=10)
    passe = datetime.now(timezone.utc) - timedelta(minutes=1)

    BASE.jeton = None
    r = demander()
    verifier("jeton inconnu : réponse GÉNÉRIQUE, l'adresse n'est ni confirmée ni infirmée",
             r["raison"] == "inconnu" and "exemple.fr" not in r["message"]
             and "désactivé" not in r["message"] and "compte" not in r["message"].lower(), r)

    BASE.jeton = {"used": True, "utilisations": 1, "utilisations_max": 1, "expires_at": futur}
    BASE.actif = True
    r = demander()
    verifier("lien déjà utilisé : dit qu'il a servi et qu'il faut en demander un autre",
             r["raison"] == "deja_utilise" and "nouveau" in r["message"], r)

    BASE.jeton = {"used": False, "utilisations": 3, "utilisations_max": 3, "expires_at": futur}
    r = demander()
    verifier("lien à plusieurs usages épuisé : le compteur est dit (3 fois sur 3)",
             r["raison"] == "deja_utilise" and "3 fois sur 3" in r["message"], r)

    BASE.jeton = {"used": False, "utilisations": 0, "utilisations_max": 1, "expires_at": passe}
    r = demander()
    verifier("lien périmé : dit la durée de vie et d'en ouvrir un tout de suite",
             r["raison"] == "expire" and "15 minutes" in r["message"], r)

    BASE.jeton = {"used": False, "utilisations": 0, "utilisations_max": 1, "expires_at": futur}
    BASE.actif = False
    r = demander()
    verifier("COMPTE DÉSACTIVÉ : dit que le lien n'y changera rien, et OÙ le réactiver",
             r["raison"] == "compte_desactive" and "Utilisateurs" in r["message"], r)

    BASE.actif = None
    r = demander()
    verifier("adresse sans compte : dit qu'il faut le créer ou corriger l'orthographe",
             r["raison"] == "compte_absent", r)

    BASE.actif = True
    r = demander()
    verifier("lien encore valable : dit que le serveur n'a pas répondu, sans accuser le lien",
             r["raison"] == "valide", r)

    verifier("la route n'ÉCRIT jamais rien : aucun jeton n'est consommé par un diagnostic",
             ECRITURES == [], ECRITURES)

# ── L'écran ──
page = (FRONTEND / "app" / "(auth)" / "verify" / "page.tsx").read_text(encoding="utf-8")
verifier("l'écran demande la raison au serveur quand la connexion échoue",
         "/api/auth/magic-link/etat" in page and "setRaison" in page)
verifier("…et l'affiche à la place du message unique",
         "{raison ||" in page and "Lien invalide ou expiré</p>" not in page)
verifier("le serveur muet ne casse pas la page (message générique gardé)",
         "catch { /* le serveur ne répond pas" in page)

print(f"\n  (jamais rendu dans un navigateur : le texte affiché se juge à l'écran)")
print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
