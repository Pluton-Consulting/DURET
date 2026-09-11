"""
Banc « L'AGENDA D'UN COMPTE GMAIL, ET LE CHOIX DES MODÈLES QUI NE BUGUE PLUS » (11/09).

Deux relevés de Noa, le même jour :
  1. « il faut que ça ait accès aussi à Calendar » — sur un compte Gmail
     PERSONNEL. Le mot de passe d'application n'ouvre que IMAP/SMTP, Google a
     fermé CalDAV à tout sauf OAuth, et un compte de service n'emprunte que les
     boîtes d'un domaine Workspace : la seule voie est la connexion OAuth du
     compte ;
  2. « dans Clés API je ne peux pas changer les modèles embeddings ou OCR, ça
     bug » — la liste filtrée de ces deux lignes changeait d'identité à chaque
     rendu et remettait le menu sur la valeur en vigueur ; et la ligne des
     embeddings proposait des fournisseurs de texte, refusés à l'écriture.

CE QUE CE BANC PROUVE (modules EXÉCUTÉS contre des doublures de Google et de
la base) :
  * le client OAuth se lit dans Paramètres avant le `.env` ; le lien de
    consentement demande l'agenda et présélectionne le compte attendu ;
  * les droits ACCORDÉS sont retenus par compte : un compte relié avant
    l'agenda garde son mail (on ne redemande pas un droit jamais accordé) et
    se sait « relié sans l'agenda » ;
  * l'agenda passe par Google Calendar dès que la messagerie est Google —
    boîte unique par mot de passe d'application comprise — : lecture déployée
    (récurrences), événements annulés écartés, journées entières lisibles,
    invitations envoyées seulement s'il y a des invités ; chaque refus se dit
    avec le geste à faire ;
  * l'écran ne propose, sur chaque ligne de modèle, que les fournisseurs que
    l'écriture acceptera, et la vision n'accepte plus un fournisseur aveugle.
Tombe sur la version d'avant.
"""
import asyncio
import pathlib
import sys
import types
import urllib.parse
from datetime import datetime, timezone

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []
AGENDA_SCOPE = "https://www.googleapis.com/auth/calendar.events"


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


print(f"\n═══ L'AGENDA D'UN COMPTE GMAIL, ET LE CHOIX DES MODÈLES — {BACKEND.parent}\n")

# ── Doublures communes ──
cfg = types.ModuleType("config")
cfg.settings = types.SimpleNamespace(
    app_url="https://assistant.exemple.fr/", google_oauth_client_id="env-id.apps.googleusercontent.com",
    google_oauth_client_secret="env-secret", google_sa_json=None, google_sa_file="/nulle/part.json",
    gmail_domain=None, google_admin_subject=None)
sys.modules["config"] = cfg

LIGNES_GOOGLE = []   # la table connexions_google doublée
ECRITES = []


class _Conn:
    async def fetch(self, sql, *a):
        if "connexions_google" in sql:
            return list(LIGNES_GOOGLE)
        if "FROM reglages" in sql:
            return []
        raise RuntimeError("base doublée")

    async def execute(self, sql, *a):
        ECRITES.append((sql, a))


class _Ctx:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


dbc = types.ModuleType("database.connection")
dbc.get_db = lambda: _Ctx()
sys.modules["database"] = types.ModuleType("database")
sys.modules["database.connection"] = dbc
for paquet in ("llm", "mail"):
    sys.modules[paquet] = types.ModuleType(paquet)
    sys.modules[paquet].__path__ = [str(BACKEND / paquet)]
cles = charger(BACKEND / "llm" / "cles.py", "llm.cles")
cles._EXPIRE = 10 ** 12   # cache piloté à la main

jwt = types.ModuleType("auth.jwt_handler")
jwt.create_access_token = lambda donnees, expires_delta=None: "etat-signe"
sys.modules["auth"] = types.ModuleType("auth")
sys.modules["auth.jwt_handler"] = jwt


class FakeCredentials:
    def __init__(self, **k):
        self.__dict__.update(k)


cred_mod = types.ModuleType("google.oauth2.credentials")
cred_mod.Credentials = FakeCredentials
sys.modules["google"] = types.ModuleType("google")
sys.modules["google.oauth2"] = types.ModuleType("google.oauth2")
sys.modules["google.oauth2.credentials"] = cred_mod

