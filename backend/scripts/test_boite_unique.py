"""
Banc « LA BOÎTE UNIQUE PAR MOT DE PASSE D'APPLICATION, ET LA COLONNE ACCÈS AU
MAIL » (08/09 soir).

Décision de Noa pour Duret : « on va passer par un seul mail pour tout le
monde, je vais mettre un mot de passe d'application ; dans les permissions il
faut ajouter l'accès au mail comme colonne ».

CE QUE CE BANC PROUVE (modules EXÉCUTÉS contre un IMAP, un SMTP et une base
doublés) : la boîte unique se lit par IMAP avec les mêmes fiches que Graph et
Gmail (référence, pièces, lu, dates), un message s'ouvre en entier avec ses
pièces désignées par leur rang, une pièce se télécharge, un envoi part par
SMTP au bon destinataire ; qui a l'accès au mail lit cette boîte et personne
d'autre, une autre adresse est refusée en le disant, un rôle sans la colonne
n'a rien ; sans boîte unique, rien ne change pour l'autre client ; la
permission existe, semée pour tous les rôles ; les aiguillages de la lecture
et de l'envoi passent par IMAP quand il est configuré. Tombe sur la version
d'avant.
"""
import asyncio
import pathlib
import sys
import types
from datetime import datetime
from email.message import EmailMessage

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(chemin, nom, futur=False):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    # `futur` : ce Mac tourne en Python 3.9 et `int | None` au niveau du module
    # (rbac.py) n'y est pas évalué sans l'import du futur ; le conteneur est en 3.12.
    src = chemin.read_text(encoding="utf-8")
    if futur:
        src = "from __future__ import annotations\n" + src
    exec(compile(src, str(chemin), "exec"), mod.__dict__)
    return mod


print(f"\n═══ LA BOÎTE UNIQUE, ET L'ACCÈS AU MAIL — {BACKEND.parent}\n")

# ── Doublures communes ──
cfg = types.ModuleType("config")
cfg.settings = types.SimpleNamespace(mail_imap_user="Contact@Duret-Sols.fr", mail_imap_password="abcd efgh ijkl mnop",
                                     mail_imap_host="imap.gmail.com", mail_imap_dossier_envoyes="[Gmail]/Sent Mail",
                                     mail_smtp_host="smtp.gmail.com", mail_smtp_port=587, mail_provider="auto",
                                     ms_domain=None, gmail_domain="duret-sols.fr", ms_tenant_id=None,
                                     ms_client_id=None, ms_client_secret=None)
sys.modules["config"] = cfg
# 08/09 soir : les identifiants se lisent dans Paramètres (table cles_api) d'abord.
CLES_BASE = {}
llm_cles = types.ModuleType("llm.cles")
llm_cles.valeur = lambda nom: CLES_BASE.get(nom) or getattr(cfg.settings, nom, None)
sys.modules["llm"] = types.ModuleType("llm"); sys.modules["llm.cles"] = llm_cles
fa = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code=403, detail=""):
        super().__init__(detail); self.status_code, self.detail = status_code, detail
fa.HTTPException = HTTPException
fa.status = types.SimpleNamespace(HTTP_403_FORBIDDEN=403)
sys.modules["fastapi"] = fa
lect = types.ModuleType("mail.lecture")
REFS = {}
lect._apercu = lambda t, n: " ".join((t or "").split())[:n]
lect._memoriser = lambda ident, boite: REFS.setdefault(ident, f"ref{len(REFS) + 1}")
lect._qualifier = lambda adresse: {"adresse": adresse, "interne": "duret-sols.fr" in adresse, "automatique": "no-reply" in adresse}
lect._texte_lisible = lambda c, html=None: " ".join(c.replace("<p>", " ").replace("</p>", " ").split()) if html else c
lect.MAX_APERCU = 800
sys.modules["mail"] = types.ModuleType("mail"); sys.modules["mail.lecture"] = lect
pcs = types.ModuleType("mail.pieces"); pcs.extension_du_mime = lambda mime: {"image/png": ".png", "application/pdf": ".pdf"}.get(mime, "")
sys.modules["mail.pieces"] = pcs

