"""
Banc « LE CODE D'UNE CARTE NE S'OUVRE PAS TOUT SEUL » — audit du 15/09, fiche D-19.

CE QUI ÉTAIT FAUX. `controler_code` rendait `None` pour dire « entre », et
rendait `None` aussi quand elle ne POUVAIT PAS vérifier : schéma incomplet
(migrations 041/042 non appliquées), profil inconnu, empreinte absente. Une
base en cours de migration ouvrait donc l'entrée administrateur. Le code de
première entrée du serveur était en outre un secret PERMANENT, et le compte des
essais se lisait puis se réécrivait — deux essais simultanés se recouvraient.

CE BANC PROUVE (base doublée, fonctions EXÉCUTÉES) :
  1. le verdict est typé et FAIL-CLOSED : schéma incomplet, profil inconnu ou
     empreinte absente REFUSENT dès qu'un code est exigé ; un profil ordinaire
     sans code garde son entrée d'un clic ;
  2. le compte des essais tient sous verrou de ligne (`FOR UPDATE`), dans une
     transaction ; un succès ne remet à zéro que CE profil ;
  3. le code de PREMIÈRE ENTRÉE ne sert qu'une fois, oblige à en poser un vrai,
     et sans la migration 044 il est refusé (jamais permanent) ;
  4. la clé qui chiffre les codes relisibles est SÉPARÉE du secret JWT, les
     anciens chiffrés restent lisibles et se réécrivent avec la nouvelle clé ;
  5. le câblage : statuts HTTP, limitation par origine, réponse « code à
     changer », panneau d'écran, script d'exploitation, migration, journal.

Usage : python backend/scripts/test_code_admin.py [backend]
"""
import asyncio
import importlib.util
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def poser(nom, **attrs):
    mod = types.ModuleType(nom)
    mod.__dict__.update(attrs)
    mod.__path__ = []
    sys.modules[nom] = mod
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            poser(parent)
        setattr(sys.modules[parent], feuille, mod)
    return mod


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, BACKEND / chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            poser(parent)
        setattr(sys.modules[parent], feuille, mod)
    spec.loader.exec_module(mod)
    return mod


print(f"\n═══ LE CODE ADMINISTRATEUR — {BACKEND.parent}\n")

# ── La base doublée : une ligne de `users`, des requêtes enregistrées ───────
class ColonneAbsente(Exception):
    """Ce que rend Postgres quand la migration n'est pas appliquée."""

    def __str__(self):
        return 'column "code_defaut_le" of relation "users" does not exist'


class Conn:
    def __init__(self, base):
        self.base = base
        self.requetes = []
        self.transactions = 0

    def transaction(self):
        conn = self

        class _T:
            async def __aenter__(self):
                conn.transactions += 1
                return None

            async def __aexit__(self, *a):
                return False
        return _T()

    async def fetchrow(self, requete, *args):
        self.requetes.append(requete)
        if "code_defaut_le" in requete and "NULL::timestamptz" not in requete and not self.base["a_044"]:
            raise ColonneAbsente()
        ligne = self.base["users"].get(str(args[0]))
        if ligne is None:
            return None
        fiche = dict(ligne)
        if "NULL::timestamptz" in requete:
            fiche["code_defaut_le"] = None
        return fiche

    async def execute(self, requete, *args):
        self.requetes.append(requete)
        if "code_defaut_le" in requete and not self.base["a_044"]:
            raise ColonneAbsente()
        ligne = self.base["users"].get(str(args[0]))
        if ligne is None:
            return
        if "code_pin_echecs = 0" in requete:
            ligne["code_pin_echecs"] = 0
            ligne["code_pin_bloque_jusqu"] = args[1] if "bloque_jusqu = $2" in requete else None
            if "code_defaut_le = $2" in requete:
                ligne["code_defaut_le"] = args[1]
                ligne["code_pin_bloque_jusqu"] = None
        elif "code_pin_echecs = $2" in requete:
            ligne["code_pin_echecs"] = args[1]


BASE = {"a_044": True, "users": {}}
CONNEXIONS = []