# ── 1. Le choix des modèles (socle) ──
print("— le choix des modèles : ce que l'écriture accepte")
reglages = charger(BACKEND / "llm" / "reglages.py", "llm.reglages")


def accepte(nom, valeur):
    try:
        asyncio.run(reglages.enregistrer(nom, valeur, "u1"))
        return True
    except ValueError:
        return False


verifier("la vision refuse un fournisseur qui ne voit pas (DeepSeek)", not accepte("modele_vision", "deepseek:deepseek-chat"))
verifier("la vision refuse LongCat", not accepte("modele_vision", "longcat:LongCat-2.0"))
verifier("la vision accepte le modèle d'OCR en place (OpenRouter)", accepte("modele_vision", "openrouter:google/gemini-2.5-pro"))
verifier("la vision accepte Google", accepte("modele_vision", "google:gemini-flash-latest"))
verifier("les embeddings refusent un fournisseur de texte", not accepte("modele_embedding", "longcat:LongCat-2.0"))
verifier("les embeddings acceptent le modèle Google", accepte("modele_embedding", "google:gemini-embedding-001"))
verifier("le texte garde ses fournisseurs", accepte("modele_rapide", "longcat:LongCat-2.0"))

src_router = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")
bloc_catalogue = src_router.split("def catalogue_modeles")[1].split("\ndef ")[0]
verifier("chaque fiche du catalogue dit ce que le fournisseur sait faire",
         '"usages"' in bloc_catalogue and "FOURNISSEURS_VISION" in bloc_catalogue
         and "FOURNISSEURS_EMBEDDING" in bloc_catalogue)
verifier("le modèle d'embedding Google et le modèle d'OCR figurent au catalogue",
         "gemini_embedding_model" in bloc_catalogue and "model_openrouter_vision" in bloc_catalogue)
verifier("la vision de l'écriture est celle de la cascade",
         all(f'"{p}"' in src_router.split("def get_vision_candidates")[1].split("\ndef ")[0]
             for p in reglages.FOURNISSEURS_VISION))

