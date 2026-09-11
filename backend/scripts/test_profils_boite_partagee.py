"""
Banc « LES PRÉNOMS D'UNE BOÎTE PARTAGÉE, ET LES DOSSIERS DE CHACUN » (11/09, Duret).

Demande de Noa : tout le monde se connecte avec la même adresse (la boîte de
l'entreprise, mot de passe d'application). Après le lien magique, un compte
non administrateur choisit son prénom sur un écran de cartes, et chaque
prénom est un utilisateur à part entière — son chat, ses informations — comme
avec des adresses différentes. L'administrateur crée ces profils sur une même
adresse et ouvre à chacun des dossiers du mail : le profil lit la boîte de
réception, plus ces dossiers-là.

CE QUE CE BANC PROUVE (modules EXÉCUTÉS contre des doublures de la base et
d'IMAP) :
  * qui entre : un compte seul entre directement ; plusieurs profils ⇒ les
    cartes ; un prénom cliqué doit appartenir à l'adresse ; un administrateur
    n'est JAMAIS atteignable par une adresse partagée, et ne peut pas en
    partager une ; deux prénoms identiques sur une adresse sont refusés ;
  * les dossiers IMAP : noms en UTF-7 modifié décodés et réencodés, dossier
    des envoyés reconnu à son attribut (Gmail en français), « Tous les
    messages », corbeille, brouillons et spam jamais proposés ;
  * les droits : la réception toujours, les autres selon le profil ; un
    dossier fermé est refusé AVANT tout appel réseau — liste, message ouvert
    par sa référence, pièce jointe ; la mémoire n'expose pas les messages
    envoyés à qui ne les a pas ;
  * l'écran : cartes après le lien, bouton « Changer de profil », fil courant
    rangé par profil et non par adresse, dossiers à cocher.
Tombe sur la version d'avant.
"""
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
FRONTEND = RACINE / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(chemin, nom):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    sys.modules[nom] = mod
    return mod


def lire(rel):
    return (RACINE / rel).read_text(encoding="utf-8")


print(f"\n═══ LES PRÉNOMS D'UNE BOÎTE PARTAGÉE, ET LES DOSSIERS DE CHACUN — {RACINE}\n")

# ── Doublures ──
cfg = types.ModuleType("config")
cfg.settings = types.SimpleNamespace(
    mail_imap_user="contact@exemple-sols.fr", mail_imap_password="x", mail_imap_host="imap.gmail.com",
    mail_imap_dossier_envoyes="[Gmail]/Sent Mail", mail_provider="imap", ms_domain=None, gmail_domain=None)
sys.modules["config"] = cfg

USERS = {}           # id -> {role, dossiers_mail, actif}
SCHEMA_ABSENT = {"oui": False}


class _Conn:
    async def fetchrow(self, sql, *a):
        if "dossiers_mail" in sql and SCHEMA_ABSENT["oui"]:
            raise RuntimeError('column "dossiers_mail" does not exist')
        u = USERS.get(str(a[0]))
        if not u or not u.get("actif", True):
            return None
        return dict(u)

    async def fetch(self, *a):
        return []


class _Ctx:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


dbc = types.ModuleType("database.connection")
dbc.get_db = lambda: _Ctx()
dbc.schema_incomplet = lambda e: "does not exist" in str(e)
sys.modules["database"] = types.ModuleType("database")
sys.modules["database.connection"] = dbc
fa = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code=403, detail=""):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


fa.HTTPException = HTTPException
fa.status = types.SimpleNamespace(HTTP_403_FORBIDDEN=403)
sys.modules["fastapi"] = fa
for paquet in ("auth", "mail", "llm", "security", "vectorstore"):
    sys.modules[paquet] = types.ModuleType(paquet)
    sys.modules[paquet].__path__ = [str(BACKEND / paquet)]
cles = types.ModuleType("llm.cles")
cles.valeur = lambda nom: getattr(cfg.settings, nom, None)
sys.modules["llm.cles"] = cles
rbac = types.ModuleType("security.rbac")
rbac.has_permission = lambda role, f: True
sys.modules["security.rbac"] = rbac