class _Db:
    async def __aenter__(self):
        conn = Conn(BASE)
        CONNEXIONS.append(conn)
        return conn

    async def __aexit__(self, *a):
        return False


def schema_incomplet(e):
    texte = str(e).lower()
    return "does not exist" in texte and ("column" in texte or "relation" in texte)


poser("database")
poser("database.connection", get_db=lambda: _Db(), schema_incomplet=schema_incomplet)
poser("config", settings=types.SimpleNamespace(jwt_secret_key="secret-de-session",
                                               code_chiffrement_cle="", code_admin_defaut="0000"))
poser("llm")
poser("llm.cles")
poser("mail")
poser("mail.imap", boite_unique=lambda: None)
profils = charger("auth.profils", "auth/profils.py")


def poser_profil(ident, code=None, echecs=0, bloque=None, defaut_le=None):
    BASE["users"][ident] = {"code_pin_hash": profils.hacher_code(code) if code else None,
                            "code_pin_echecs": echecs, "code_pin_bloque_jusqu": bloque,
                            "code_defaut_le": defaut_le}


def controler(ident, code, **kw):
    return asyncio.run(profils.controler_code(ident, code, **kw))


print("1. Fail-closed : ce qui ne peut pas être vérifié n'ouvre pas")
poser_profil("carte-sans-code")
poser_profil("carte-a-code", code="4321")
verifier("un profil ordinaire sans code entre d'un clic (le comportement d'avant)",
         controler("carte-sans-code", None).ok)
verifier("un profil INCONNU est refusé dès qu'un code est exigé, permis sinon",
         not controler("inconnu", "4321", exige=True).ok
         and controler("inconnu", "4321", exige=True).raison == "indisponible"
         and controler("inconnu", None).ok)
verifier("une carte à code sans empreinte lisible est refusée (jamais ouverte par défaut)",
         not controler("carte-sans-code", "4321", exige=True).ok)
BASE["users"]["carte-a-code"]["code_pin_hash"] = "empreinte-illisible"
verifier("une empreinte illisible ne vaut pas autorisation",
         not controler("carte-a-code", "4321", exige=True).ok)
poser_profil("carte-a-code", code="4321")
verifier("le bon code ouvre, et remet le compteur d'essais à zéro",
         controler("carte-a-code", "4321", exige=True).ok
         and BASE["users"]["carte-a-code"]["code_pin_echecs"] == 0)
verifier("un code faux refuse sans rien apprendre d'autre",
         controler("carte-a-code", "0000", exige=True).raison == "code_faux"
         and BASE["users"]["carte-a-code"]["code_pin_echecs"] == 1)
verifier("un code absent se dit « requis », pas « faux »",
         controler("carte-a-code", "", exige=True).raison == "code_requis")
for _ in range(profils.ESSAIS_CODE_MAX - 2):
    controler("carte-a-code", "0000", exige=True)
verdict = controler("carte-a-code", "0000", exige=True)
verifier("au cinquième essai, la carte est bloquée un quart d'heure",
         verdict.raison == "code_bloque" and BASE["users"]["carte-a-code"]["code_pin_bloque_jusqu"] is not None)
verifier("une carte bloquée refuse même le BON code, sans consommer d'essai",
         controler("carte-a-code", "4321", exige=True).raison == "code_bloque")

print("2. Le compte des essais tient sous verrou, et par profil")
poser_profil("a", code="1111")
poser_profil("b", code="2222", echecs=3)
CONNEXIONS.clear()
controler("a", "9999", exige=True)
verifier("la ligne est lue FOR UPDATE, dans une transaction",
         any("FOR UPDATE" in r for r in CONNEXIONS[-1].requetes) and CONNEXIONS[-1].transactions == 1,
         CONNEXIONS[-1].requetes)
controler("a", "1111", exige=True)
verifier("un succès ne remet à zéro que le compteur de CE profil",
         BASE["users"]["a"]["code_pin_echecs"] == 0 and BASE["users"]["b"]["code_pin_echecs"] == 3)
