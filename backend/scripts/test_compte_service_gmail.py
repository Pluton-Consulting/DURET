"""
Banc « GMAIL PAR COMPTE DE SERVICE, SAISI DANS PARAMÈTRES » (11/09).

Demande de Noa : « pour Duret j'aimerais connecter Gmail via compte de service,
prévois ça pour que je rentre les clés ». Jusqu'ici la clé ne se posait que
dans le `.env` du serveur (GOOGLE_SA_JSON) ou en fichier sous `secrets/`.

CE QUE CE BANC PROUVE (modules EXÉCUTÉS contre des doublures de Google et de
la base) :
  * socle — la clé, le domaine et l'administrateur entrent dans la liste
    FERMÉE des clés surchargeables, sans jamais apparaître dans la liste des
    clés de modèles ; le domaine saisi à l'écran est celui que lit le
    cloisonnement des boîtes ; la route répond « indisponible » là où le
    connecteur Gmail n'existe pas, et la carte se cache ;
  * connecteur (là où il existe) — une clé collée est vérifiée et remise sur
    une ligne, la clé d'un client OAuth est refusée EN LE NOMMANT ; la clé de
    Paramètres passe avant le `.env`, qui passe avant le fichier ; l'état rendu
    à l'écran ne contient JAMAIS la clé privée mais donne l'identifiant et les
    champs à coller dans la console Admin ; le test éprouve lecture, envoi et
    annuaire SÉPARÉMENT, chacun sur la bonne identité, et traduit les refus de
    Google en gestes à faire ; la messagerie est reconnue « gmail » dès que la
    clé est dans Paramètres. Tombe sur la version d'avant.
"""
import asyncio
import json
import pathlib
import sys
import time
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
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


print(f"\n═══ GMAIL PAR COMPTE DE SERVICE — {BACKEND.parent}\n")

# ── Doublures communes ──
FICHIER_SA = BACKEND / "secrets" / "__banc_inexistant__.json"
cfg = types.ModuleType("config")
cfg.settings = types.SimpleNamespace(
    google_sa_json=None, google_sa_file=str(FICHIER_SA), gmail_domain="env-sols.fr",
    google_admin_subject=None, ms_domain=None, mail_provider="auto",
    ms_tenant_id=None, ms_client_id=None, ms_client_secret=None,
    google_oauth_client_id=None, google_oauth_client_secret=None,
    gmail_decouvrir_domaine=True, gmail_extra_mailboxes=None,
    ollama_cloud_api_key=None, longcat_api_key=None, deepseek_api_key=None,
    openrouter_api_key=None, groq_api_key=None, anthropic_api_key=None, google_api_key=None,
    mail_imap_user=None, mail_imap_password=None)
sys.modules["config"] = cfg

LIGNES_USERS = []


class _Conn:
    async def fetch(self, *a):
        raise RuntimeError("base doublée : pas de cles_api")

    async def fetchval(self, sql, *a):
        motif = (a[0] if a else "").lstrip("%")
        for adresse in LIGNES_USERS:
            if adresse.endswith(motif):
                return adresse
        return None


class _Ctx:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


dbc = types.ModuleType("database.connection")
dbc.get_db = lambda: _Ctx()
sys.modules["database"] = types.ModuleType("database")
sys.modules["database.connection"] = dbc
sys.modules["llm"] = types.ModuleType("llm")
sys.modules["llm"].__path__ = [str(BACKEND / "llm")]

# ── 1. llm/cles.py (socle) ──
print("— la liste fermée des clés")
cles = charger(BACKEND / "llm" / "cles.py", "llm.cles")
for nom in ("google_sa_json", "gmail_domain", "google_admin_subject"):
    verifier(f"« {nom} » est une clé surchargeable", nom in cles.CLES_CONNUES)
    verifier(f"« {nom} » n'apparaît pas parmi les clés de modèles", nom in cles.CLES_HORS_ECRAN)
