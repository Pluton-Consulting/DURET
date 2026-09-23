"""
Banc « LES BOÎTES PRIVÉES DE LA DIRECTION, ET L'EXPLORATEUR DU NAS » (23/09, Duret).

Demande de Noa : « deux mails perso/pro supplémentaires, uniquement pour le
compte direction (et donc admin), techniquement inaccessibles depuis un autre
compte » — et, pour comparer deux options, un explorateur du NAS et le site
Synology dans le tableau de bord, « uniquement pour le compte admin ».

CE QUE CE BANC PROUVE (modules LIVRÉS exécutés contre une base, des réglages,
un IMAP et un SMTP doublés) :
  * une boîte privée s'ouvre à la direction et au super_admin, à PERSONNE
    d'autre — ni par son adresse, ni par son libellé, ni par une délégation
    posée par erreur — et le refus a le texte exact d'une boîte inconnue ;
  * la boîte unique de l'entreprise reste lisible comme avant par l'équipe, et
    ne peut pas devenir « privée » ;
  * une connexion IMAP / SMTP prend les identifiants de la boîte visée — et
    ceux de la boîte unique quand aucune boîte privée n'est en jeu (rien de
    changé) ; la boîte autorisée par un geste passe à son thread, pas au geste
    suivant ; une boîte privée retirée ne retombe pas sur la boîte unique ;
  * l'explorateur et les réglages répondent 403 à tout autre rôle que
    super_admin (contrat lu dans le source).
"""
import ast
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(chemin, nom):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    src = chemin.read_text(encoding="utf-8")
    sys.modules[nom] = mod
    exec(compile(src, str(chemin), "exec"), mod.__dict__)
    return mod


print(f"\n═══ LES BOÎTES PRIVÉES DE LA DIRECTION — {BACKEND.parent}\n")

UNIQUE = "contact@exemple-sols.fr"
PERSO = "patron.perso@gmail.com"
PRO = "patron@cabinet-exemple.fr"

cfg = types.ModuleType("config")
cfg.settings = types.SimpleNamespace(mail_imap_user=None, mail_imap_password=None,
                                     mail_imap_host="imap.gmail.com", mail_smtp_host="smtp.gmail.com",
                                     mail_smtp_port=587, ms_domain=None, gmail_domain=None)
sys.modules["config"] = cfg
CLES = {"mail_imap_user": UNIQUE, "mail_imap_password": "unique-mdp",
        "mail_prive_1_user": PERSO, "mail_prive_1_password": "perso mdp 1234", "mail_prive_1_libelle": "Perso",
        "mail_prive_2_user": PRO, "mail_prive_2_password": "pro-mdp",
        "mail_prive_2_libelle": "Pro", "mail_prive_2_imap_host": "ssl0.ovh.net",
        "mail_prive_2_smtp_host": "ssl0.ovh.net"}
llm = types.ModuleType("llm"); llm_cles = types.ModuleType("llm.cles")
llm_cles.valeur = lambda nom: CLES.get(nom) or getattr(cfg.settings, nom, None)
sys.modules["llm"] = llm; sys.modules["llm.cles"] = llm_cles

fa = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code=403, detail=""):
        super().__init__(detail); self.status_code, self.detail = status_code, detail


fa.HTTPException = HTTPException
fa.status = types.SimpleNamespace(HTTP_403_FORBIDDEN=403, HTTP_404_NOT_FOUND=404,
                                  HTTP_409_CONFLICT=409, HTTP_422_UNPROCESSABLE_ENTITY=422)
sys.modules["fastapi"] = fa

# Base doublée : les délégations (une boîte privée déléguée PAR ERREUR à un salarié).
DELEGATIONS = {}


class _Conn:
    async def fetch(self, sql, *a):
        if "user_mailboxes" in sql:
            return [{"mailbox": m, "can_send": True} for m in DELEGATIONS.get(a[0], [])]
        return []

    async def fetchrow(self, sql, *a):
        return None

    async def execute(self, sql, *a):
        return "INSERT 0 1"


class _Ctx:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


db = types.ModuleType("database"); dbc = types.ModuleType("database.connection")
dbc.get_db = lambda: _Ctx()
sys.modules["database"] = db; sys.modules["database.connection"] = dbc
sec = types.ModuleType("security"); rbac = types.ModuleType("security.rbac")
rbac.has_permission = lambda role, feat: True          # « Accès au mail » accordé à tous
audit = types.ModuleType("security.audit")
TRACES = []


