"""
Banc de la connexion Google personnelle — sans base, sans réseau, sans Google.

POURQUOI. Chaque utilisateur relie SA boîte Google depuis Paramètres (un
consentement OAuth individuel, durable). Ce banc prouve la mécanique du module
`mail/google_perso.py` — construction du lien de consentement, vérification du
state signé, cache des boîtes reliées — avec des doublures pour la config, le
JWT et la base, puis vérifie statiquement que tous les branchements livrés
sont en place (connecteur, démarrage, écran).

Ce qu'il NE prouve pas : l'échange de code chez Google (réseau) et le rendu de
l'écran (navigateur) — ça, c'est le test en conditions réelles.
"""
import importlib.util
import pathlib
import sys
import types
import urllib.parse

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.parent / "frontend"

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ CONNEXION GOOGLE PERSONNELLE — {BACKEND.parent}\n")

# ── Doublures : config, JWT, base — le module ne touche à rien de vrai ──
reglages = types.SimpleNamespace(
    google_oauth_client_id=None,
    google_oauth_client_secret=None,
    app_url="https://exemple.pluton-consulting.fr",
)
faux_config = types.ModuleType("config")
faux_config.settings = reglages
sys.modules["config"] = faux_config

_jetons: dict[str, dict] = {}
faux_jwt = types.ModuleType("auth.jwt_handler")


def _creer(data, expires_delta=None):
    jeton = f"jeton-{len(_jetons)}"
    _jetons[jeton] = dict(data)
    return jeton


def _decoder(token):
    if token not in _jetons:
        raise ValueError("state inconnu")
    return _jetons[token]


faux_jwt.create_access_token = _creer
faux_jwt.decode_access_token = _decoder
faux_auth = types.ModuleType("auth")
faux_auth.jwt_handler = faux_jwt
sys.modules["auth"] = faux_auth
sys.modules["auth.jwt_handler"] = faux_jwt
sys.modules["database"] = types.ModuleType("database")
sys.modules["database.connection"] = types.ModuleType("database.connection")

spec = importlib.util.spec_from_file_location("google_perso_banc",
                                              BACKEND / "mail" / "google_perso.py")
gp = importlib.util.module_from_spec(spec)
sys.modules["google_perso_banc"] = gp
spec.loader.exec_module(gp)

# ── 1. Le lien de consentement ───────────────────────────────────────
print("1. Le lien de consentement")
verifier("sans client OAuth, configurable() dit non", not gp.configurable())
try:
    gp.lien_autorisation("u-1")
    verifier("sans client OAuth, le lien REFUSE (pas d'URL bancale)", False)
except RuntimeError:
    verifier("sans client OAuth, le lien REFUSE (pas d'URL bancale)", True)

reglages.google_oauth_client_id = "client-banc"
reglages.google_oauth_client_secret = "secret-banc"
verifier("avec le client, configurable() dit oui", gp.configurable())

url = gp.lien_autorisation("utilisateur-42")
params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
verifier("l'URL vise bien Google", url.startswith("https://accounts.google.com/o/oauth2/v2/auth?"))
verifier("le retour revient sur /api/google/retour du domaine de l'app",
         params.get("redirect_uri") == "https://exemple.pluton-consulting.fr/api/google/retour")
verifier("access_type=offline (sinon pas de refresh token)",
         params.get("access_type") == "offline")
verifier("prompt=consent (sinon une reconnexion rend un jeton sans refresh)",
         params.get("prompt") == "consent")
verifier("la lecture Gmail est demandée",
         "gmail.readonly" in params.get("scope", ""))
verifier("l'adresse est demandée (openid email)",
         "email" in params.get("scope", "").split())

# ── 2. Le state signé ────────────────────────────────────────────────
print("\n2. Le state signé")
verifier("le state rend l'identité qu'il porte",
         gp.verifier_state(params["state"]) == "utilisateur-42")
mauvais = _creer({"sub": "utilisateur-42", "usage": "session"})
try:
    gp.verifier_state(mauvais)
    verifier("un JWT d'un AUTRE usage est refusé", False)
