"""
Banc de la SESSION D'APPAREIL — se connecter une fois, plus jamais ensuite.

LA DEMANDE (03/09, Noa) : « il faudrait que chacun puisse se connecter avec son
mail comme actuellement mais sans resaisir le mail et sans aller cliquer sur le
magic link à chaque fois car ça prend beaucoup trop de temps. »

CE QUE CE BANC PROUVE, sans base ni réseau :
  · le module `auth/appareil.py` est EXÉCUTÉ contre une base doublée — ce n'est
    pas une relecture de source. On vérifie ce qui compte vraiment : la base ne
    reçoit JAMAIS le jeton en clair, une session révoquée ou échue ne rend
    aucun compte, et un identifiant deviné ne ferme pas la session d'autrui ;
  · la migration absente ne casse pas la connexion — elle la raccourcit ;
  · la chaîne d'écran tient : le JWT se renouvelle tout seul, « Se déconnecter »
    ferme vraiment l'appareil, et un 401 dans un onglet resté ouvert ne renvoie
    plus à /login avant d'avoir essayé de reprendre la session.

Il TOMBE sur la version d'avant (aucun de ces fichiers n'existait) : c'est la
condition pour qu'un banc vert veuille dire quelque chose.
"""
import asyncio
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
RACINE = BACKEND.resolve().parent
FRONTEND = RACINE / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ SESSION D'APPAREIL — {RACINE}\n")

source = BACKEND / "auth" / "appareil.py"
if not source.exists():
    print("  ✗ backend/auth/appareil.py est absent — la session d'appareil n'existe pas.")
    sys.exit(1)


# ── LA BASE DOUBLÉE ───────────────────────────────────────────────────────
# Elle enregistre CE QUI LUI EST PASSÉ : c'est ainsi qu'on prouve qu'aucun
# jeton en clair ne la traverse.
class TableAbsente(Exception):
    """Ce que lève asyncpg quand la migration n'est pas appliquée."""
    def __str__(self):
        return 'relation "sessions_appareil" does not exist'


class ConnexionDoublee:
    def __init__(self, base):
        self.base = base

    async def execute(self, sql, *args):
        self.base.appels.append((sql, args))
        if self.base.table_absente:
            raise TableAbsente()
        return self.base.retour_execute

    async def fetchrow(self, sql, *args):
        self.base.appels.append((sql, args))
        if self.base.table_absente:
            raise TableAbsente()
        return self.base.ligne

    async def fetch(self, sql, *args):
        self.base.appels.append((sql, args))
        if self.base.table_absente:
            raise TableAbsente()
        return self.base.lignes


class BaseDoublee:
    def __init__(self):
        self.appels = []
        self.ligne = None
        self.lignes = []
        self.retour_execute = "UPDATE 1"
        self.table_absente = False

    def __call__(self):
        base = self

        class Ctx:
            async def __aenter__(self):
                return ConnexionDoublee(base)

            async def __aexit__(self, *a):
                return False

        return Ctx()


BASE = BaseDoublee()


def schema_incomplet_double(e):
    texte = str(e).lower()
    return "does not exist" in texte and ("relation" in texte or "table" in texte)


# ── LE MODULE LIVRÉ, CHARGÉ AVEC SES VRAIS IMPORTS ────────────────────────
reglages = types.SimpleNamespace(session_appareil_jours=0, jwt_expire_hours=24)
mod_config = types.ModuleType("config")
mod_config.settings = reglages
mod_db = types.ModuleType("database")
mod_conn = types.ModuleType("database.connection")
mod_conn.get_db = BASE
mod_conn.schema_incomplet = schema_incomplet_double
sys.modules["config"] = mod_config
sys.modules["database"] = mod_db
sys.modules["database.connection"] = mod_conn

appareil = types.ModuleType("appareil")
appareil.__dict__["__file__"] = str(source)
exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), appareil.__dict__)


# ── 1. NOMMER L'APPAREIL — pour s'y reconnaître dans la liste ─────────────
nommer = appareil.nommer_appareil
verifier("« Chrome sur Mac » se lit tel quel",
         nommer("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/128.0 Safari/537.36") == "Chrome sur Mac",
         nommer("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/128.0 Safari/537.36"))
verifier("Safari sur iPhone n'est pas confondu avec Chrome",
         nommer("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1 "
                "Version/17.0 Mobile/15E148 Safari/604.1") == "Safari sur iPhone")