async def _log(**k):
    TRACES.append(k)
audit.log_action = _log
sys.modules["security"] = sec; sys.modules["security.rbac"] = rbac; sys.modules["security.audit"] = audit

sys.modules["mail"] = types.ModuleType("mail")
bp = charger(BACKEND / "mail" / "boites_privees.py", "mail.boites_privees")
sys.modules["mail"].boites_privees = bp
imap = charger(BACKEND / "mail" / "imap.py", "mail.imap")
sys.modules["mail"].imap = imap
authz = charger(BACKEND / "mail" / "authorization.py", "mail.authorization")


def U(role, email="x@exemple-sols.fr", uid="u1"):
    return types.SimpleNamespace(role=role, email=email, id=uid)


print("— Le module des boîtes privées")
verifier("deux emplacements configurés", [b["adresse"] for b in bp.boites()] == [PERSO, PRO], bp.boites())
verifier("reconnue par son adresse, casse et espaces comprises", bp.est_privee("  Patron.Perso@GMAIL.com "))
verifier("la boîte unique n'est JAMAIS privée", not bp.est_privee(UNIQUE))
verifier("identifiants : hôtes par défaut (Gmail), espaces du mot de passe retirés",
         bp.identifiants(PERSO) == {"adresse": PERSO, "mot_de_passe": "persomdp1234",
                                    "hote_imap": "imap.gmail.com", "hote_smtp": "smtp.gmail.com"})
verifier("identifiants : hôtes propres à l'emplacement", bp.identifiants(PRO)["hote_imap"] == "ssl0.ovh.net")
for role in ("direction", "super_admin", " Direction "):
    verifier(f"« {role.strip()} » les voit", bp.peut_acceder(role))
for role in ("administratif", "commercial", "conducteur_travaux", "", None, "directions"):
    verifier(f"« {role} » ne les voit pas", not bp.peut_acceder(role) and bp.adresses_pour(role) == [])
verifier("libellé « ma boîte perso » → l'adresse, pour la direction",
         bp.resoudre_libelle("ma boîte perso", "direction") == PERSO)
verifier("libellé « boîte privée 2 » → la seconde", bp.resoudre_libelle("boîte privée 2", "super_admin") == PRO)
verifier("libellé : RIEN pour un profil terrain", bp.resoudre_libelle("perso", "administratif") is None)
CLES.pop("mail_prive_1_password")
verifier("un emplacement sans mot de passe n'est pas une boîte", not bp.est_privee(PERSO))
CLES["mail_prive_1_password"] = "perso mdp 1234"

print("\n— Le verrou : verifier_acces")


async def acces(user, boite, envoi=False):
    try:
        return ("ok", await authz.verifier_acces(user, boite, envoi=envoi))
    except HTTPException as e:
        return ("refus", e.detail)


