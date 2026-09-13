"""
Banc « LA PAGE DE CONNEXION EST UN CHOIX DE PRÉNOM » (13/09, Duret).

Demande de Noa : tout le monde partage la boîte Gmail de l'entreprise ; la
page de connexion n'est plus qu'une rangée de cartes, « comme Netflix », où
chacun clique sur son nom. Les profils se configurent dans Paramètres (nom,
dossiers du mail). En bas, un tout petit bouton « Admin » ouvre le lien
magique d'aujourd'hui, qui reste la seule porte des administrateurs.

CE QUE CE BANC PROUVE (module et routes EXÉCUTÉS contre des doublures) :
  * les cartes : seulement les profils ACTIFS de la boîte de l'entreprise,
    jamais un administrateur, jamais une autre adresse ; pas de boîte reliée
    ⇒ aucune carte ;
  * l'entrée : le serveur revérifie tout — un identifiant hors des cartes
    (administrateur, désactivé, autre adresse, inventé) est refusé en 403 et
    tracé, un profil de la boîte ouvre une session (JWT + appareil) tracée ;
  * la création : un profil métier sans adresse prend celle de la boîte, un
    administrateur ne peut pas la prendre, un profil de la boîte a un nom ;
  * l'écran : cartes d'abord, bouton Admin qui ouvre le lien magique, retour
    aux profils, lien magique pour tout le monde s'il n'y a aucune carte.
Tombe sur la version d'avant.
"""
import ast
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel):
    return (RACINE / rel).read_text(encoding="utf-8")


print(f"\n═══ LA PAGE DE CONNEXION EST UN CHOIX DE PRÉNOM — {RACINE}\n")

# ── Le module des profils, exécuté ──
chemin = BACKEND / "auth" / "profils.py"
profils = types.ModuleType("auth.profils")
exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), profils.__dict__)

BOITE = "contact@exemple-sols.fr"
TOUS = [
    {"id": "a1", "email": BOITE, "name": "Nathalie", "role": "administratif", "actif": True},
    {"id": "a2", "email": "CONTACT@exemple-sols.fr", "name": "Éric", "role": "terrain", "actif": True},
    {"id": "a3", "email": BOITE, "name": "Paul", "role": "terrain", "actif": False},
    {"id": "d1", "email": BOITE, "name": "Direction", "role": "direction", "actif": True},
    {"id": "s1", "email": BOITE, "name": "Noa", "role": "super_admin", "actif": True},
    {"id": "x1", "email": "autre@exemple-sols.fr", "name": "Benoît", "role": "commercial", "actif": True},
]

print("— Les cartes")
existe = hasattr(profils, "cartes_de_connexion") and hasattr(profils, "entree_par_carte")
verifier("auth/profils porte cartes_de_connexion et entree_par_carte", existe)
if existe:
    c = profils.cartes_de_connexion(TOUS, BOITE)
    ids = [x["id"] for x in c]
    verifier("les profils actifs de la boîte, casse de l'adresse ignorée", ids == ["a1", "a2"], ids)
    verifier("ni rôle ni adresse sur une carte (id, nom, code seulement)",
             all(set(x) == {"id", "nom", "code"} for x in c), c)
    verifier("pas de boîte reliée : aucune carte", profils.cartes_de_connexion(TOUS, None) == [])

    print("— L'entrée par une carte")
    verifier("un profil de la boîte s'ouvre", (profils.entree_par_carte(TOUS, BOITE, "a2") or {}).get("id") == "a2")
    for uid, pourquoi in [("d1", "direction"), ("s1", "super_admin"), ("a3", "désactivé"),
                          ("x1", "une autre adresse"), ("zz", "inventé"), ("", "vide")]:
        verifier(f"refusé : {pourquoi}", profils.entree_par_carte(TOUS, BOITE, uid) is None)
    verifier("sans boîte reliée, rien ne s'ouvre", profils.entree_par_carte(TOUS, None, "a1") is None)

# ── Les routes, extraites de routers/auth.py et exécutées ──
print("— Les routes")
JOURNAL, APPAREILS, ECRITURES = [], [], []


class HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        self.status_code, self.detail = status_code, detail


class _Conn:
    async def execute(self, sql, *args):
        ECRITURES.append((sql, args))


class _Base:
    def __call__(self):
        return self

    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


class _Etat:
    boite = BOITE


async def _adresse():
    return _Etat.boite


async def _profils_de(email, actifs=True):
    return [p for p in TOUS if p["email"].lower() == (email or "").lower() and (p["actif"] or not actifs)]


async def _log(**kw):
    JOURNAL.append(kw)


async def _creer(uid, ua):
    APPAREILS.append(uid)
    return "jeton-appareil"


doublure = types.ModuleType("auth.profils")
doublure.__dict__.update({k: v for k, v in profils.__dict__.items() if not k.startswith("__")})
doublure.adresse_partagee = _adresse
doublure.profils_de = _profils_de
sys.modules["auth"] = types.SimpleNamespace(profils=doublure)
sys.modules["auth.profils"] = doublure

from datetime import datetime, timezone  # noqa: E402