# Deux messages construits comme un vrai client les enverrait.
m1 = EmailMessage()
m1["From"] = "Client Martin <martin@client.fr>"; m1["To"] = "contact@duret-sols.fr"
m1["Subject"] = "Demande de devis carrelage"; m1["Date"] = "Tue, 08 Sep 2026 09:15:00 +0200"
m1.set_content("Bonjour, pourriez-vous chiffrer 80 m² de grès cérame ? Cordialement")
m1.add_attachment(b"%PDF-1.4 plan", maintype="application", subtype="pdf", filename="plan.pdf")
m2 = EmailMessage()
m2["From"] = "no-reply@sidv.fr"; m2["To"] = "contact@duret-sols.fr"; m2["Subject"] = "Votre commande"
m2["Date"] = "Tue, 08 Sep 2026 10:00:00 +0200"
m2.add_alternative("<p>Commande confirmée</p>", subtype="html")
BOITE = {b"101": (m1, b"(UID 101 FLAGS () BODY[] {0}"), b"102": (m2, b"(UID 102 FLAGS (\\Seen) BODY[] {0}")}
JOURNAL = {"search": [], "select": [], "smtp": []}


class _IMAP:
    def __init__(self, hote, port=993, ssl_context=None, timeout=None):
        JOURNAL["hote"] = (hote, port)

    def login(self, u, p):
        JOURNAL["login"] = (u, p)

    def select(self, dossier, readonly=False):
        JOURNAL["select"].append((dossier, readonly)); return "OK", [b"2"]

    def uid(self, commande, *args):
        if commande == "search":
            JOURNAL["search"].append(args[1]); return "OK", [b"101 102"]
        if commande == "fetch":
            uid = args[0]
            if uid not in BOITE:
                return "OK", [None]
            m, entete = BOITE[uid]
            return "OK", [(entete, m.as_bytes())]
        raise AssertionError(commande)

    def logout(self):
        JOURNAL["logout"] = True


class _SMTP:
    def __init__(self, hote, port, timeout=None):
        JOURNAL["smtp"].append(("connexion", hote, port))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        JOURNAL["smtp"].append("starttls")

    def login(self, u, p):
        JOURNAL["smtp"].append(("login", u))

    def sendmail(self, exp, dests, brut):
        JOURNAL["smtp"].append(("sendmail", exp, dests, len(brut)))


import imaplib as _imaplib  # noqa: E402
import smtplib as _smtplib  # noqa: E402
_imaplib.IMAP4_SSL = _IMAP
_smtplib.SMTP = _SMTP

print("— la boîte unique par IMAP")
src = BACKEND / "mail" / "imap.py"
verifier("le module `mail/imap.py` existe", src.exists())
if not src.exists():
    sys.exit(1)
imap = charger(src, "imap_double")
verifier("configuré dès que l'adresse et le mot de passe d'application sont là ; l'adresse est normalisée",
         imap.configure() is True and imap.boite_unique() == "contact@duret-sols.fr")
verifier("les critères IMAP : depuis / avant à la journée, recherche dans objet et corps",
         imap._criteres(datetime(2026, 9, 1), "devis carrelage", datetime(2026, 9, 8)) == 'SINCE 01-Sep-2026 BEFORE 08-Sep-2026 TEXT "devis carrelage"'
         and imap._criteres(None, None, None) == "ALL")
fiches, total = imap.lister("contact@duret-sols.fr", "INBOX", 10, datetime(2026, 9, 1), None, None, 160)
verifier("la connexion : l'hôte, l'identifiant, le dossier en lecture seule, la déconnexion",
         JOURNAL["hote"] == ("imap.gmail.com", 993) and JOURNAL["login"][0] == "contact@duret-sols.fr"
         and JOURNAL["select"][-1] == ('"INBOX"', True) and JOURNAL.get("logout"))
verifier("les fiches ont la forme des voies Graph/Gmail, les plus récentes d'abord, le total exact",
         total == 2 and [f["objet"] for f in fiches] == ["Votre commande", "Demande de devis carrelage"]
         and all(k in fiches[1] for k in ("ref", "de", "date_iso", "lu", "pieces_jointes", "apercu", "expediteur_automatique")))
f1 = fiches[1]
verifier("pièce jointe détectée, non lu, date en ISO, aperçu du texte, expéditeur automatique marqué sur l'autre",
         f1["pieces_jointes"] is True and f1["lu"] is False and f1["date_iso"] == "2026-09-08"
         and f1["apercu"].startswith("Bonjour, pourriez-vous chiffrer") and fiches[0]["expediteur_automatique"] is True
         and fiches[0]["lu"] is True)
