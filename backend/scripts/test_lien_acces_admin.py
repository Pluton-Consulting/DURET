"""
Banc du LIEN D'ACCÈS DÉLIVRÉ À LA MAIN — quand le mail de connexion n'arrive pas.

LA DEMANDE (03/09, Noa) : « avec mon compte admin, pouvoir leur faire accéder à
l'interface même s'ils ne reçoivent pas le mail magique. »

CE QUI SE PASSAIT. Toute l'entrée dépendait de l'arrivée d'un mail. Boîte mal
configurée, message en indésirables, salarié sans accès à sa messagerie, poste
qu'on installe pour quelqu'un : il fallait réparer la messagerie AVANT de
pouvoir ouvrir l'accès. L'administration n'avait aucun recours.

CE QUE CE BANC PROUVE, sans base ni réseau :
  · la hiérarchie est EXÉCUTÉE — la direction ne se fabrique pas un accès
    super_admin, un rôle métier ne fabrique rien du tout ;
  · le lien n'est pas une porte dérobée : même table, même page /verify, même
    usage unique que le lien du mail. Seul le TRANSPORT change ;
  · un compte désactivé ne reçoit pas de lien, et on dit quoi faire ;
  · l'adresse est encodée dans l'URL (un « + » se décoderait en espace) ;
  · l'écran prévient que le lien ouvre la session à la place de la personne.

Il TOMBE sur la version d'avant : ni la route ni le bouton n'existaient.
"""
import ast
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
RACINE = BACKEND.resolve().parent
FRONTEND = RACINE / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LIEN D'ACCÈS DÉLIVRÉ PAR L'ADMINISTRATION — {RACINE}\n")

users_py = (BACKEND / "routers" / "users.py").read_text(encoding="utf-8")

# ── 1. LA HIÉRARCHIE, EXÉCUTÉE ────────────────────────────────────────────
# On extrait la garde du module LIVRÉ : l'importer en entier exigerait fastapi
# et asyncpg, absents de ce Mac.
voulu = {"peut_ouvrir_pour", "DIRECTION_CREATABLE_ROLES", "SUPER_ADMIN_CREATABLE_ROLES",
         "LIEN_ACCES_EXPIRE_HEURES"}
gardes = []
for n in ast.parse(users_py).body:
    if isinstance(n, ast.FunctionDef) and n.name in voulu:
        gardes.append(n)
    elif isinstance(n, ast.Assign):
        if any(isinstance(c, ast.Name) and c.id in voulu for c in n.targets):
            gardes.append(n)
espace = {}
if gardes:
    exec(compile(ast.Module(body=gardes, type_ignores=[]), "users", "exec"), espace)
manquants = voulu - set(espace)
verifier("la garde et ses constantes existent dans le module livré", not manquants, str(manquants))

if not manquants:
    peut = espace["peut_ouvrir_pour"]
    verifier("un super_admin peut ouvrir pour n'importe qui",
             peut("super_admin", "terrain") and peut("super_admin", "direction")
             and peut("super_admin", "super_admin"))
    verifier("la direction peut ouvrir pour les rôles métier",
             peut("direction", "terrain") and peut("direction", "commercial")
             and peut("direction", "bureau_etudes"))
    verifier("LA DIRECTION NE SE FABRIQUE PAS UN ACCÈS SUPER_ADMIN",
             not peut("direction", "super_admin"))
    verifier("ni un accès direction (elle ouvrirait la porte d'à côté)",
             not peut("direction", "direction"))
    verifier("un rôle métier n'ouvre rien du tout",
             not peut("commercial", "terrain") and not peut("terrain", "terrain")
             and not peut("administratif", "commercial"))
    verifier("le lien vaut 24 h — il voyage par un humain, pas par un mail",
             espace["LIEN_ACCES_EXPIRE_HEURES"] == 24)

# ── 2. LA ROUTE : rien n'est contourné, seul le transport change ──────────
verifier("la route existe", '@router.post("/{user_id}/lien-connexion")' in users_py)
verifier("elle exige la permission de gérer les utilisateurs",
         'has_permission(current_user.role, "manage_users")' in users_py)
verifier("elle applique la hiérarchie côté SERVEUR (un écran ne suffit pas)",
         "peut_ouvrir_pour(current_user.role, cible[\"role\"])" in users_py)
verifier("un compte désactivé ne reçoit pas de lien, et on dit quoi faire",
         'if not cible["actif"]' in users_py
         and "réactivez-le avant de créer un lien" in users_py)