source = lire("backend/routers/auth.py")
espace = {
    "get_db": _Base(), "datetime": datetime, "timezone": timezone,
    "HTTPException": HTTPException,
    "status": types.SimpleNamespace(HTTP_403_FORBIDDEN=403, HTTP_401_UNAUTHORIZED=401,
                                    HTTP_429_TOO_MANY_REQUESTS=429),
    "log_action": _log,
    "create_access_token": lambda d: f"jwt:{d['sub']}:{d['role']}",
    "appareil": types.SimpleNamespace(creer=_creer),
    "ChangerProfilRequest": object, "Request": object,
}
noms = {"profils_de_connexion", "entrer_par_carte", "_exiger_code"}
trouvees = []
for n in ast.parse(source).body:
    if isinstance(n, ast.AsyncFunctionDef) and n.name in noms:
        n.decorator_list = []
        n.args.defaults = []
        # Python 3.9 sur ce poste : `str | None` ne s'évalue pas, les annotations partent.
        n.returns = None
        for a in n.args.args:
            a.annotation = None
        trouvees.append(n)
verifier("routers/auth.py porte les deux routes de la page de connexion", len(trouvees) == 3,
         [t.name for t in trouvees])
verifier("routes publiques sous /connexion/…",
         '@router.get("/connexion/profils")' in source and '@router.post("/connexion/profil")' in source)

if len(trouvees) == 3:
    exec(compile(ast.Module(body=trouvees, type_ignores=[]), "auth", "exec"), espace)
    lister, entrer = espace["profils_de_connexion"], espace["entrer_par_carte"]

    r = asyncio.run(lister())
    verifier("GET : les cartes Nathalie et Éric seulement", [p["nom"] for p in r["profils"]] == ["Nathalie", "Éric"], r)
    _Etat.boite = None
    verifier("GET sans boîte reliée : aucune carte", asyncio.run(lister()) == {"profils": []})
    _Etat.boite = BOITE

    def ouvrir(uid):
        JOURNAL.clear(); APPAREILS.clear(); ECRITURES.clear()
        try:
            return asyncio.run(entrer(types.SimpleNamespace(user_id=uid, code=None),
                                      types.SimpleNamespace(headers={"user-agent": "banc"})))
        except HTTPException as e:
            return e

    r = ouvrir("a1")
    verifier("POST carte : session du profil (JWT, appareil, identité)",
             isinstance(r, dict) and r["access_token"] == "jwt:a1:administratif"
             and r["refresh_token"] == "jeton-appareil" and r["user_id"] == "a1" and r["nom"] == "Nathalie", r)
    verifier("l'entrée est tracée comme une connexion par carte",
             any(j.get("action") == "login" and (j.get("metadata") or {}).get("par") == "carte_profil" for j in JOURNAL), JOURNAL)
    verifier("last_login posé", any("last_login" in s for s, _ in ECRITURES))

    for uid in ("s1", "d1", "a3", "x1", "inconnu"):
        r = ouvrir(uid)
        verifier(f"POST {uid} : 403, aucune session, refus tracé",
                 isinstance(r, HTTPException) and r.status_code == 403 and not APPAREILS
                 and any(j.get("action") == "connexion_carte_refusee" for j in JOURNAL), r)
    _Etat.boite = None
    r = ouvrir("a1")
    verifier("POST sans boîte reliée : 403", isinstance(r, HTTPException) and r.status_code == 403)
    _Etat.boite = BOITE

# ── La création d'un profil ──
print("— Paramètres")
users = lire("backend/routers/users.py")
verifier("un profil métier sans adresse prend celle de la boîte",
         'email: str = ""' in users and "body.email = boite" in users)
# Depuis le 13/09 ces deux règles vivent dans `refus_sur_boite` (exécutée par
# test_droits_par_profil) : la direction y entre derrière un code.
verifier("sur la boîte, la création passe par refus_sur_boite (super_admin jamais, nom obligatoire)",
         "_profils.refus_sur_boite(body.role, body.name, bool(code), existants) if partagee" in users)
if existe:
    verifier("refus_sur_boite : super_admin refusé, profil sans nom refusé",
             profils.refus_sur_boite("super_admin", "Noa", True, []) is not None
             and profils.refus_sur_boite("terrain", "", False, []) is not None)
verifier("un profil de la boîte commence par la réception seule", "(existants or partagee) and dossiers is None" in users)
verifier("/users/dossiers-mail rend l'adresse de la boîte", '"adresse": adresse' in users)
reglages = lire("frontend/app/(app)/parametres/SettingsClient.tsx")
verifier("le formulaire pose l'adresse de la boîte d'office",
         "setForm((f) => ({ ...f, email: adresseBoite }))" in reglages and "setAdresseBoite(j.adresse" in reglages)
verifier("le formulaire dit que le profil aura sa carte à la connexion", "carte sur la page" in reglages)

# ── L'écran ──
print("— La page de connexion")
page = lire("frontend/app/(auth)/login/page.tsx")
verifier("les cartes viennent de /api/auth/connexion/profils", "/api/auth/connexion/profils" in page)
verifier("les cartes sont l'écran d'arrivée (ChoixProfil)", "<ChoixProfil" in page and 'vue === "cartes"' in page)
verifier("un clic ouvre la session sans lien magique", 'signIn("credentials", { carte: "1", user_id: id' in page)
verifier("le petit bouton Admin ouvre le lien magique", 'data-testid="bouton-admin"' in page and 'setVue("admin")' in page)
verifier("retour aux profils depuis le lien magique", "Retour aux profils" in page)
verifier("aucune carte : le lien magique pour tout le monde",
         'setVue(liste.length > 0 ? "cartes" : "admin")' in page and "/api/auth/magic-link/request" in page)
auth_ts = lire("frontend/lib/auth.ts")
verifier("next-auth sait ouvrir une carte", "carte: { type:" in auth_ts and "/api/auth/connexion/profil`" in auth_ts)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ tout est vert")