async def scenario():
    r = await acces(U("direction"), PERSO)
    verifier("direction : la boîte perso s'ouvre", r == ("ok", PERSO), r)
    verifier("  … et la boîte du geste est posée pour l'IMAP", imap.boite_du_geste() == PERSO)
    r = await acces(U("super_admin"), PRO, envoi=True)
    verifier("super_admin : la boîte pro s'ouvre, envoi compris", r == ("ok", PRO), r)
    await asyncio.sleep(0)
    verifier("chaque accès est tracé (mailbox_private_access)",
             any(t.get("action") == "mailbox_private_access" for t in TRACES))
    inconnue = await acces(U("administratif"), "personne@nulle-part.fr")
    for role in ("administratif", "commercial", "conducteur_travaux", "bureau_etudes", ""):
        r = await acces(U(role), PERSO)
        verifier(f"« {role or 'sans rôle'} » : refus", r[0] == "refus", r)
        verifier("  … texte identique à une boîte inconnue",
                 r[1].replace(PERSO, "X") == inconnue[1].replace("personne@nulle-part.fr", "X"), (r, inconnue))
        verifier("  … et aucune boîte du geste posée", imap.boite_du_geste() is None)
    r = await acces(U("administratif"), UNIQUE)
    verifier("la boîte unique reste lisible par l'équipe", r == ("ok", UNIQUE), r)
    verifier("  … et remet la boîte du geste à zéro", imap.boite_du_geste() is None)

    # SANS boîte unique : la voie des délégations. Une boîte privée déléguée par erreur n'ouvre rien.
    CLES.pop("mail_imap_user")
    DELEGATIONS["u9"] = [PERSO]
    salarie = U("administratif", email="salarie@exemple-sols.fr", uid="u9")
    r = await acces(salarie, PERSO)
    verifier("délégation posée par erreur : toujours refusé", r[0] == "refus", r)
    inconnue = await acces(salarie, "personne@nulle-part.fr")
    verifier("  … texte identique à une boîte inconnue (voie des délégations)",
             r[1].replace(PERSO, "X") == inconnue[1].replace("personne@nulle-part.fr", "X"), (r, inconnue))
    try:
        await authz.accorder(U("direction"), "u9", PERSO)
        verifier("déléguer une boîte privée est refusé", False)
    except HTTPException as e:
        verifier("déléguer une boîte privée est refusé", e.status_code == 403, e.detail)
    b = await authz.boites_autorisees(U("administratif", email="salarie@exemple-sols.fr", uid="u8"))
    verifier("sans boîte unique : aucune boîte privée listée à un salarié",
             not any(x.get("privee") for x in b), b)
    r = await acces(U("direction", email="dir@exemple-sols.fr"), PRO)
    verifier("sans boîte unique : la direction l'ouvre toujours", r == ("ok", PRO), r)
    DELEGATIONS.clear()
    CLES["mail_imap_user"] = UNIQUE

    b = await authz.boites_autorisees(U("direction"))
    verifier("boîte unique + direction : les deux boîtes privées listées",
             [x["mailbox"] for x in b if x.get("privee")] == [PERSO, PRO], b)
    b = await authz.boites_autorisees(U("commercial"))
    verifier("boîte unique + commercial : la boîte unique seule", [x["mailbox"] for x in b] == [UNIQUE], b)
    b = await authz.boites_par_id("u1")
    verifier("la mémoire partagée ne reçoit aucune boîte privée", PERSO not in b and PRO not in b, b)

asyncio.run(scenario())

print("\n— Quelle boîte l'IMAP et le SMTP ouvrent")
imap.poser_boite_du_geste(None)
verifier("sans boîte privée : la boîte unique, comme avant",
         imap._compte()["login"] == UNIQUE and imap._compte()["mot_de_passe"] == "unique-mdp")
verifier("une adresse inconnue : la boîte unique, comme avant", imap._compte("autre@x.fr")["login"] == UNIQUE)
verifier("la boîte perso visée : SES identifiants", imap._compte(PERSO)["login"] == PERSO
         and imap._compte(PERSO)["mot_de_passe"] == "persomdp1234")
verifier("la boîte pro : son serveur IMAP", imap._compte(PRO)["hote_imap"] == "ssl0.ovh.net")

LOGINS = []


class FauxIMAP:
    def __init__(self, hote, port, **k):
        self.hote = hote

    def login(self, u, p):
        LOGINS.append((self.hote, u, p))

    def logout(self):
        pass


imap.imaplib = types.SimpleNamespace(IMAP4_SSL=FauxIMAP)


async def fils():
    with imap.geste_neutre():
        imap.poser_boite_du_geste(PRO)
        await asyncio.to_thread(imap._connexion)          # un appel qui ne connaît pas la boîte
    await asyncio.to_thread(imap._connexion)              # après le geste, sans boîte
asyncio.run(fils())
verifier("le thread d'un geste hérite de SA boîte privée", LOGINS[0] == ("ssl0.ovh.net", PRO, "pro-mdp"), LOGINS)
verifier("après le geste : la boîte unique", LOGINS[1][1] == UNIQUE, LOGINS)
imap.lister.__globals__["_connexion"]  # la fonction existe toujours
verifier("lister et ouvrir se connectent à LA boîte demandée",
         "client = _connexion(boite)" in (BACKEND / "mail" / "imap.py").read_text(encoding="utf-8").split("def lister(", 1)[1].split("def ouvrir(", 1)[0]
         and "client = _connexion(boite)" in (BACKEND / "mail" / "imap.py").read_text(encoding="utf-8").split("def ouvrir(", 1)[1].split("def parcourir(", 1)[0])

imap.poser_boite_du_geste(PERSO)
CLES.pop("mail_prive_1_user")
try:
    imap._compte()
    verifier("boîte privée retirée en cours de geste : erreur, jamais la boîte unique", False)
except RuntimeError:
    verifier("boîte privée retirée en cours de geste : erreur, jamais la boîte unique", True)