# ── 1. Qui entre ──
print("— qui entre")
profils = charger(BACKEND / "auth" / "profils.py", "auth.profils")
seul = [{"id": "a", "name": "Noa", "role": "super_admin"}]
equipe = [{"id": "n", "name": "Nathalie", "role": "administratif"},
          {"id": "e", "name": "Éric", "role": "conducteur"}]
verifier("un compte seul sur son adresse entre directement", profils.choisir(seul) == seul[0])
verifier("plusieurs profils : on montre les cartes", profils.choisir(equipe) == "choix")
verifier("le prénom cliqué est celui qui entre", profils.choisir(equipe, "e")["name"] == "Éric")
verifier("un identifiant étranger à l'adresse n'entre pas", profils.choisir(equipe, "intrus") is None)
verifier("aucun compte actif : personne n'entre", profils.choisir([]) is None)
melange = equipe + [{"id": "d", "name": "Direction", "role": "direction"}]
verifier("un administrateur n'est jamais atteignable par une adresse partagée",
         profils.choisir(melange, "d") is None)
verifier("les cartes ne montrent ni administrateur, ni rôle, ni adresse",
         profils.cartes(melange) == [{"id": "n", "nom": "Nathalie"}, {"id": "e", "nom": "Éric"}])

print("— qui peut être créé sur une adresse déjà portée")
verifier("une adresse neuve : rien à redire", profils.refus_creation("terrain", None, []) is None)
verifier("un nouveau prénom métier sur la boîte partagée", profils.refus_creation("terrain", "Julie", equipe) is None)
verifier("un administrateur ne partage pas une adresse",
         "administrateur" in (profils.refus_creation("direction", "Chef", equipe) or ""))
verifier("l'adresse d'un administrateur ne se partage pas",
         "administrateur" in (profils.refus_creation("terrain", "Julie", seul) or ""))
verifier("sur une adresse partagée, le prénom est obligatoire",
         "prénom" in (profils.refus_creation("terrain", "  ", equipe) or ""))
verifier("deux fois le même prénom (casse et espaces près) : refusé",
         "existe déjà" in (profils.refus_creation("terrain", "  nathalie ", equipe) or ""))

# ── 2. La connexion (contrats du routeur) ──
print("— la connexion")
src_auth = lire("backend/routers/auth.py")
bloc_verify = src_auth.split("async def verify_magic_link")[1].split("@router")[0]
verifier("le prénom est tranché AVANT de consommer le lien (les cartes rappellent la route)",
         0 < bloc_verify.find("_profils.choisir") < bloc_verify.find("UPDATE verification_tokens"))
verifier("sans prénom sur une adresse partagée : 409 « choix_profil »", 'detail="choix_profil"' in bloc_verify)
verifier("la session s'ouvre au compte CHOISI, pas au premier de l'adresse",
         '"SELECT * FROM users WHERE id = $1 AND actif = true"' in bloc_verify
         and "WHERE email = $1 AND actif = true" not in bloc_verify)
bloc_cartes = src_auth.split("async def profils_du_lien")[1].split("@router")[0]
verifier("les cartes ne se donnent que contre un lien VALIDE (anti-énumération)",
         "expires_at" in bloc_cartes and "utilisations_max" in bloc_cartes)
bloc_changer = src_auth.split("async def changer_de_profil")[1].split("@router")[0]
verifier("changer de profil ne sort jamais de l'adresse", "profils_partages" in bloc_changer
         and "_profils.choisir(partages" in bloc_changer)
verifier("le changement de profil est journalisé", 'action="changement_profil"' in bloc_changer)
src_users = lire("backend/routers/users.py")
verifier("la création passe par la règle des profils", "_profils.refus_creation(" in src_users)
verifier("le lien remis par l'administrateur désigne le prénom", "&profil=" in src_users)
verifier("la liste des comptes survit à une migration non appliquée",
         "NULL::text[] AS dossiers_mail" in src_users)
migration = lire("backend/database/migrations/040_profils_boite_partagee.sql")
verifier("la migration lève l'unicité de l'adresse seule", "DROP CONSTRAINT IF EXISTS users_email_key" in migration)
verifier("… pour l'unicité (adresse, nom)", "lower(email), lower(coalesce(name, ''))" in migration)
verifier("… et ajoute les dossiers de chacun", "ADD COLUMN IF NOT EXISTS dossiers_mail TEXT[]" in migration)
verifier("plus aucun « ON CONFLICT (email) » (il n'aurait plus de contrainte)",
         "ON CONFLICT (email)" not in lire("deploy.sh")
         and "ON CONFLICT (email)" not in lire("backend/database/migrations/_dev_seed.sql"))