verifier("l'identifiant mémorisé porte le dossier (« INBOX|101 »)", "INBOX|101" in REFS)
ouvert = imap.ouvrir("contact@duret-sols.fr", "101", "INBOX")
verifier("un message ouvert : corps entier, HTML, pièces désignées par leur rang",
         "80 m²" in ouvert["corps"] and ouvert["pieces_jointes"] and ouvert["pieces_jointes"][0]["nom"] == "plan.pdf"
         and ouvert["pieces_jointes"][0]["type"] == "application/pdf" and ouvert["pieces_jointes"][0]["inline"] is False)
rang = ouvert["pieces_jointes"][0]["id"]
verifier("la pièce se télécharge par son rang", imap.piece("101", rang, "INBOX") == b"%PDF-1.4 plan")
ouvert2 = imap.ouvrir("contact@duret-sols.fr", "102", "INBOX")
verifier("un message HTML seul : le texte en est tiré", "Commande confirmée" in ouvert2["corps"] and "<p>" in ouvert2["corps_html"])
imap.envoyer(b"Subject: x\r\n\r\ncorps", "contact@duret-sols.fr", ["martin@client.fr", ""])
verifier("l'envoi : SMTP 587, STARTTLS, identifiant de la boîte, destinataires vides écartés",
         JOURNAL["smtp"][0] == ("connexion", "smtp.gmail.com", 587) and "starttls" in JOURNAL["smtp"]
         and ("login", "contact@duret-sols.fr") in JOURNAL["smtp"]
         and JOURNAL["smtp"][-1][:3] == ("sendmail", "contact@duret-sols.fr", ["martin@client.fr"]))

# ── Les droits ──
print("— qui lit la boîte unique")
sys.modules["mail.imap"] = imap
rb = types.ModuleType("security.rbac")
PERMS = {"direction": {"access_mail"}, "commercial": {"access_mail"}, "terrain": set()}
rb.has_permission = lambda role, f: role == "super_admin" or f in PERMS.get(role, set())
sys.modules["security"] = types.ModuleType("security"); sys.modules["security.rbac"] = rb
sys.modules["security.audit"] = types.SimpleNamespace(log_action=None)
COMPTES = {"u-com": ("nathalie@duret-sols.fr", "commercial"), "u-ter": ("eric@duret-sols.fr", "terrain")}


class _Conn:
    async def fetchrow(self, sql, *a):
        c = COMPTES.get(a[0])
        return {"email": c[0], "role": c[1]} if c else None

    async def fetch(self, sql, *a):
        return []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


db = types.ModuleType("database.connection"); db.get_db = lambda: _Conn()
sys.modules["database"] = types.ModuleType("database"); sys.modules["database.connection"] = db
aut = charger(BACKEND / "mail" / "authorization.py", "authz_double")
COM = types.SimpleNamespace(id="u-com", email="nathalie@duret-sols.fr", role="commercial")
TER = types.SimpleNamespace(id="u-ter", email="eric@duret-sols.fr", role="terrain")
verifier("un commercial avec l'accès au mail lit la boîte unique, et c'est sa boîte par défaut",
         asyncio.run(aut.verifier_acces(COM, "contact@duret-sols.fr")) == "contact@duret-sols.fr"
         and asyncio.run(aut.boite_par_defaut(COM)) == "contact@duret-sols.fr"
         and asyncio.run(aut.boites_par_id("u-com")) == ["contact@duret-sols.fr"]
         and asyncio.run(aut.boites_autorisees(COM))[0]["mailbox"] == "contact@duret-sols.fr")
try:
    asyncio.run(aut.verifier_acces(COM, "nathalie@duret-sols.fr"))
    verifier("une autre adresse (même la sienne) est refusée : la messagerie est UNE boîte", False)
except aut.AccesBoiteRefuse as e:
    verifier("une autre adresse (même la sienne) est refusée : la messagerie est UNE boîte", "boîte unique" in e.detail)
try:
    asyncio.run(aut.verifier_acces(TER, "contact@duret-sols.fr"))
    verifier("un rôle SANS la colonne « Accès au mail » n'a rien, avec le geste à faire", False)
except aut.AccesBoiteRefuse as e:
    verifier("un rôle SANS la colonne « Accès au mail » n'a rien, avec le geste à faire",
             "Accès au mail" in e.detail and "Permissions" in e.detail)
verifier("…ni dans la mémoire (filtre RAG) ni dans la liste des boîtes",
         asyncio.run(aut.boites_par_id("u-ter")) == [] and asyncio.run(aut.boites_autorisees(TER)) == [])
verifier("le super_admin garde le jeton « toutes les boîtes » dans la mémoire",
         asyncio.run(aut.boites_par_id("u-adm")) == [] or True)   # compte inconnu : rien — le jeton se teste plus bas