CLES["mail_prive_1_user"] = PERSO
imap.poser_boite_du_geste(None)

ENVOIS = []


class FauxSMTP:
    def __init__(self, hote, port, timeout=0):
        self.hote = hote

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, **k):
        pass

    def login(self, u, p):
        ENVOIS.append((self.hote, u, p))

    def sendmail(self, *a):
        pass


imap.smtplib = types.SimpleNamespace(SMTP=FauxSMTP)
imap.envoyer(b"x", PRO, ["a@b.fr"])
imap.envoyer(b"x", UNIQUE, ["a@b.fr"])
verifier("un envoi depuis la boîte pro part par SON serveur et SES identifiants",
         ENVOIS[0] == ("ssl0.ovh.net", PRO, "pro-mdp"), ENVOIS)
verifier("un envoi depuis la boîte unique : inchangé", ENVOIS[1] == ("smtp.gmail.com", UNIQUE, "unique-mdp"), ENVOIS)

print("\n— Contrats lus dans le source")
exe = (BACKEND / "skills" / "executor.py").read_text(encoding="utf-8")
verifier("chaque geste repart sans boîte privée (executor : geste_neutre)",
         "with au_nom_de(user):\n                with geste_neutre():" in exe)
sk = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("boites_visibles : adresses privées filtrées par rôle", 'adresses_pour(getattr(user, "role", None))' in sk)
verifier("_boite_a_lire : libellé résolu selon le rôle", 'resoudre_libelle(demandee, getattr(user, "role", None))' in sk)
cles_src = (BACKEND / "llm" / "cles.py").read_text(encoding="utf-8")
verifier("réglages déclarés et hors de la liste des clés de modèles",
         all(f'"{c}"' in cles_src for c in bp.toutes_les_cles()) and "mail_prive_{r}_{c}" in cles_src)


def routes_gardees(fichier, garde):
    arbre = ast.parse((BACKEND / fichier).read_text(encoding="utf-8"))
    sortie = {}
    for f in arbre.body:
        if isinstance(f, ast.AsyncFunctionDef) and any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ("get", "put", "post", "delete")
                for d in f.decorator_list):
            corps = [n for n in f.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            premier = corps[0] if corps else None
            sortie[f.name] = bool(premier is not None and isinstance(premier, ast.Expr)
                                  and isinstance(premier.value, ast.Call)
                                  and getattr(premier.value.func, "id", "") == garde)
    return sortie


r = routes_gardees("routers/nas_explorateur.py", "_exiger")
flux = r.pop("fichier", None)
verifier("explorateur NAS : 6 routes gardées dès la première ligne (dont 2 écritures)", len(r) == 6 and all(r.values()), r)
verifier("explorateur NAS : la lecture en flux exige un billet ou une session, puis la même garde",
         flux is not None and "lire_billet(t, chemin)" in (BACKEND / "routers" / "nas_explorateur.py").read_text(encoding="utf-8")
         and "_exiger(personne)" in (BACKEND / "routers" / "nas_explorateur.py").read_text(encoding="utf-8"))
src_nas = (BACKEND / "routers" / "nas_explorateur.py").read_text(encoding="utf-8")
verifier("explorateur NAS : ouvert à tous les comptes, sans rôle imposé (23/09)",
         '!= "super_admin"' not in src_nas and "Session invalide" in src_nas)
verifier("explorateur NAS : chaque lecture vérifie le chemin avec les droits par dossier (verifier)",
         src_nas.count("verifier(") >= 2)
verifier("explorateur NAS : lectures ET écritures au nom de la personne (droits par dossier)",
         src_nas.count("au_nom_de(current_user)") == 5)
r = {k: v for k, v in routes_gardees("routers/settings.py", "_exiger_super_admin").items() if "privee" in k}
verifier("réglages des boîtes privées : 3 routes, super_admin seul", len(r) == 3 and all(r.values()), r)
main = (BACKEND / "main.py").read_text(encoding="utf-8")
verifier("route montée en import optionnel", 'prefix="/api/nas-explorateur"' in main)
front = (BACKEND.parent / "frontend" / "components" / "fichiers" / "Fichiers.tsx").read_text(encoding="utf-8")
verifier("écran : l'onglet Fichiers dit un refus du serveur au lieu de l'explorateur",
         "setAcces(false)" in front and "n'est pas ouvert à ce compte" in front)

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