# ── 3. Les dossiers IMAP ──
print("— les dossiers de la boîte")
imap = charger(BACKEND / "mail" / "imap.py", "mail.imap")
for nom in ("Comptabilité", "Tâches & suivi", "Chantiers/2026 — Ikos", "日本"):
    verifier(f"« {nom} » s'encode et se décode sans perte", imap.utf7_decoder(imap.utf7_encoder(nom)) == nom)
verifier("« Comptabilit&AOk- » (le fil) se lit « Comptabilité »", imap.utf7_decoder("Comptabilit&AOk-") == "Comptabilité")
verifier("« & » s'écrit « &- »", imap.utf7_encoder("A&B") == "A&-B")
LIST_GMAIL_FR = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasNoChildren) "/" "Chantiers"',
    b'(\\HasNoChildren) "/" "Comptabilit&AOk-"',
    b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
    b'(\\All \\HasNoChildren) "/" "[Gmail]/Tous les messages"',
    b'(\\Drafts \\HasNoChildren) "/" "[Gmail]/Brouillons"',
    b'(\\HasNoChildren \\Important) "/" "[Gmail]/Important"',
    b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Messages envoy&AOk-s"',
    b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
    b'(\\Flagged \\HasNoChildren) "/" "[Gmail]/Suivis"',
    b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Corbeille"',
    (b'(\\HasNoChildren) "/" {7}', b'Devis 1'),
]
analyses = imap.analyser_list(LIST_GMAIL_FR)
verifier("la liste Gmail se lit, littéral compris", ({"\\sent", "\\hasnochildren"}, "[Gmail]/Messages envoyés") in analyses
         and any(n == "Devis 1" for _, n in analyses), analyses[-1:])
proposes = imap.dossiers_proposables(analyses)
noms = [d["nom"] for d in proposes]
verifier("les envoyés sont proposés sous la clé « envoyes », en tête", noms[0] == "envoyes" and proposes[0]["libelle"] == "Messages envoyés")
verifier("les dossiers de l'utilisateur sont proposés, décodés", {"Chantiers", "Comptabilité", "Devis 1"} <= set(noms), noms)
verifier("ni la réception, ni « Tous les messages », corbeille, brouillons, spam, suivis, importants",
         not ({"INBOX", "[Gmail]/Tous les messages", "[Gmail]/Corbeille", "[Gmail]/Brouillons", "[Gmail]/Spam",
               "[Gmail]/Suivis", "[Gmail]/Important", "[Gmail]"} & set(noms)), noms)
verifier("le vrai nom des envoyés est retenu (Gmail en français)", imap.dossier_imap("envoyes") == "[Gmail]/Messages envoyés")
verifier("« recus » et ses synonymes sont la réception", all(imap.cle_dossier(x) == "INBOX" for x in ("recus", "INBOX", "Boîte de réception", "")))
verifier("le nom réel des envoyés se ramène à « envoyes »", imap.cle_dossier("[Gmail]/Messages envoyés") == "envoyes")
verifier("la réception est toujours permise", imap.dossier_permis("recus", frozenset()))
verifier("un dossier non ouvert est refusé", not imap.dossier_permis("Comptabilité", frozenset({"Chantiers"})))
verifier("un dossier ouvert est permis (casse près)", imap.dossier_permis("chantiers", frozenset({"Chantiers"})))
verifier("sans restriction, tout est permis", imap.dossier_permis("Comptabilité", None))


class ClientFaux:
    def __init__(self, existants):
        self.existants, self.ouverts = existants, []

    def select(self, nom, readonly=True):
        self.ouverts.append(nom)
        return ("OK" if nom in self.existants else "NO"), [b"0"]

    def list(self):
        return "OK", LIST_GMAIL_FR


imap._ENVOYES_DETECTE = None
client = ClientFaux({'"[Gmail]/Messages envoy&AOk-s"'})
imap._selectionner(client, imap.dossier_imap("envoyes"))
verifier("envoyés introuvables sous le nom réglé : retrouvés par leur attribut \\Sent",
         client.ouverts == ['"[Gmail]/Sent Mail"', '"[Gmail]/Messages envoy&AOk-s"'], client.ouverts)