verifier("le lien passe par la MÊME table que le lien du mail (donc à usage unique)",
         "INSERT INTO verification_tokens" in users_py)
verifier("il mène à la MÊME page de vérification",
         '/verify"' in users_py and "token=" in users_py)
verifier("le jeton est un vrai aléa, pas un identifiant devinable",
         "secrets.token_urlsafe(32)" in users_py)
verifier("l'adresse ET le jeton sont encodés (un « + » se décoderait en espace)",
         "quote(jeton, safe='')" in users_py and "quote(cible['email'], safe='')" in users_py)
verifier("la délivrance est tracée dans l'audit",
         'action="lien_acces_cree"' in users_py)
verifier("l'audit ne recopie pas l'adresse de la personne",
         "target_email" not in users_py)

# ── 3. L'ÉCRAN : le bouton, et l'avertissement qui va avec ───────────────
ecran = (FRONTEND / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
verifier("le bouton « Lien d'accès » est dans la liste des utilisateurs",
         "Lien d'accès" in ecran and "creerLienAcces" in ecran)
verifier("il appelle la bonne route", "/lien-connexion" in ecran)
verifier("il ne s'affiche pas pour un compte désactivé",
         "user.actif && (currentRole ===" in ecran)
verifier("l'écran dit que le lien ouvre la session À LA PLACE de la personne",
         "ouvre la session à sa place" in ecran)
verifier("il dit qu'il ne sert QU'UNE FOIS et qu'il expire",
         "qu'une fois" in ecran and "expire dans {lienAcces.valable_heures}" in ecran)
verifier("il dit la suite : l'appareil restera connecté",
         "restera connecté" in ecran)
verifier("le lien se copie, et un presse-papiers refusé est DIT",
         "clipboard.writeText" in ecran and "copiez-le à la main" in ecran)


# ── 4. PLUSIEURS UTILISATIONS : PC + téléphone (03/09, migration 035) ────
# « Quand je crée un lien, je dois pouvoir choisir le nombre d'utilisations. »
# Chaque appareil franchit la porte une fois (session d'appareil) : un salarié
# qu'on équipe d'un poste et d'un téléphone avait besoin de deux liens.
auth_py = (BACKEND / "routers" / "auth.py").read_text(encoding="utf-8")
migration = BACKEND / "database" / "migrations" / "035_lien_multi_usages.sql"
verifier("la migration 035 existe et est idempotente",
         migration.exists() and migration.read_text(encoding="utf-8").count("ADD COLUMN IF NOT EXISTS") == 2)
verifier("un lien existant vaut UNE utilisation (défauts des colonnes)",
         migration.exists() and "utilisations_max INTEGER NOT NULL DEFAULT 1" in migration.read_text(encoding="utf-8"))
verifier("la route accepte le nombre d'utilisations", "class LienConnexionRequest" in users_py
         and "utilisations: int = 1" in users_py)
verifier("il est BORNÉ des deux côtés (1 au moins, 5 au plus)",
         "LIEN_ACCES_UTILISATIONS_MAX = 5" in users_py
         and "max(1, min(int(" in users_py)
verifier("la vérification COMPTE au lieu de cocher, en une seule requête (deux appareils en même temps)",
         "utilisations = utilisations + 1" in auth_py
         and "used = (utilisations + 1 >= utilisations_max)" in auth_py)
verifier("un lien plein est refusé comme avant", "faites >= maxi" in auth_py)
verifier("sans la migration, tout redevient à usage unique — et la réponse le DIT",
         "schema_incomplet" in auth_py and "schema_incomplet" in users_py
         and '"migration_absente": "035_lien_multi_usages"' in users_py)
verifier("le lien du MAIL reste à usage unique (rien ne change pour lui)",
         "INSERT INTO verification_tokens (email, token, expires_at) VALUES ($1, $2, $3)" in auth_py)
verifier("l'audit note le nombre d'utilisations accordé", '"utilisations": utilisations' in users_py)
verifier("l'écran fait CHOISIR avant de créer : 1, 2, 3 ou 5 appareils",
         "[1, 2, 3, 5].map((n) =>" in ecran and "Créer le lien" in ecran
         and "setLienPour({ id: user.id" in ecran)
verifier("le bandeau dit combien de fois le lien vaut",
         "Il fonctionne <b>{lienAcces.utilisations} fois</b>" in ecran)
verifier("le bandeau prévient si le serveur ne sait pas encore compter",
         "migration 035 à appliquer" in ecran)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