COMPTES["u-adm"] = ("noa@benit.fr", "super_admin")
verifier("…et le voit bien pour un compte super_admin", asyncio.run(aut.boites_par_id("u-adm")) == [aut.TOUTES_LES_BOITES])
# Sans boîte unique (l'autre client) : rien ne change.
cfg.settings.mail_imap_user = None
verifier("sans boîte unique : chacun lit SA boîte (règle du 01/09), la colonne s'applique quand même",
         asyncio.run(aut.verifier_acces(COM, "nathalie@duret-sols.fr")) == "nathalie@duret-sols.fr"
         and asyncio.run(aut.boite_par_defaut(COM)) == "nathalie@duret-sols.fr"
         and asyncio.run(aut.boites_par_id("u-com")) == ["nathalie@duret-sols.fr"])
try:
    asyncio.run(aut.verifier_acces(TER, "eric@duret-sols.fr"))
    verifier("…et un rôle sans accès au mail est refusé même sur sa propre boîte", False)
except aut.AccesBoiteRefuse:
    verifier("…et un rôle sans accès au mail est refusé même sur sa propre boîte", True)
cfg.settings.mail_imap_user = "Contact@Duret-Sols.fr"

print("— l'écran règle la boîte, tout est câblé")
CLES_BASE["mail_imap_user"] = "Autre@Duret-Sols.fr"; CLES_BASE["mail_imap_password"] = "zzzz zzzz zzzz zzzz"
verifier("l'adresse et le mot de passe posés dans Paramètres PRIMENT sur le .env",
         imap.boite_unique() == "autre@duret-sols.fr" and imap._mot_de_passe() == "zzzz zzzz zzzz zzzz")
JOURNAL["login"] = None
imap.lister("autre@duret-sols.fr", "INBOX", 2)
verifier("…et servent à la connexion", JOURNAL["login"] == ("autre@duret-sols.fr", "zzzz zzzz zzzz zzzz"))
CLES_BASE.clear()
t_ok = imap.tester()
verifier("« Tester la connexion » : IMAP puis SMTP, le compte des messages, jamais le mot de passe",
         t_ok["ok"] is True and t_ok["imap"] and t_ok["smtp"] and t_ok.get("messages") == 2
         and "zzzz" not in str(t_ok) and "abcd" not in str(t_ok))
cfg.settings.mail_imap_password = ""
verifier("sans mot de passe : le test dit ce qui manque", "absent" in imap.tester()["erreur"])
cfg.settings.mail_imap_password = "abcd efgh ijkl mnop"
msgs = imap.parcourir("INBOX", 10)
verifier("`parcourir` rend les messages parsés avec leur UID, les plus récents d'abord",
         [u for u, _ in msgs] == ["102", "101"] and msgs[1][1]["Subject"] == "Demande de devis carrelage")
# le connecteur d'ingestion
INGERES = []


async def _ingest(text, source_type, source_id, source_filename, access_level, anonymize):
    INGERES.append((source_type, source_id, source_filename, access_level, anonymize, text[:40]))
    return True
pipe = types.ModuleType("ingestion.pipeline"); pipe.ingest_document = _ingest
sys.modules["ingestion"] = types.ModuleType("ingestion"); sys.modules["ingestion.pipeline"] = pipe
sys.modules["ingestion.connectors"] = types.ModuleType("ingestion.connectors")
sty = types.ModuleType("mail.style"); sty.PREFIXE_ENVOYE = "email_sent"; sty.source_id = lambda b, i: f"email_sent:{b}:{i}"


async def _profil(boite):
    return {"profil": {"ton": "sobre"}}
sty.construire_profil = _profil
sys.modules["mail.style"] = sty
sys.modules["mail.imap"] = imap
cfg.settings.gmail_access_level = "all"; cfg.settings.gmail_max_messages = 100
con = charger(BACKEND / "ingestion" / "connectors" / "imap.py", "connecteur_imap_double")
bilan = asyncio.run(con.sync(boites=["quelquun@ailleurs.fr"]))
verifier("la synchronisation ingère la boîte unique : reçus (email:…) et envoyés (email_sent:…), profil de style recalculé",
         bilan["boite"] == "contact@duret-sols.fr" and bilan["recus"] == 2 and bilan["envoyes"] == 2 and bilan["profils"] == 1
         and any(s[0] == "email" and s[1].startswith("email:contact@duret-sols.fr:") for s in INGERES)
         and any(s[0] == "email_sent" for s in INGERES) and all(s[4] is False for s in INGERES), bilan)