lignes = asyncio.run(cles.etat())
noms = {l["cle"] for l in lignes}
verifier("l'état des clés de modèles ne montre ni la clé JSON ni le domaine",
         not noms & {"google_sa_json", "gmail_domain", "google_admin_subject"}, sorted(noms))
# Le cache est piloté à la main : pas de rafraîchissement dans le dos du banc.
cles._EXPIRE = time.monotonic() + 3600

# ── 2. Le domaine saisi à l'écran est celui du cloisonnement (socle) ──
print("— le domaine de Paramètres fait foi")
fa = types.ModuleType("fastapi")


class HTTPException(Exception):
    def __init__(self, status_code=403, detail=""):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


fa.HTTPException = HTTPException
fa.status = types.SimpleNamespace(HTTP_403_FORBIDDEN=403)
sys.modules["fastapi"] = fa
sys.modules["mail"] = types.ModuleType("mail")
sys.modules["mail"].__path__ = [str(BACKEND / "mail")]
autorisation = charger(BACKEND / "mail" / "authorization.py", "mail.authorization")
verifier("sans surcharge, le domaine vient du .env",
         "env-sols.fr" in autorisation.domaines_messagerie())
cles._CACHE["gmail_domain"] = "ecran-sols.fr"
d = autorisation.domaines_messagerie()
verifier("avec une surcharge, le domaine vient de Paramètres", "ecran-sols.fr" in d and "env-sols.fr" not in d, d)
cles._CACHE.pop("gmail_domain")

# ── 3. La route et la carte (contrat, socle) ──
print("— la route et la carte")
src_settings = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
for route in ('@router.get("/compte-service-google")', '@router.put("/compte-service-google")',
              '@router.post("/compte-service-google/tester")'):
    verifier(f"route {route.split('(')[1][:-1]}", route in src_settings)
verifier("la route se tait là où le connecteur Gmail n'existe pas",
         'find_spec("ingestion.connectors.gmail")' in src_settings and '{"disponible": False}' in src_settings)
bloc_put = src_settings.split('async def ecrire_compte_service')[1].split("@router")[0]
verifier("la clé est VÉRIFIÉE avant d'être enregistrée",
         bloc_put.find("valider_cle") != -1
         and bloc_put.find("valider_cle") < bloc_put.find('enregistrer("google_sa_json"'))
verifier("le journal d'audit ne recopie aucune valeur",
         '"cle_posee": bool(cle)' in bloc_put and "metadata={\"cle\": cle" not in bloc_put)
verifier("les trois routes exigent l'administration système",
         src_settings.split("GMAIL PAR COMPTE DE SERVICE")[1].split("def _moteur_images_present")[0]
         .count('has_permission(current_user.role, "manage_system")') == 3)