verifier("Edge ne se déclare pas « Chrome » (l'ordre de lecture compte)",
         nommer("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "Chrome/128.0 Safari/537.36 Edg/128.0") == "Edge sur Windows")
verifier("Firefox sur Windows aussi",
         nommer("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0")
         == "Firefox sur Windows")
verifier("un en-tête vide ne met pas une chaîne technique à l'écran",
         nommer("") == "Appareil inconnu" and nommer(None) == "Appareil inconnu")


# ── 2. L'EMPREINTE — la base ne voit jamais le jeton ──────────────────────
h = appareil.hacher("jeton-de-test")
verifier("l'empreinte est un SHA-256 (64 hexa), stable",
         len(h) == 64 and h == appareil.hacher("jeton-de-test") and all(c in "0123456789abcdef" for c in h))
verifier("deux jetons différents ne se confondent pas",
         appareil.hacher("a") != appareil.hacher("b"))


# ── 3. L'ÉCHÉANCE — 0 veut dire ILLIMITÉ (décision de Noa) ────────────────
reglages.session_appareil_jours = 0
verifier("sans réglage, la session n'a pas d'échéance", appareil.expiration() is None)
reglages.session_appareil_jours = 30
depart = datetime(2026, 9, 3, tzinfo=timezone.utc)
verifier("un réglage à 30 jours pose une échéance glissante",
         appareil.expiration(depart) == depart + timedelta(days=30))
reglages.session_appareil_jours = 0


# ── 4. OUVRIR UNE SESSION — le jeton en clair ne part pas en base ─────────
BASE.appels.clear()
jeton = asyncio.run(appareil.creer("user-1", "Mozilla/5.0 (Macintosh) Chrome/128.0 Safari/537.36"))
verifier("un jeton long est rendu à l'appelant", bool(jeton) and len(jeton) >= 32)
ecrits = [a for sql, a in BASE.appels if "INSERT INTO sessions_appareil" in sql]
verifier("l'INSERT a bien eu lieu", len(ecrits) == 1)
args = ecrits[0] if ecrits else ()
verifier("LA BASE NE REÇOIT JAMAIS LE JETON EN CLAIR",
         jeton not in [str(a) for a in args], str(args))
verifier("c'est bien son empreinte qui est écrite", appareil.hacher(jeton) in [str(a) for a in args])
verifier("l'appareil est nommé lisiblement dans la ligne", "Chrome sur Mac" in [str(a) for a in args])
verifier("aucune échéance n'est posée quand la session est illimitée",
         any(a is None for a in args))


# ── 5. MIGRATION ABSENTE — la connexion marche encore, en plus court ──────
BASE.table_absente = True
BASE.appels.clear()
sans_table = asyncio.run(appareil.creer("user-1", "Chrome"))
verifier("sans la table, ouvrir une session rend None au lieu de planter",
         sans_table is None)
verifier("sans la table, la liste dit « je ne sais pas » et non « aucun appareil »",
         asyncio.run(appareil.lister("user-1")) is None)
verifier("sans la table, aucun compte n'est rendu",
         asyncio.run(appareil.compte_de("peu importe")) is None)
BASE.table_absente = False


# ── 6. REPRENDRE LA MAIN — le jeton rend un compte, et prolonge la ligne ──
BASE.appels.clear()
BASE.ligne = {"id": "sess-1", "expire_le": None, "user_id": "user-1",
              "email": "quelqu-un@exemple.fr", "role": "direction"}
compte = asyncio.run(appareil.compte_de(jeton))
verifier("un jeton vivant rend le compte, avec son rôle",
         compte and compte["user_id"] == "user-1" and compte["role"] == "direction")
lu = [(sql, a) for sql, a in BASE.appels if "SELECT" in sql]
verifier("la lecture se fait par EMPREINTE, jamais par jeton",
         lu and appareil.hacher(jeton) in [str(x) for x in lu[0][1]] and jeton not in [str(x) for x in lu[0][1]])
sql_lecture = lu[0][0] if lu else ""
verifier("une session révoquée ne peut pas être lue (clause dans le SQL)",
         "revoque_le IS NULL" in sql_lecture)
verifier("un compte désactivé ne peut plus rien rouvrir",
         "u.actif = true" in sql_lecture)
verifier("l'usage prolonge la ligne (date et échéance mises à jour)",
         any("UPDATE sessions_appareil" in sql and "derniere_utilisation" in sql
             for sql, _ in BASE.appels))

BASE.ligne = None
verifier("un jeton inconnu ne rend aucun compte", asyncio.run(appareil.compte_de(jeton)) is None)
verifier("un jeton vide non plus", asyncio.run(appareil.compte_de("")) is None)

BASE.ligne = {"id": "sess-2", "expire_le": datetime.now(timezone.utc) - timedelta(days=1),
              "user_id": "user-1", "email": "x@y.fr", "role": "terrain"}
verifier("une échéance passée ferme la porte", asyncio.run(appareil.compte_de(jeton)) is None)
BASE.ligne = None


# ── 7. FERMER — et ne fermer que ce qui est à soi ─────────────────────────
BASE.appels.clear()
BASE.retour_execute = "UPDATE 1"
verifier("« Se déconnecter » ferme la session de cet appareil",
         asyncio.run(appareil.revoquer(jeton)) is True)
BASE.retour_execute = "UPDATE 0"
verifier("fermer deux fois ne ment pas (rien à fermer = False)",
         asyncio.run(appareil.revoquer(jeton)) is False)

BASE.appels.clear()
BASE.retour_execute = "UPDATE 1"
asyncio.run(appareil.revoquer_une("user-1", "sess-42"))
sql_une = [sql for sql, _ in BASE.appels if "UPDATE sessions_appareil" in sql]
verifier("fermer UN appareil exige que la ligne soit à SOI (user_id dans le WHERE)",
         sql_une and "user_id = $2" in sql_une[0], str(sql_une))

BASE.retour_execute = "UPDATE 3"
verifier("« fermer tous mes appareils » dit combien il en a fermé",
         asyncio.run(appareil.revoquer_tout("user-1")) == 3)


# ── 8. LE BACKEND : les routes, et le lien magique qui pose la session ────
routeur = (BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
verifier("la vérification du lien magique ouvre la session de l'appareil",
         "appareil.creer(" in routeur and '"refresh_token"' in routeur)
verifier("une route échange le jeton d'appareil contre un JWT frais",
         '@router.post("/refresh")' in routeur and "appareil.compte_de(" in routeur)
verifier("le refus de rafraîchissement ne dit pas POURQUOI (pas de diagnostic à qui présente un jeton)",
         "Session close : reconnectez-vous." in routeur)
verifier("« Se déconnecter » ferme l'appareil SANS exiger un JWT encore valide",
         '@router.post("/appareils/fermer-jeton")' in routeur)
verifier("chacun peut voir et fermer ses appareils",
         '@router.get("/appareils")' in routeur
         and '@router.delete("/appareils/{session_id}")' in routeur
         and '@router.post("/appareils/tout-fermer")' in routeur)
verifier("la déconnexion classique ferme aussi la session durable",
         "if body and body.refresh_token" in routeur)

users = (BACKEND / "routers" / "users.py").read_text(encoding="utf-8")
verifier("désactiver un compte ferme ses appareils",
         "appareil.revoquer_tout(user_id)" in users)

config = (BACKEND / "config.py").read_text(encoding="utf-8")
verifier("le réglage existe et vaut 0 (illimité) par défaut",
         "session_appareil_jours: int = 0" in config)
exemple = (RACINE / ".env.example").read_text(encoding="utf-8")
verifier("le .env d'exemple le documente", "SESSION_APPAREIL_JOURS=0" in exemple)

migration = BACKEND / "database" / "migrations" / "034_sessions_appareil.sql"
verifier("la migration 034 existe", migration.exists())
if migration.exists():
    sql = migration.read_text(encoding="utf-8")
    verifier("elle est idempotente (rejouable sans dommage)",
             "CREATE TABLE IF NOT EXISTS sessions_appareil" in sql
             and "CREATE INDEX IF NOT EXISTS" in sql)
    verifier("elle stocke une EMPREINTE, pas un jeton",
             "jeton_hash" in sql and "UNIQUE" in sql)
    verifier("une session fermée reste tracée plutôt qu'effacée", "revoque_le" in sql)


# ── 9. L'ÉCRAN : plus de lien magique quotidien ───────────────────────────
auth_ts = (FRONTEND / "lib" / "auth.ts").read_text(encoding="utf-8")
verifier("la session d'écran dure un an (plafond des navigateurs)",
         "maxAge: 60 * 60 * 24 * 400" in auth_ts)
verifier("le JWT se renouvelle tout seul avec le jeton d'appareil",
         "/api/auth/refresh" in auth_ts and "refreshToken" in auth_ts)
verifier("un backend injoignable ne déconnecte PAS tout le monde",
         "return undefined" in auth_ts and "if (neuf === undefined) return token" in auth_ts)
verifier("« Se déconnecter » ferme l'appareil côté serveur",
         "appareils/fermer-jeton" in auth_ts and "signOut" in auth_ts)

verifier("un jeton frais se redemande sans quitter la page",
         (FRONTEND / "lib" / "session.ts").exists())
chat = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("un 401 dans un onglet ouvert tente la reprise AVANT de renvoyer à /login",
         chat.find("const frais = await jetonFrais()") != -1
         and chat.find("const frais = await jetonFrais()") < chat.find('window.location.assign("/login")'))

login = (FRONTEND / "app" / "(auth)" / "login" / "page.tsx").read_text(encoding="utf-8")
verifier("l'écran de connexion pré-remplit la dernière adresse",
         "CLE_DERNIER_EMAIL" in login and "localStorage.getItem" in login)
verifier("« utiliser un autre email » vide vraiment le champ",
         "changerDAdresse" in login and "removeItem(CLE_DERNIER_EMAIL)" in login)

reglages_ecran = (FRONTEND / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
verifier("l'onglet « Mes appareils » est déclaré, pour tous les rôles",
         '{ key: "appareils", label: "Mes appareils" }' in reglages_ecran
         and "<AppareilsTab" in reglages_ecran)
onglet = FRONTEND / "components" / "settings" / "AppareilsTab.tsx"
verifier("l'onglet existe et sait fermer un appareil", onglet.exists()
         and "appareils/tout-fermer" in onglet.read_text(encoding="utf-8"))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