source = (BACKEND / "auth" / "profils.py").read_text(encoding="utf-8")
verifier("le contrôle n'écrit plus le compteur hors de la transaction qui l'a lu",
         "async with conn.transaction():" in source and "FOR UPDATE" in source)

print("3. Le code de première entrée ne sert QU'UNE FOIS")
poser_profil("admin")
premier = controler("admin", "0000", defaut="0000", exige=True)
verifier("l'administrateur sans code entre avec le code de première entrée, et doit en poser un",
         premier.ok and premier.doit_changer and BASE["users"]["admin"]["code_defaut_le"] is not None)
verifier("il ne sert PAS deux fois : la seconde entrée dit qu'il faut en poser un",
         controler("admin", "0000", defaut="0000", exige=True).raison == "code_a_poser")
poser_profil("admin2")
verifier("un code faux en première entrée refuse et compte l'essai",
         controler("admin2", "1234", defaut="0000", exige=True).raison == "code_faux"
         and BASE["users"]["admin2"]["code_pin_echecs"] == 1
         and BASE["users"]["admin2"]["code_defaut_le"] is None)
BASE["a_044"] = False
poser_profil("admin3")
verifier("sans la migration 044, le code de première entrée est REFUSÉ (jamais permanent)",
         controler("admin3", "0000", defaut="0000", exige=True).raison == "indisponible")
verifier("sans les migrations du tout, une carte à code refuse aussi",
         controler("admin3", "0000", exige=True).raison == "indisponible")
BASE["a_044"] = True
sys.modules["config"].settings.code_admin_defaut = ""
poser_profil("admin5")
verifier("sans code posé ET sans code de première entrée, l'écran dit qu'il faut en poser un",
         controler("admin5", "0000", defaut="", exige=True).raison == "code_a_poser")
sys.modules["config"].settings.code_admin_defaut = "0000"
poser_profil("admin4", code="7777")
verifier("un administrateur qui a SON code n'est pas concerné par celui de première entrée",
         controler("admin4", "7777", defaut="0000", exige=True).ok
         and controler("admin4", "0000", defaut="0000", exige=True).raison == "code_faux")

print("4. La clé des codes relisibles est séparée du secret JWT")
try:
    import cryptography  # noqa: F401
    dispo = True
except ImportError:
    dispo = False
if not dispo:
    print("  (cryptography absent : section non jouée — elle l'est dans le conteneur)")
else:
    reglages = sys.modules["config"].settings
    reglages.code_chiffrement_cle = ""
    ancien = profils.chiffrer_code("4321")            # chiffré à l'ancienne (secret JWT)
    reglages.code_chiffrement_cle = "cle-dediee-aux-codes"
    neuf = profils.chiffrer_code("4321")
    verifier("un code chiffré avec l'ANCIENNE clé reste lisible", profils.dechiffrer_code(ancien) == "4321")
    verifier("un code neuf est chiffré avec la clé dédiée", profils.dechiffrer_code(neuf) == "4321" and neuf != ancien)
    rechiffre = profils.rechiffre_avec_la_cle_du_jour(ancien)
    verifier("relire un ancien code le RÉÉCRIT avec la clé du jour (rotation sans perte)",
             rechiffre and profils.dechiffrer_code(rechiffre) == "4321")
    verifier("un code déjà à jour n'est pas réécrit pour rien", profils.rechiffre_avec_la_cle_du_jour(neuf) is None)
    reglages.jwt_secret_key = "un-autre-secret-de-session"
    verifier("changer le secret des sessions ne rend plus les codes illisibles",
             profils.dechiffrer_code(neuf) == "4321")
    reglages.code_chiffrement_cle = "encore-une-autre-cle"
    verifier("changer la clé DES CODES, elle, les rend illisibles — pas une panne, un état",
             profils.dechiffrer_code(neuf) is None)
    reglages.code_chiffrement_cle = ""
    reglages.jwt_secret_key = "secret-de-session"

print("4 bis. La borne par origine, exécutée")
tentatives = charger("security.tentatives", "security/tentatives.py")
T0 = 10_000.0
verifier("l'origine vient de X-Forwarded-For (nginx), sinon de la connexion",
         tentatives.origine_de("203.0.113.7, 10.0.0.1", "10.0.0.1") == "203.0.113.7"
         and tentatives.origine_de("", "10.0.0.2") == "10.0.0.2"
         and tentatives.origine_de("", "") == "inconnue")