src_tab = (FRONTEND / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
verifier("la carte existe et s'affiche sous la boîte mail",
         "function ReglageCompteServiceGoogle" in src_tab
         and src_tab.find("<ReglageBoiteMail") < src_tab.find("<ReglageCompteServiceGoogle"))
verifier("la carte se cache quand la route dit « indisponible »",
         "etat?.disponible === false) return null" in src_tab)
verifier("la carte ne lit jamais la clé privée", "etat.private_key" not in src_tab and "etat?.private_key" not in src_tab)
verifier("la carte donne l'ID client et les champs à coller", "etat.client_id" in src_tab and "etat.a_coller" in src_tab)
verifier("la carte prévient quand la boîte unique passe avant", 'etat?.fournisseur === "imap"' in src_tab)

# ── Le connecteur Gmail, là où il existe ──
GMAIL = BACKEND / "ingestion" / "connectors" / "gmail.py"
if not GMAIL.exists():
    print("\n  (pas de connecteur Gmail dans ce projet : la carte est cachée, rien d'autre à éprouver)")
else:
    # Doublures de Google : chaque jeton se refuse ou s'accorde selon (scope, identité).
    REFUS = {}          # (scope, sujet) -> message d'erreur de Google
    JETONS = []         # (scopes, sujet) demandés, dans l'ordre
    PROFIL = {"messagesTotal": 1234, "emailAddress": ""}

    class FakeCreds:
        def __init__(self, info, scopes=None, subject=None):
            self.info, self.scopes, self.subject = info, list(scopes or []), subject

        def refresh(self, requete):
            JETONS.append((tuple(self.scopes), self.subject))
            cle = (self.scopes[0] if self.scopes else "", self.subject)
            if cle in REFUS:
                raise RuntimeError(REFUS[cle])

    class Credentials:
        @staticmethod
        def from_service_account_info(info, scopes=None, subject=None):
            if "CASSEE" in info.get("private_key", ""):
                raise ValueError("Could not deserialize key data")
            return FakeCreds(info, scopes, subject)

    class _Exec:
        def __init__(self, valeur):
            self.valeur = valeur

        def execute(self):
            if isinstance(self.valeur, Exception):
                raise self.valeur
            return self.valeur

    class FakeService:
        def __init__(self, nom, creds):
            self.nom, self.creds = nom, creds

        def users(self):
            return self

        def getProfile(self, userId):
            return _Exec(dict(PROFIL, emailAddress=self.creds.subject))

        def list(self, **k):
            return _Exec({"users": [{"primaryEmail": "a@exemple-sols.fr"}]})

    sa = types.ModuleType("google.oauth2.service_account")
    sa.Credentials = Credentials
    sys.modules["google"] = types.ModuleType("google")
    sys.modules["google.oauth2"] = types.ModuleType("google.oauth2")
    sys.modules["google.oauth2"].service_account = sa
    sys.modules["google.oauth2.service_account"] = sa
    req = types.ModuleType("google.auth.transport.requests")
    req.Request = lambda: None
    for nom in ("google.auth", "google.auth.transport"):
        sys.modules[nom] = types.ModuleType(nom)
    sys.modules["google.auth.transport.requests"] = req
    disco = types.ModuleType("googleapiclient.discovery")
    disco.build = lambda nom, version, credentials=None, cache_discovery=False: FakeService(nom, credentials)
    sys.modules["googleapiclient"] = types.ModuleType("googleapiclient")
    sys.modules["googleapiclient.discovery"] = disco
    perso = types.ModuleType("mail.google_perso")
    perso.credentials_pour_boite = lambda boite: None
    sys.modules["mail.google_perso"] = perso
    sys.modules["mail"].google_perso = perso
    pipe = types.ModuleType("ingestion.pipeline")
    pipe.ingest_document = None
    style = types.ModuleType("mail.style")
    style.source_id, style.PREFIXE_ENVOYE = (lambda *a: ""), "envoye:"
    sys.modules["mail.style"] = style
    sys.modules["ingestion"] = types.ModuleType("ingestion")
    sys.modules["ingestion"].__path__ = [str(BACKEND / "ingestion")]
    sys.modules["ingestion.connectors"] = types.ModuleType("ingestion.connectors")
    sys.modules["ingestion.connectors"].__path__ = [str(BACKEND / "ingestion" / "connectors")]
    sys.modules["ingestion.pipeline"] = pipe
    gmail = charger(GMAIL, "ingestion.connectors.gmail")

    CLE = {
        "type": "service_account", "project_id": "duret-mail",
        "private_key_id": "0123456789abcdef0123456789abcdef01234567",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQ-FAUSSE-CLE-DE-BANC\n-----END PRIVATE KEY-----\n",
        "client_email": "assistant@duret-mail.iam.gserviceaccount.com",
        "client_id": "104857600000000000001",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    jolie = json.dumps(CLE, indent=2)

    # ── 4. valider_cle ──
    print("— la clé collée est vérifiée")
    une_ligne = gmail.valider_cle(jolie)
    verifier("une clé sur plusieurs lignes est acceptée et remise sur UNE ligne",
             "\n" not in une_ligne.replace("\\n", "") and json.loads(une_ligne) == CLE)

    def refusee(brut, attendu):
        try:
            gmail.valider_cle(brut)
        except ValueError as e:
            return attendu.lower() in str(e).lower(), str(e)
        return False, "acceptée"

    for nom, brut, attendu in (
        ("un texte qui n'est pas du JSON", "clé : abc", "JSON"),
        ("la clé d'un client OAuth, nommée comme telle", json.dumps({"web": {"client_id": "x"}}), "client OAuth"),
        ("un autre type de fichier", json.dumps(dict(CLE, type="authorized_user")), "service_account"),
        ("une clé sans clé privée", json.dumps({k: v for k, v in CLE.items() if k != "private_key"}), "private_key"),
        ("une clé privée tronquée", json.dumps(dict(CLE, private_key="MIIEvQ")), "tronquée"),
        ("une clé privée que Google ne lit pas", json.dumps(dict(CLE, private_key=CLE["private_key"] + "CASSEE")), "refusée"),
        ("rien du tout", "   ", "aucune"),
    ):
        ok, detail = refusee(brut, attendu)
        verifier(f"refusé : {nom}", ok, detail)

    # ── 5. La priorité : Paramètres > .env > fichier ──
    print("— la clé de Paramètres passe avant le .env")
    verifier("rien de configuré : aucune clé", gmail._cle_compte_de_service() is None)
    cfg.settings.google_sa_json = json.dumps(dict(CLE, client_id="ENV"))
    verifier("la clé du .env est lue", gmail._cle_compte_de_service()["client_id"] == "ENV")
    cles._CACHE["google_sa_json"] = une_ligne
    verifier("la clé de Paramètres passe avant", gmail._cle_compte_de_service()["client_id"] == CLE["client_id"])
    verifier("son origine se dit « parametres »", gmail._origine_cle() == "parametres")
    cfg.settings.google_sa_json = None

    # ── 6. L'état de la carte ──
    print("— l'état rendu à l'écran")
    cles._CACHE["gmail_domain"] = "exemple-sols.fr"
    cles._CACHE["google_admin_subject"] = "Admin@Exemple-Sols.fr"
    etat = gmail.etat_compte_de_service()
    dump = json.dumps(etat)
    verifier("la clé privée ne sort JAMAIS", "PRIVATE KEY" not in dump and "FAUSSE-CLE" not in dump)
    verifier("l'identifiant de la clé n'est qu'une empreinte",
             CLE["private_key_id"] not in dump and etat["empreinte"].startswith("0123"))
    verifier("l'ID client et l'adresse du compte sont donnés",
             etat["client_id"] == CLE["client_id"] and etat["compte"] == CLE["client_email"])
    verifier("les champs à coller : lecture, envoi, annuaire, dans cet ordre",
             etat["a_coller"] == ",".join([gmail.SCOPES[0], gmail.SCOPES_ENVOI[0], gmail.SCOPES_ANNUAIRE[0]]),
             etat.get("a_coller"))
    verifier("le domaine et l'administrateur de Paramètres",
             etat["domaine"] == "exemple-sols.fr" and etat["administrateur"] == "admin@exemple-sols.fr")

    # ── 7. Le service Gmail emprunte la boîte avec la clé de Paramètres ──
    print("— la lecture passe par la clé de Paramètres")
    service = gmail._service("julie@exemple-sols.fr")
    verifier("l'identité empruntée est la boîte, en lecture seule",
             service.creds.subject == "julie@exemple-sols.fr" and service.creds.scopes == gmail.SCOPES
             and service.creds.info["client_id"] == CLE["client_id"])
    envoi = gmail._service_envoi("julie@exemple-sols.fr")
    verifier("l'envoi n'a que le champ d'envoi", envoi.creds.scopes == gmail.SCOPES_ENVOI)

    # ── 8. Le test, champ par champ ──
    print("— le test éprouve chaque autorisation")
    JETONS.clear()
    r = gmail.tester_compte_de_service("admin@exemple-sols.fr")
    verifier("tout accordé : ok, avec le nombre de messages",
             r["ok"] and r["lecture"] == {"ok": True, "messages": 1234} and r["envoi"]["ok"] and r["annuaire"]["ok"], r)
    verifier("trois jetons, chacun sur son champ et la bonne identité",
             [(s[0], sujet) for s, sujet in JETONS] == [
                 (gmail.SCOPES[0], "admin@exemple-sols.fr"), (gmail.SCOPES_ENVOI[0], "admin@exemple-sols.fr"),
                 (gmail.SCOPES_ANNUAIRE[0], "admin@exemple-sols.fr")], JETONS)
    REFUS[(gmail.SCOPES_ENVOI[0], "admin@exemple-sols.fr")] = (
        "('unauthorized_client: Client is unauthorized to retrieve access tokens using this method', {})")
    r = gmail.tester_compte_de_service("admin@exemple-sols.fr")
    verifier("envoi non délégué : échec, et la raison dit d'ajouter le champ à la délégation",
             not r["ok"] and r["lecture"]["ok"] and not r["envoi"]["ok"] and "délégation" in r["envoi"]["raison"], r["envoi"])
    REFUS.clear()
    REFUS[(gmail.SCOPES_ANNUAIRE[0], "admin@exemple-sols.fr")] = "Gmail API has not been used in project 42 before or it is disabled"
    r = gmail.tester_compte_de_service("admin@exemple-sols.fr")
    verifier("un annuaire en échec ne fait pas tomber le test, il se dit à part",
             r["ok"] and not r["annuaire"]["ok"] and "activée" in r["annuaire"]["raison"], r)
    REFUS.clear()
    REFUS[(gmail.SCOPES[0], "personne@exemple-sols.fr")] = "invalid_grant: Invalid email or User ID"
    r = gmail.tester_compte_de_service("personne@exemple-sols.fr")
    verifier("une boîte inconnue est dite inconnue", not r["lecture"]["ok"] and "pas une boîte" in r["lecture"]["raison"], r["lecture"])
    REFUS.clear()
    verifier("sans boîte, le test le dit au lieu d'appeler Google",
             "aucune boîte" in gmail.tester_compte_de_service(None)["erreur"])
    for message, attendu in (
        ("Precondition check failed.", "licence"),
        ("Not Authorized to access this resource/api", "administrateur"),
    ):
        verifier(f"traduit : « {message[:30]}… »", attendu in gmail._raison_google(RuntimeError(message)))

    # ── 9. La boîte du test ──
    print("— la boîte sur laquelle on teste")
    verifier("l'administrateur d'abord", asyncio.run(gmail.boite_pour_le_test("noa@gmail.com")) == "admin@exemple-sols.fr")
    cles._CACHE.pop("google_admin_subject")
    verifier("sinon la personne qui clique, si elle est du domaine",
             asyncio.run(gmail.boite_pour_le_test("Eric@exemple-sols.fr")) == "eric@exemple-sols.fr")
    LIGNES_USERS[:] = ["nathalie@exemple-sols.fr"]
    verifier("un super-administrateur hors domaine : le premier compte du domaine",
             asyncio.run(gmail.boite_pour_le_test("noa@gmail.com")) == "nathalie@exemple-sols.fr")

    # ── 10. La messagerie est reconnue dès que la clé est dans Paramètres ──
    print("— la messagerie effective")
    imap = types.ModuleType("mail.imap")
    imap.configure = lambda: False
    sys.modules["mail.imap"] = imap
    sys.path.insert(0, str(BACKEND))
    # `find_spec` lit le `__spec__` d'un module déjà chargé : la doublure n'en a
    # pas. On la retire, et la recherche retrouve le vrai fichier sans l'exécuter.
    del sys.modules["ingestion.connectors.gmail"]
    collecte = charger(BACKEND / "mail" / "collecte.py", "mail.collecte")
    verifier("clé dans Paramètres seulement : la messagerie est « gmail »", collecte.fournisseur() == "gmail")
    imap.configure = lambda: True
    verifier("la boîte unique garde la priorité qu'on lui a donnée le 08/09", collecte.fournisseur() == "imap")

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