client = ClientFaux({'"Comptabilit&AOk-"'})
imap._selectionner(client, "Comptabilité")
verifier("un dossier accentué s'ouvre sous son nom encodé", client.ouverts == ['"Comptabilit&AOk-"'])

# ── 4. Les droits par profil ──
print("— les dossiers de chaque profil")
autorisation = charger(BACKEND / "mail" / "authorization.py", "mail.authorization")
USERS.update({
    "admin": {"role": "direction", "dossiers_mail": ["Chantiers"]},
    "libre": {"role": "terrain", "dossiers_mail": None},
    "julie": {"role": "administratif", "dossiers_mail": ["Chantiers"]},
    "eric": {"role": "conducteur", "dossiers_mail": ["envoyes", "Chantiers"]},
})
da = lambda uid: asyncio.run(autorisation.dossiers_autorises(uid))
verifier("un administrateur n'a jamais de restriction", da("admin") is None)
verifier("un compte sans restriction posée : tout (comme avant)", da("libre") is None)
verifier("un profil restreint : ses dossiers", da("julie") == frozenset({"Chantiers"}))
verifier("un compte inconnu : la réception seule", da("inconnu") == frozenset())
SCHEMA_ABSENT["oui"] = True
verifier("sans la migration 040 : rien n'était restreint, rien ne l'est", da("julie") is None)
SCHEMA_ABSENT["oui"] = False
cfg.settings.mail_imap_user = None
verifier("sans boîte unique, pas de découpage en dossiers", da("julie") is None)
cfg.settings.mail_imap_user = "contact@exemple-sols.fr"
memoire = asyncio.run(autorisation.boites_pour_la_memoire("julie"))
verifier("la mémoire écarte les envoyés de qui ne les a pas", autorisation.SANS_ENVOYES in memoire, memoire)
verifier("… et les garde à qui les a", autorisation.SANS_ENVOYES not in asyncio.run(autorisation.boites_pour_la_memoire("eric")))

# Les deux fonctions pures du filtre, extraites du module livré.
import ast
rag_src = lire("backend/vectorstore/rag.py")
arbre = ast.parse(rag_src)
morceaux = [ast.get_source_segment(rag_src, n) for n in arbre.body
            if isinstance(n, ast.FunctionDef) and n.name in ("_boite_du_chunk", "_filtrer_mails")]
ns = {"Optional": __import__("typing").Optional, "TYPES_MAIL": ("email", "email_sent")}
exec("\n\n".join(morceaux), ns)
chunks = [{"source_type": "email", "source_id": "email:contact@exemple-sols.fr:1"},
          {"source_type": "email_sent", "source_id": "email_sent:contact@exemple-sols.fr:2"},
          {"source_type": "devis", "source_id": "d1"}]
retenus = ns["_filtrer_mails"](chunks, ["contact@exemple-sols.fr", "!email_sent"])
verifier("la recherche en mémoire ne rend pas les envoyés à ce profil",
         [c["source_type"] for c in retenus] == ["email", "devis"], retenus)
verifier("sans le jeton, les envoyés restent", len(ns["_filtrer_mails"](chunks, ["contact@exemple-sols.fr"])) == 3)

# ── 5. La lecture refuse avant d'appeler le serveur ──
print("— la lecture en direct")
coll = types.ModuleType("mail.collecte")
coll.fournisseur = lambda: "imap"
sys.modules["mail.collecte"] = coll
APPELS = []
imap.lister = lambda boite, dossier, limite, *a, **k: (APPELS.append(("lister", dossier)) or ([], 0))
imap.ouvrir = lambda boite, uid, dossier: (APPELS.append(("ouvrir", dossier)) or {"corps": "", "pieces_jointes": []})
lecture = charger(BACKEND / "mail" / "lecture.py", "mail.lecture")
try:
    asyncio.run(lecture.lire_boite("contact@exemple-sols.fr", "Comptabilité", autorises=frozenset({"Chantiers"})))
    verifier("un dossier fermé est refusé", False)