src_tab = (FRONTEND / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
ligne = src_tab.split("function LigneModele")[1].split("\nfunction ")[0]
verifier("la liste filtrée est MÉMORISÉE (sinon le menu revient en arrière à chaque frappe)",
         "const fiches = useMemo(" in ligne and "[toutesFiches, usage]" in ligne, ligne[:0])
verifier("seuls les fournisseurs capables sont proposés sur la ligne",
         "f.usages.includes(usage" in ligne)
verifier("aucun modèle d'embedding sur une ligne qui doit répondre", 'm.usage !== "embedding"' in ligne)

# ── 2. La connexion Google : client, lien, droits accordés (socle) ──
print("— la connexion Google : client de Paramètres, droits accordés")
gp = charger(BACKEND / "mail" / "google_perso.py", "mail.google_perso")
sys.modules["mail"].google_perso = gp
verifier("sans surcharge, le client vient du .env", gp._client() == ("env-id.apps.googleusercontent.com", "env-secret"))
cles._CACHE.update(google_oauth_client_id="ecran.apps.googleusercontent.com", google_oauth_client_secret="ecran-secret")
verifier("le client de Paramètres passe avant", gp._client() == ("ecran.apps.googleusercontent.com", "ecran-secret"))
verifier("il suffit à rendre la connexion configurable", gp.configurable())
url = gp.lien_autorisation("u1", "Contact@Exemple-Sols.fr")
q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
verifier("le lien porte le client de Paramètres", q.get("client_id") == "ecran.apps.googleusercontent.com")
verifier("le compte attendu est présélectionné", q.get("login_hint") == "contact@exemple-sols.fr", q)
verifier("sans compte attendu, aucune présélection", "login_hint" not in gp.lien_autorisation("u1"))
DEMANDES = q.get("scope", "").split()
verifier("le lien demande les droits du client (l agenda chez Duret)", AGENDA_SCOPE in DEMANDES or "drive" in q.get("scope", ""), DEMANDES)
verifier("les droits d'avant l'agenda n'incluent pas l'agenda",
         all("/auth/calendar" not in x for x in gp.SCOPES_HISTORIQUES) and len(gp.SCOPES_HISTORIQUES) >= 1)

LIGNES_GOOGLE[:] = [
    {"user_id": "u1", "email": "contact@exemple-sols.fr", "refresh_token": "rt-1",
     "scopes": "openid https://www.googleapis.com/auth/gmail.readonly "
               "https://www.googleapis.com/auth/gmail.send " + AGENDA_SCOPE},
    {"user_id": "u2", "email": "ancien@exemple-sols.fr", "refresh_token": "rt-2", "scopes": ""},
]
asyncio.run(gp.rafraichir(force=True))
verifier("un compte relié avec l'agenda le dit", gp.accorde("contact@exemple-sols.fr", AGENDA_SCOPE) is True)
verifier("un compte relié AVANT l'agenda se sait sans l'agenda", gp.accorde("ancien@exemple-sols.fr", AGENDA_SCOPE) is False)
verifier("un compte relié avant l'agenda garde ses droits de mail",
         gp.accorde("ancien@exemple-sols.fr", gp.SCOPES_HISTORIQUES[0]) is True)
verifier("un compte non relié : ni oui ni non", gp.accorde("inconnu@exemple-sols.fr", AGENDA_SCOPE) is None)
c = gp.credentials_pour_boite("contact@exemple-sols.fr")
verifier("le jeton ne redemande QUE les droits accordés (openid écarté)",
         c.scopes == ["https://www.googleapis.com/auth/gmail.readonly",
                      "https://www.googleapis.com/auth/gmail.send", AGENDA_SCOPE], c.scopes)
verifier("et porte le client de Paramètres", c.client_id == "ecran.apps.googleusercontent.com" and c.client_secret == "ecran-secret")
c2 = gp.credentials_pour_boite("ancien@exemple-sols.fr")
verifier("le compte ancien ne demande pas l'agenda (sinon Google refuserait TOUT, mail compris)",
         AGENDA_SCOPE not in c2.scopes and list(c2.scopes) == list(gp.SCOPES_HISTORIQUES), c2.scopes)

# ── 3. La voie Google de l'agenda ──
print("— l'agenda passe par Google Calendar")
ETAT = {"fournisseur": "imap", "gmail": True}
coll = types.ModuleType("mail.collecte")
coll.fournisseur = lambda: ETAT["fournisseur"]
coll._module_present = lambda chemin: ETAT["gmail"]
sys.modules["mail.collecte"] = coll
agenda = charger(BACKEND / "mail" / "agenda.py", "mail.agenda")
verifier("boîte unique par mot de passe d'application : l'agenda passe par Google", agenda._voie() == "google")
ETAT["fournisseur"] = "gmail"
verifier("messagerie Gmail : Google aussi", agenda._voie() == "google")
ETAT["fournisseur"] = "outlook"
verifier("Microsoft 365 : Graph, inchangé", agenda._voie() == "outlook")
ETAT.update(fournisseur="imap", gmail=False)
try:
    agenda._voie()
    verifier("sans connecteur Google, la voie le dit", False)
except agenda.AgendaIndisponible as e:
    verifier("sans connecteur Google, la voie le dit", "OAuth" in str(e))
ETAT["gmail"] = True

f = agenda._fiche_google({"summary": "Visite Duval", "start": {"dateTime": "2026-09-14T09:00:00+02:00"},
                          "end": {"dateTime": "2026-09-14T10:00:00+02:00"}, "location": "Mérignac",
                          "organizer": {"email": "contact@exemple-sols.fr"},
                          "attendees": [{"email": "duval@exemple.fr"}, {"email": "salle@r", "resource": True}],
                          "hangoutLink": "https://meet.google.com/abc"}, "contact@exemple-sols.fr")
verifier("un événement Google a les champs d'un événement Graph",
         f["titre"] == "Visite Duval" and f["lieu"] == "Mérignac" and f["participants"] == ["duval@exemple.fr"]
         and f["en_ligne"] and not f["journee_entiere"], f)
verifier("son heure se lit (fuseau compris)",
         agenda._analyser(f["debut"]) == datetime(2026, 9, 14, 7, 0, tzinfo=timezone.utc))
j = agenda._fiche_google({"summary": "Congés", "start": {"date": "2026-09-15"}, "end": {"date": "2026-09-16"}}, "b")
verifier("une journée entière se lit comme telle", j["journee_entiere"] and agenda._analyser(j["debut"]) is not None, j)

GMAIL = BACKEND / "ingestion" / "connectors" / "gmail.py"
if not GMAIL.exists():
    print("\n  (pas de connecteur Gmail dans ce projet : la voie Google de l'agenda n'y a pas d'objet)")
else:
    APPELS = []
    REFUS = {}

    class _Exec:
        def __init__(self, nom, k):
            self.nom, self.k = nom, k

        def execute(self):
            APPELS.append((self.nom, self.k))
            if self.nom in REFUS:
                raise RuntimeError(REFUS[self.nom])
            if self.nom == "list":
                return {"items": [
                    {"summary": "Chantier Ikos", "status": "confirmed",
                     "start": {"dateTime": "2026-09-14T08:00:00+02:00"}, "end": {"dateTime": "2026-09-14T12:00:00+02:00"}},
                    {"summary": "Occurrence annulée", "status": "cancelled",
                     "start": {"dateTime": "2026-09-14T14:00:00+02:00"}, "end": {"dateTime": "2026-09-14T15:00:00+02:00"}},
                ]}
            return dict(self.k["body"], id="ev1")

    class FakeCalendar:
        def __init__(self, creds):
            self.creds = creds

        def events(self):
            return self

        def list(self, **k):
            return _Exec("list", k)

        def insert(self, **k):
            return _Exec("insert", k)

    CONSTRUITS = []

    def build(nom, version, credentials=None, cache_discovery=False):
        CONSTRUITS.append((nom, credentials))
        return FakeCalendar(credentials)

    disco = types.ModuleType("googleapiclient.discovery")
    disco.build = build
    sys.modules["googleapiclient"] = types.ModuleType("googleapiclient")
    sys.modules["googleapiclient.discovery"] = disco
    sa = types.ModuleType("google.oauth2.service_account")
    sa.Credentials = types.SimpleNamespace(
        from_service_account_info=lambda info, scopes=None, subject=None: FakeCredentials(scopes=scopes, subject=subject))
    sys.modules["google.oauth2.service_account"] = sa
    sys.modules["google.oauth2"].service_account = sa
    for nom in ("ingestion", "ingestion.connectors"):
        sys.modules[nom] = types.ModuleType(nom)
    sys.modules["ingestion"].__path__ = [str(BACKEND / "ingestion")]
    sys.modules["ingestion.connectors"].__path__ = [str(BACKEND / "ingestion" / "connectors")]
    pipe = types.ModuleType("ingestion.pipeline")
    pipe.ingest_document = None
    sys.modules["ingestion.pipeline"] = pipe
    style = types.ModuleType("mail.style")
    style.source_id, style.PREFIXE_ENVOYE = (lambda *a: ""), "envoye:"
    sys.modules["mail.style"] = style
    gmail = charger(GMAIL, "ingestion.connectors.gmail")

    print("— le client Google Agenda du connecteur")
    verifier("l'agenda a son propre droit", gmail.SCOPES_AGENDA == [AGENDA_SCOPE])
    service = gmail._service_agenda("contact@exemple-sols.fr")
    verifier("compte relié avec l'agenda : Google Agenda avec SA connexion",
             CONSTRUITS[-1][0] == "calendar" and CONSTRUITS[-1][1].refresh_token == "rt-1")
    try:
        gmail._service_agenda("ancien@exemple-sols.fr")
        verifier("compte relié avant l'agenda : « reliez à nouveau »", False)
    except NotImplementedError as e:
        verifier("compte relié avant l'agenda : « reliez à nouveau »", "sans l'agenda" in str(e) and "Relier" in str(e))
    try:
        gmail._service_agenda("personne@exemple-sols.fr")
        verifier("compte jamais relié, sans compte de service : le geste à faire", False)
    except NotImplementedError as e:
        verifier("compte jamais relié, sans compte de service : le geste à faire",
                 "client OAuth" in str(e) and "Relier l'agenda Google" in str(e))

    print("— lire et poser des rendez-vous")
    evenements = asyncio.run(agenda.lire("contact@exemple-sols.fr",
                                         datetime(2026, 9, 14, tzinfo=timezone.utc),
                                         datetime(2026, 9, 21, tzinfo=timezone.utc)))
    nom, k = APPELS[-1]
    verifier("la période est DÉPLOYÉE (récurrences) et triée",
             nom == "list" and k["singleEvents"] is True and k["orderBy"] == "startTime" and k["calendarId"] == "primary", k)
    verifier("les bornes portent leur fuseau", k["timeMin"].endswith("+00:00") and k["timeMax"].endswith("+00:00"), k)
    verifier("une occurrence annulée n'est pas un rendez-vous", [e["titre"] for e in evenements] == ["Chantier Ikos"], evenements)
    prises = asyncio.run(agenda.occupations("contact@exemple-sols.fr", datetime(2026, 9, 14, tzinfo=timezone.utc),
                                            datetime(2026, 9, 21, tzinfo=timezone.utc)))
    verifier("les créneaux se calculent sur l'agenda Google (8 h à Paris = 6 h UTC)",
             prises and prises[0][0] == datetime(2026, 9, 14, 6, tzinfo=timezone.utc), prises)

    cree = asyncio.run(agenda.creer("contact@exemple-sols.fr", "Visite Duval",
                                    datetime(2026, 9, 15, 7, tzinfo=timezone.utc),
                                    datetime(2026, 9, 15, 8, tzinfo=timezone.utc),
                                    ["duval@exemple.fr", "pas-une-adresse"], "Mérignac", "Métré"))
    nom, k = APPELS[-1]
    verifier("un rendez-vous avec invités part AVEC les invitations",
             nom == "insert" and k["sendUpdates"] == "all" and k["body"]["attendees"] == [{"email": "duval@exemple.fr"}], k)
    verifier("titre, lieu et note arrivent", k["body"]["summary"] == "Visite Duval"
             and k["body"]["location"] == "Mérignac" and k["body"]["description"] == "Métré")
    verifier("le rendez-vous créé revient sous la forme commune", cree["titre"] == "Visite Duval")
    asyncio.run(agenda.creer("contact@exemple-sols.fr", "Bloc chantier",
                             datetime(2026, 9, 16, 7, tzinfo=timezone.utc), datetime(2026, 9, 16, 8, tzinfo=timezone.utc)))
    verifier("sans invité, personne n'est prévenu", APPELS[-1][1]["sendUpdates"] == "none")

    REFUS["list"] = "<HttpError 403 \"Request had insufficient authentication scopes.\">"
    try:
        asyncio.run(agenda.lire("contact@exemple-sols.fr", datetime(2026, 9, 14, tzinfo=timezone.utc),
                                datetime(2026, 9, 15, tzinfo=timezone.utc)))
        verifier("un droit manquant se dit « reliez à nouveau »", False)
    except agenda.AgendaIndisponible as e:
        verifier("un droit manquant se dit « reliez à nouveau »", "reliez-le à nouveau" in str(e), str(e))
    REFUS["list"] = "Google Calendar API has not been used in project 42 before or it is disabled"
    try:
        asyncio.run(agenda.lire("contact@exemple-sols.fr", datetime(2026, 9, 14, tzinfo=timezone.utc),
                                datetime(2026, 9, 15, tzinfo=timezone.utc)))
        verifier("une API non activée nomme « Google Calendar API »", False)
    except agenda.AgendaIndisponible as e:
        verifier("une API non activée nomme « Google Calendar API »", "Google Calendar API" in str(e), str(e))
    REFUS.clear()
    try:
        asyncio.run(agenda.lire("personne@exemple-sols.fr", datetime(2026, 9, 14, tzinfo=timezone.utc),
                                datetime(2026, 9, 15, tzinfo=timezone.utc)))
        verifier("un compte non relié : un refus lisible, pas une exception technique", False)
    except agenda.AgendaIndisponible as e:
        verifier("un compte non relié : un refus lisible, pas une exception technique", "client OAuth" in str(e))

    # ── 4. L'écran ──
    print("— l'écran")
    src_settings = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
    verifier("la carte de la boîte mail reçoit l'état de l'agenda",
             '"agenda": agenda' in src_settings and "SCOPES_AGENDA" in src_settings)
    verifier("le client OAuth se saisit dans Paramètres",
             '@router.put("/client-oauth-google")' in src_settings and 'enregistrer("google_oauth_client_secret"' in src_settings)
    verifier("la carte de la boîte mail relie l'agenda avec le compte présélectionné",
             "/api/google/lien?compte=" in src_tab and "Relier l'agenda Google" in src_tab)
    verifier("la carte du client OAuth donne l'adresse de redirection à coller",
             "function ReglageClientOAuth" in src_tab and "etat.redirection" in src_tab
             and src_tab.find("<ReglageClientOAuth") > src_tab.find("<ReglageBoiteMail"))
    src_param = (FRONTEND / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
    verifier("au retour de Google, Paramètres rouvre l'onglet d'où l'on est parti",
             "parametres_retour_google" in src_param and "parametres_retour_google" in src_tab)

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