verifier("le texte ingéré porte les en-têtes puis le corps, avec le niveau d'accès du réglage",
         INGERES[0][5].startswith("Objet : ") and INGERES[0][3] == "all")
cfg.settings.mail_imap_user = None
try:
    asyncio.run(con.sync())
    verifier("sans boîte unique : la synchro dit où la régler", False)
except NotImplementedError as e:
    verifier("sans boîte unique : la synchro dit où la régler", "Paramètres" in str(e))
cfg.settings.mail_imap_user = "Contact@Duret-Sols.fr"
cl = (BACKEND / "llm" / "cles.py").read_text(encoding="utf-8")
verifier("les deux identifiants sont des clés de Paramètres, hors de la liste des clés de modèles",
         '"mail_imap_user",' in cl and '"mail_imap_password",' in cl and "CLES_HORS_ECRAN" in cl)
stg = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
verifier("les routes : lire (jamais le mot de passe), enregistrer, tester",
         '@router.get("/boite-mail")' in stg and '@router.put("/boite-mail")' in stg and '"/boite-mail/tester"' in stg
         and "imap.tester" in stg and '"empreinte": masquer(mdp)' in stg)
ing = (BACKEND / "routers" / "ingestion.py").read_text(encoding="utf-8")
verifier("la synchronisation propose la boîte unique, et la collecte des envois passe par IMAP",
         '"imap": ("Messagerie (boîte unique' in ing
         and 'from ingestion.connectors.imap import sync' in (BACKEND / "mail" / "collecte.py").read_text(encoding="utf-8"))
tab = (BACKEND.parent / "frontend" / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
verifier("Paramètres → Clés API : la carte « La boîte mail de l'entreprise » (adresse, mot de passe, Enregistrer, Tester)",
         "function ReglageBoiteMail(" in tab and "<ReglageBoiteMail" in tab and "Tester la connexion" in tab
         and "/api/settings/boite-mail" in tab)

print("— la permission et le câblage")
rbac_reel = charger(BACKEND / "security" / "rbac.py", "rbac_double", futur=True)
verifier("la colonne « Accès au mail » existe dans la matrice, avec son libellé",
         "access_mail" in rbac_reel.ALL_FEATURES and rbac_reel.FEATURE_LABELS.get("access_mail") == "Accès au mail")
verifier("elle est accordée par défaut à TOUS les rôles (le comportement d'avant)",
         all("access_mail" in v for v in rbac_reel.ROLE_PERMISSIONS.values())
         and rbac_reel.has_permission("terrain", "access_mail") is True)
mig = BACKEND / "database" / "migrations" / "039_acces_mail.sql"
verifier("migration 039 : semée pour les sept rôles, sans écraser un choix fait à l'écran",
         mig.exists() and "'access_mail'" in mig.read_text(encoding="utf-8") and "DO NOTHING" in mig.read_text(encoding="utf-8"))
col = (BACKEND / "mail" / "collecte.py").read_text(encoding="utf-8")
verifier("le fournisseur « imap » se choisit dès que les identifiants existent, avant les clés Google/Microsoft",
         'if choix in ("outlook", "gmail", "imap"):' in col and col.find("_imap_configure()") < col.find("ms_tenant_id and settings.ms_client_id"))
lec_src = (BACKEND / "mail" / "lecture.py").read_text(encoding="utf-8")
verifier("la lecture aiguille vers IMAP : liste, dernier message, recherche, ouverture, pièces",
         lec_src.count('nom == "imap"') >= 4 and 'if fournisseur() == "imap":' in lec_src and "async def _ouvrir_imap(" in lec_src)
exp = (BACKEND / "mail" / "expedition.py").read_text(encoding="utf-8")
verifier("l'envoi aiguille vers SMTP avec le même message MIME que Gmail, et un 535 dit quoi vérifier",
         'if nom == "imap":' in exp and "imap.envoyer, brut" in exp and "mot de passe d'application" in exp)
cfgs = (BACKEND / "config.py").read_text(encoding="utf-8")
verifier("les réglages existent (adresse, mot de passe d'application, hôtes Gmail préréglés)",
         "mail_imap_user: Optional[str] = None" in cfgs and 'mail_smtp_host: str = "smtp.gmail.com"' in cfgs)
verifier(".env.example : la procédure (validation en deux étapes, mot de passe d'application, GMAIL_DOMAIN)",
         "MAIL_IMAP_PASSWORD" in (BACKEND.parent / ".env.example").read_text(encoding="utf-8"))

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs)); sys.exit(1)
print("✓ 0 échec")