for i in range(tentatives.ESSAIS_MAX):
    tentatives.noter_echec("203.0.113.7", T0 + i)
verifier("une origine qui enchaîne les essais ratés est bornée, les autres ne le sont pas",
         tentatives.saturee("203.0.113.7", T0 + 60) and not tentatives.saturee("10.0.0.2", T0 + 60))
verifier("la fenêtre s'oublie seule (un quart d'heure plus tard, on réessaie)",
         not tentatives.saturee("203.0.113.7", T0 + tentatives.FENETRE_S + 1))
tentatives.noter_echec("10.0.0.2", T0)
tentatives.oublier("10.0.0.2")
verifier("une entrée réussie efface les essais ratés de son origine",
         not tentatives.saturee("10.0.0.2", T0) and tentatives._ESSAIS.get("10.0.0.2") is None)

print("5. Le câblage : routes, écran, exploitation")
routes = (BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
verifier("les routes lisent le VERDICT, jamais « None vaut oui »",
         "verdict = await _profils.controler_code(" in routes and "if verdict.ok:" in routes
         and "exige=True" in routes)
verifier("un refus technique n'est pas une erreur de la personne (503), un blocage est un 429",
         'status.HTTP_503_SERVICE_UNAVAILABLE' in routes and '"code_bloque": status.HTTP_429' in routes)
verifier("les routes bornent aussi PAR ORIGINE (et oublient une entrée réussie)",
         "tentatives.saturee(_origine(request))" in routes and "tentatives.noter_echec(" in routes
         and "tentatives.oublier(" in routes and "x-forwarded-for" in routes)
verifier("l'entrée par le code de première entrée dit à l'écran d'en poser un",
         '"code_a_changer": bool(verdict.doit_changer)' in routes)
ecran = (FRONTEND / "components" / "nav" / "CodeAPoser.tsx").read_text(encoding="utf-8")
layout = (FRONTEND / "app" / "(app)" / "layout.tsx").read_text(encoding="utf-8")
verifier("l'écran fait poser un vrai code, et le panneau ne se referme pas sans lui",
         "/api/users/me/code" in ecran and "code_par_defaut" in ecran
         and '<CodeAPoser jeton={jeton} />' in layout and 'role === "super_admin"' in layout)
carte = (FRONTEND / "components" / "nav" / "CodeCarte.tsx").read_text(encoding="utf-8")
authts = (FRONTEND / "lib" / "auth.ts").read_text(encoding="utf-8")
verifier("les nouveaux refus sont dits en français à l'écran",
         all(r in carte for r in ("code_a_poser", "indisponible", "origine_bloquee"))
         and all(r in authts for r in ("code_a_poser", "indisponible", "origine_bloquee")))
migration = BACKEND / "database" / "migrations" / "044_code_admin_premiere_entree.sql"
verifier("la migration 044 existe et est idempotente",
         migration.exists() and "ADD COLUMN IF NOT EXISTS code_defaut_le" in migration.read_text(encoding="utf-8"))
script = (BACKEND / "scripts" / "code_admin.py").read_text(encoding="utf-8")
verifier("la reprise de secours existe HORS de l'interface, et ne lit jamais un code existant",
         "--profil" in script and "hacher_code(code)" in script and "dechiffrer_code" not in script)
users = (BACKEND / "routers" / "users.py").read_text(encoding="utf-8")
verifier("lire le code de quelqu'un d'autre est journalisé, sans le code",
         'action="codes_cartes_consultes"' in users and '"code": d["code"]' not in users)
exemple = (BACKEND.parent / ".env.example").read_text(encoding="utf-8")
verifier("le .env.example nomme les deux réglages, sans publier de code",
         "CODE_ADMIN_DEFAUT=" in exemple and "CODE_CHIFFREMENT_CLE=" in exemple
         and "CODE_ADMIN_DEFAUT=0000" not in exemple)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