except ValueError:
    verifier("un JWT d'un AUTRE usage est refusé", True)
try:
    gp.verifier_state("forge")
    verifier("un state forgé est refusé", False)
except Exception:  # noqa: BLE001
    verifier("un state forgé est refusé", True)

# ── 3. Le cache des boîtes reliées ───────────────────────────────────
print("\n3. Le cache des boîtes reliées")
gp._CACHE = {"nathalie@duret-sols.fr": "refresh-n"}
verifier("une boîte non reliée rend None",
         gp.credentials_pour_boite("eric@duret-sols.fr") is None)
verifier("les boîtes reliées se listent (pour la synchronisation)",
         gp.emails_connectes() == ["nathalie@duret-sols.fr"])
verifier("la casse et les espaces ne comptent pas",
         gp._normaliser("  Nathalie@Duret-Sols.FR ") == "nathalie@duret-sols.fr")
try:
    import google.oauth2.credentials  # noqa: F401
    creds = gp.credentials_pour_boite("Nathalie@duret-sols.fr")
    verifier("une boîte reliée rend des identifiants OAuth",
             creds is not None and creds.refresh_token == "refresh-n")
except ImportError:
    print("  (google-auth absent de ce poste : le chemin positif se joue dans le conteneur)")
reglages.google_oauth_client_id = None
verifier("client OAuth retiré : plus d'identifiants, même boîte reliée",
         gp.credentials_pour_boite("nathalie@duret-sols.fr") is None)

# ── 4. Les branchements livrés (contrôles statiques) ─────────────────
print("\n4. Les branchements livrés")


def source(chemin: pathlib.Path) -> str:
    return chemin.read_text(encoding="utf-8")


verifier("migration 026 : la table connexions_google",
         "connexions_google" in source(BACKEND / "database" / "migrations" / "026_connexions_google.sql"))
gmail = source(BACKEND / "ingestion" / "connectors" / "gmail.py")
# Dans le CORPS de `_service` : la connexion personnelle d'abord, l'emprunt
# d'identité (compte de service) en repli.
corps_service = gmail[gmail.index("def _service("):gmail.index("def _service_annuaire(")]
verifier("connecteur : la connexion personnelle passe AVANT l'emprunt d'identité",
         "credentials_pour_boite" in corps_service
         and corps_service.index("credentials_pour_boite")
             < corps_service.index("_cle_compte_de_service()"))
verifier("synchronisation : les boîtes reliées s'ajoutent et échappent au filtre de domaine",
         "emails_connectes" in gmail and "b in connectees" in gmail)
verifier("lecture : le cache est rafraîchi avant le thread",
         "google_perso.rafraichir()" in source(BACKEND / "mail" / "lecture.py"))
principal = source(BACKEND / "main.py")
verifier("main : routes montées sur /api/google",
         'prefix="/api/google"' in principal)
verifier("main : cache rempli au démarrage (le piège des clés, déjà payé)",
         "rafraichir_google(force=True)" in principal)
verifier("collecte : le client OAuth suffit à choisir Gmail",
         "google_oauth_client_id" in source(BACKEND / "mail" / "collecte.py"))
routeur = source(BACKEND / "routers" / "google_perso.py")
verifier("routeur : le refresh token ne sort jamais par l'API",
         "refresh_token" not in routeur.replace('infos["refresh_token"]', ""))
ecran = source(FRONTEND / "app" / "(app)" / "parametres" / "SettingsClient.tsx")
verifier("écran : l'onglet Mon compte Google existe, sans restriction de rôle",
         '{ key: "google", label: "Mon compte Google" }' in ecran)
verifier("écran : la page Paramètres ne rejette plus les collaborateurs",
         '["super_admin", "direction"].includes' not in source(
             FRONTEND / "app" / "(app)" / "parametres" / "page.tsx"))
verifier("navigation : Paramètres visible de tous les rôles",
         source(FRONTEND / "lib" / "permissions.ts").count(
             'href: "/parametres",  roles: ALL_ROLES') >= 1
         or 'roles: ALL_ROLES,\n  },' in source(FRONTEND / "lib" / "permissions.ts"))

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