except lecture.DossierInterdit as e:
    verifier("un dossier fermé est refusé, sans appel au serveur", not APPELS, APPELS)
    verifier("… et le refus dit ce que le profil peut lire", "réception" in str(e) and "Chantiers" in str(e), str(e))
asyncio.run(lecture.lire_boite("contact@exemple-sols.fr", "Chantiers", autorises=frozenset({"Chantiers"})))
verifier("un dossier ouvert se lit sous son NOM", APPELS[-1] == ("lister", "Chantiers"), APPELS)
asyncio.run(lecture.lire_boite("contact@exemple-sols.fr", "recus", autorises=frozenset()))
verifier("la réception se lit toujours", APPELS[-1] == ("lister", "INBOX"))
try:
    asyncio.run(lecture.lire_boite("contact@exemple-sols.fr", "envoyes", autorises=frozenset({"Chantiers"})))
    verifier("les envoyés sont refusés à qui ne les a pas", False)
except lecture.DossierInterdit:
    verifier("les envoyés sont refusés à qui ne les a pas", True)
ref = lecture._memoriser("Comptabilité|42", "contact@exemple-sols.fr")
n = len(APPELS)
try:
    asyncio.run(lecture.lire_message("contact@exemple-sols.fr", ref=ref, autorises=frozenset({"Chantiers"})))
    verifier("une RÉFÉRENCE d'un dossier fermé ne l'ouvre pas", False)
except lecture.DossierInterdit:
    verifier("une RÉFÉRENCE d'un dossier fermé ne l'ouvre pas", len(APPELS) == n)
src_skills = lire("backend/mail/skills.py")
for geste in ("lire_mails", "lire_mail", "lire_piece_jointe"):
    corps = src_skills.split(f"async def {geste}(")[1].split("\nSKILLS_NATIFS")[0]
    verifier(f"« {geste} » passe les dossiers du profil et traduit le refus",
             "autorises=await dossiers_autorises(user)" in corps and "except DossierInterdit" in corps)
verifier("le geste « dossiers_mail » existe et se déclare en lecture",
         'SKILLS_NATIFS["dossiers_mail"]' in src_skills and '"dossiers_mail": "lecture"' in src_skills
         and '"dossiers_mail": (' in lire("backend/skills/protocol.py"))
for f in ("backend/agents/agent1.py", "backend/skills/documents.py"):
    verifier(f"la recherche en mémoire de {f.split('/')[-1]} applique les dossiers", "boites_pour_la_memoire" in lire(f))

# ── 6. L'écran ──
print("— l'écran")
verify = lire("frontend/app/(auth)/verify/page.tsx")
verifier("après le lien, les cartes quand l'adresse porte plusieurs prénoms",
         "/api/auth/magic-link/profils" in verify and "<ChoixProfil" in verify and "user_id: userId" in verify)
verifier("le lien de l'administrateur ouvre le prénom sans cartes", 'params.get("profil")' in verify)
auth_ts = lire("frontend/lib/auth.ts")
verifier("la session s'ouvre au prénom choisi, ou bascule sans nouveau lien",
         "user_id: { type: \"text\" }" in auth_ts and "/api/auth/profils/changer" in auth_ts)
verifier("la session porte l'identifiant du PROFIL", "(session.user as any).id = token.sub" in auth_ts)
verifier("le fil courant se range par profil, pas par adresse",
         "(session as any)?.user?.id || (session as any)?.user?.email" in lire("frontend/components/chat/ChatWindow.tsx"))
verifier("« Changer de profil » dans le panneau, seulement pour une boîte partagée",
         "Changer de profil" in lire("frontend/components/nav/EnTete.tsx")
         and "autresProfils > 1" in lire("frontend/components/nav/EnTete.tsx"))
verifier("la page des profils existe", "signIn(\"credentials\", { bascule: jeton" in lire("frontend/app/(app)/profil/page.tsx"))
reglages = lire("frontend/app/(app)/parametres/SettingsClient.tsx")
verifier("l'administrateur coche les dossiers de chacun",
         "/api/users/dossiers-mail" in reglages and "<CasesDossiers" in reglages and "dossiers-mail`" in reglages)
verifier("sur une adresse déjà portée, le prénom devient obligatoire", "required={adresseDejaPortee}" in reglages)

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
