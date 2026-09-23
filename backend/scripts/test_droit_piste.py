"""
Banc « LE DROIT OFFICIEL PAR PISTE » (23/09) — `outils/piste.py` et `skills/droit.py`.

Les gestes `texte_de_loi` (Légifrance) et `jurisprudence` (Judilibre) appellent
des API de l'État derrière une authentification OAuth2. Aucun identifiant réel
n'existe ici : le banc DOUBLE le client HTTP (`piste.fabrique_client`) et la
couche des clés (`llm.cles`), puis EXÉCUTE les vrais modules.

CE QUE CE BANC PROUVE, sans réseau :
  * le jeton est demandé UNE fois, puis réutilisé tant qu'il est valable ;
  * sans identifiant, le message renvoie à Paramètres → Clés API et AUCUN appel
    ne part ;
  * un 401 (identifiants refusés) et un 403 (API non souscrite) se disent en
    français, et un 401 sur l'API retente une fois avec un jeton neuf ;
  * un article de code rendu avec son numéro, sa date de version, son lien
    Légifrance, en texte propre, coupé proprement avec `pour_continuer` ;
  * une recherche Judilibre rendue compacte (tableau garanti, liens) et la
    lecture d'une décision qui commence aux motifs ;
  * le secret n'apparaît dans AUCUNE sortie (résultats, erreurs, journaux).

Usage : python3.12 backend/scripts/test_droit_piste.py backend
"""
import asyncio
import io
import json
import logging
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LE DROIT OFFICIEL PAR PISTE — {BACKEND.parent}\n")

SECRET = "s3cr3t-piste-NE-DOIT-JAMAIS-SORTIR"
CLIENT_ID = "identifiant-application-piste"

# ── Doublure de la couche des clés (Paramètres > .env) ───────────────
CLES = {"piste_client_id": CLIENT_ID, "piste_client_secret": SECRET,
        "piste_environnement": ""}
faux_cles = types.ModuleType("llm.cles")
faux_cles.valeur = lambda nom: CLES.get(nom)
faux_llm = types.ModuleType("llm")
faux_llm.cles = faux_cles
sys.modules["llm"] = faux_llm
sys.modules["llm.cles"] = faux_cles

# Journaux capturés : le secret ne doit pas y passer non plus.
journal = io.StringIO()
gestionnaire = logging.StreamHandler(journal)
logging.getLogger().addHandler(gestionnaire)
logging.getLogger().setLevel(logging.DEBUG)

from outils import piste  # noqa: E402
from skills import droit  # noqa: E402
from skills.erreurs import SkillError  # noqa: E402


# ── Doublure du client HTTP ──────────────────────────────────────────
class Reponse:
    def __init__(self, statut, corps):
        self.status_code = statut
        self._corps = corps

    def json(self):
        if isinstance(self._corps, Exception):
            raise self._corps
        return self._corps


APPELS = []          # (méthode, url, données) de chaque requête
ROUTES = {}          # suffixe d'URL -> fonction(corps/params) -> Reponse


class Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *x):
        return False

    async def post(self, url, data=None, json=None, headers=None):
        APPELS.append(("POST", url, data if data is not None else json, headers or {}))
        return self._repondre(url, data if data is not None else json)

    async def get(self, url, params=None, headers=None):
        APPELS.append(("GET", url, params, headers or {}))
        return self._repondre(url, params)

    def _repondre(self, url, charge):
        for suffixe, fn in ROUTES.items():
            if url.endswith(suffixe):
                return fn(charge)
        return Reponse(404, {})


piste.fabrique_client = lambda: Client()


def jeton_ok(charge):
    return Reponse(200, {"access_token": "jeton-A", "expires_in": 3600, "token_type": "Bearer"})


def remettre():
    APPELS.clear()
    ROUTES.clear()
    piste.oublier_jetons()
    ROUTES["/api/oauth/token"] = jeton_ok


def lancer(coro):
    return asyncio.run(coro)


def echec(coro):
    try:
        lancer(coro)
    except SkillError as e:
        return str(e)
    except piste.PisteErreur as e:
        return str(e)
    return None


def appels_vers(fragment):
    return [a for a in APPELS if fragment in a[1]]


SORTIES = []         # tout ce qui sort (résultats et erreurs), pour la chasse au secret

# ── 1. Jeton demandé une fois puis réutilisé ─────────────────────────
print("── Jeton OAuth")
remettre()
ARTICLE_1792 = {"article": {
    "id": "LEGIARTI000006438834", "num": "1792", "etat": "VIGUEUR",
    "dateDebut": 1041379200000, "dateFin": 32472144000000, "cid": "LEGIARTI000006438834",
    "texteHtml": "<p>Tout constructeur d'un ouvrage est responsable de plein droit, envers "
                 "le ma&icirc;tre ou l'acqu&eacute;reur de l'ouvrage, des dommages.</p><p>Une "
                 "telle responsabilit&eacute; n'a point lieu si le constructeur prouve que les "
                 "dommages proviennent d'une cause &eacute;trang&egrave;re.</p>",
    "textTitles": [{"titre": "Code civil", "nature": "CODE", "cid": "LEGITEXT000006070721"}],
    "sectionParentTitre": "Chapitre III : Du louage d'ouvrage et d'industrie"}}
ROUTES["/consult/getArticleWithIdAndNum"] = lambda c: (
    Reponse(200, ARTICLE_1792) if c.get("num") == "1792" else Reponse(404, {}))
r1 = lancer(droit.texte_de_loi({"code": "code civil", "article": "1792"}, None))
r2 = lancer(droit.texte_de_loi({"code": "civil", "article": "art. 1792"}, None))
SORTIES += [r1, r2]
jetons = appels_vers("/api/oauth/token")
verifier("un seul jeton pour deux questions", len(jetons) == 1, f"{len(jetons)} demandes")
verifier("le jeton est demandé en client_credentials, scope openid",
         jetons and jetons[0][2].get("grant_type") == "client_credentials"
         and jetons[0][2].get("scope") == "openid")
verifier("production par défaut (oauth.piste.gouv.fr)",
         jetons and jetons[0][1] == "https://oauth.piste.gouv.fr/api/oauth/token")
api = appels_vers("/consult/getArticleWithIdAndNum")
verifier("l'API reçoit le jeton en Bearer",
         api and api[0][3].get("Authorization") == "Bearer jeton-A")
verifier("appel sur la base Légifrance officielle",
         api and api[0][1] == "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/getArticleWithIdAndNum")
verifier("le code civil est résolu vers son LEGITEXT",
         api and api[0][2] == {"id": "LEGITEXT000006070721", "num": "1792"})

# ── 2. Un article rendu avec lien et date ────────────────────────────
print("── Article de code")
verifier("numéro d'article", r1.get("article") == "Article 1792", r1.get("article"))
verifier("texte source nommé", r1.get("texte_source") == "Code civil")
verifier("état en vigueur", r1.get("etat") == "en vigueur", r1.get("etat"))
verifier("date de version lisible (millisecondes → ISO)",
         r1.get("version_en_vigueur_depuis") == "2003-01-01", r1.get("version_en_vigueur_depuis"))
verifier("fin de version 2999 tue (pas de fausse échéance)", "version_valable_jusqu_au" not in r1)
verifier("lien Légifrance d'article de code",
         r1.get("lien") == "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006438834",
         r1.get("lien"))
verifier("texte débarrassé du HTML et des entités",
         "<p>" not in r1["texte"] and "maître" in r1["texte"] and "étrangère" in r1["texte"])
verifier("consigne : citer, dater, pas un conseil juridique",
         all(m in r1.get("a_faire", "") for m in ("CITANT", "lien", "conseil juridique")))
verifier("court : pas de suite", "pour_continuer" not in r1)

# Un article du Code du travail écrit sans préfixe : les variantes L/R/D.
remettre()
vus = []
ROUTES["/consult/getArticleWithIdAndNum"] = lambda c: (
    vus.append(c["num"]) or (Reponse(200, {"article": {
        "id": "LEGIARTI000035644154", "num": "L1234-9", "etat": "VIGUEUR",
        "dateDebut": "2017-09-24", "texte": "Le salarié titulaire d'un CDI licencié…"}})
        if c["num"] == "L1234-9" else Reponse(404, {})))
r3 = lancer(droit.texte_de_loi({"code": "Code du travail", "article": "1234-9"}, None))
SORTIES.append(r3)
verifier("numéro nu : essais « 1234-9 » puis « L1234-9 »", vus == ["1234-9", "L1234-9"], vus)
verifier("date ISO gardée", r3.get("version_en_vigueur_depuis") == "2017-09-24")

# Un long article : coupé à une fin de phrase, avec la suite.
remettre()
long_texte = " ".join(f"Phrase numéro {i} du long article sur la réception des travaux." for i in range(120))
ROUTES["/consult/getArticle"] = lambda c: Reponse(200, {"article": {
    "id": c["id"], "num": "L111-1", "etat": "VIGUEUR", "dateDebut": "2022-07-01",
    "texte": long_texte,
    "textTitles": [{"titre": "Code de la construction et de l'habitation", "nature": "CODE"}]}})
r4 = lancer(droit.texte_de_loi({"id": "LEGIARTI000045000001"}, None))
SORTIES.append(r4)
verifier("long article coupé sous le plafond", len(r4["texte"]) <= droit.TAILLE_MORCEAU)
verifier("coupé à une fin de phrase", r4["texte"].endswith("."), r4["texte"][-30:])
verifier("pour_continuer dit l'id et la position",
         "a_partir_de" in r4.get("pour_continuer", "") and "LEGIARTI000045000001" in r4["pour_continuer"])
suite = int(r4["pour_continuer"].split("a_partir_de: ")[1].split("`")[0])
r5 = lancer(droit.texte_de_loi({"id": "LEGIARTI000045000001", "a_partir_de": suite}, None))
verifier("la suite reprend là où le morceau s'arrêtait",
         long_texte[suite:].lstrip().startswith(r5["texte"][:40]))
verifier("résultat compact (< 4 000 caractères)",
         len(json.dumps(r4, ensure_ascii=False)) < 4000, len(json.dumps(r4, ensure_ascii=False)))

# ── 3. Clé absente : message clair, aucun appel ──────────────────────
print("── Identifiants absents")
remettre()
CLES["piste_client_secret"] = ""
m = echec(droit.texte_de_loi({"code": "civil", "article": "1792"}, None))
SORTIES.append(m or "")
verifier("un refus est rendu", bool(m))
verifier("le refus renvoie à Paramètres → Clés API", m and "Paramètres → Clés API" in m, m)
verifier("aucun appel réseau sans identifiants", not APPELS, APPELS)
m2 = echec(droit.jurisprudence({"recherche": "réception tacite"}, None))
verifier("idem pour la jurisprudence", m2 and "Paramètres → Clés API" in m2 and not APPELS)
CLES["piste_client_secret"] = SECRET

# ── 4. 401 / 403 / 429 : messages clairs ────────────────────────────
print("── Refus")
remettre()
ROUTES["/api/oauth/token"] = lambda c: Reponse(401, {"error": "invalid_client",
                                                     "error_description": f"bad {SECRET}"})
m = echec(droit.texte_de_loi({"code": "civil", "article": "1792"}, None))
SORTIES.append(m or "")
verifier("401 à l'authentification : identifiants refusés, où les corriger",
         m and "refusé" in m and "Paramètres → Clés API" in m, m)

remettre()
ROUTES["/consult/getArticleWithIdAndNum"] = lambda c: Reponse(401, {})
m = echec(droit.texte_de_loi({"code": "civil", "article": "1792"}, None))
SORTIES.append(m or "")
verifier("401 sur l'API : message clair", m and "401" in m and "refusé" in m, m)
verifier("401 sur l'API : UN nouvel essai avec un jeton neuf",
         len(appels_vers("/api/oauth/token")) == 2
         and len(appels_vers("/consult/getArticleWithIdAndNum")) == 2,
         [a[1] for a in APPELS])

remettre()
ROUTES["/search"] = lambda c: Reponse(403, {})
m = echec(droit.jurisprudence({"recherche": "désordres décennale"}, None))
SORTIES.append(m or "")
verifier("403 : l'API n'est pas souscrite dans PISTE", m and "souscrit" in m, m)

remettre()
ROUTES["/search"] = lambda c: Reponse(429, {})
m = echec(droit.texte_de_loi({"recherche": "pénalités de retard"}, None))
verifier("429 : quota dit tel quel", m and "Quota" in m, m)

# ── 5. Recherche Légifrance ──────────────────────────────────────────
print("── Recherche Légifrance")
remettre()
RECHERCHE = {"totalResultNumber": 12, "results": [
    {"titles": [{"title": "Code de procédure civile", "id": "LEGITEXT000006070716"}],
     "sections": [{"extracts": [{"id": "LEGIARTI000006410000", "num": "12",
                                 "legalStatus": "VIGUEUR", "values": ["le <mark>juge</mark>"]}]}]},
    {"titles": [{"title": "Code civil", "id": "LEGITEXT000006070721"}],
     "sections": [{"title": "Du louage d'ouvrage", "extracts": [
         {"id": "LEGIARTI000006438836", "num": "1792-6", "legalStatus": "VIGUEUR",
          "dateDebut": 1041379200000,
          "values": ["La <mark>réception</mark> est l'acte par lequel le maître de l'ouvrage…"]}]}]},
]}
corps_vus = []
ROUTES["/search"] = lambda c: corps_vus.append(c) or Reponse(200, RECHERCHE)
r6 = lancer(droit.texte_de_loi({"recherche": "réception des travaux", "code": "civil"}, None))
SORTIES.append(r6)
verifier("fond des codes en vigueur", corps_vus and corps_vus[0]["fond"] == "CODE_ETAT")
verifier("les mots cherchés sont transmis",
         corps_vus and corps_vus[0]["recherche"]["champs"][0]["criteres"][0]["valeur"]
         == "réception des travaux")
verifier("filtre sur le code demandé (pas « procédure civile »)",
         [l["id"] for l in r6["resultats"]] == ["LEGIARTI000006438836"],
         [l["id"] for l in r6["resultats"]])
verifier("tableau garanti avec le lien",
         r6.get("bloc_garanti") and r6["bloc_ui"]["type"] == "table"
         and "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000006438836"
         in json.dumps(r6["bloc_ui"]))
verifier("extrait sans balises", "<mark>" not in json.dumps(r6, ensure_ascii=False))
verifier("consigne : ouvrir l'article avant de répondre", "OUVRE" in r6.get("a_faire", ""))

# Une facette refusée (500) : second essai sans le filtre d'état.
remettre()
essais = []
ROUTES["/search"] = lambda c: (essais.append(c) or
                               (Reponse(500, {}) if c["recherche"].get("filtres") else Reponse(200, RECHERCHE)))
r7 = lancer(droit.texte_de_loi({"recherche": "garantie décennale", "source": "codes"}, None))
verifier("facette refusée : second essai sans filtre, et une réponse",
         len(essais) == 2 and r7["resultats"], len(essais))

# Convention collective du bâtiment.
remettre()
kali = []
ROUTES["/search"] = lambda c: kali.append(c) or Reponse(200, {"totalResultNumber": 0, "results": []})
r8 = lancer(droit.texte_de_loi({"recherche": "indemnité de trajet", "idcc": "1597"}, None))
verifier("idcc → fonds KALI filtré par IDCC",
         kali and kali[0]["fond"] == "KALI"
         and {"facette": "IDCC", "valeurs": ["1597"]} in kali[0]["recherche"].get("filtres", []))
verifier("aucun résultat : on le dit, sans inventer", "Ne réponds pas de mémoire" in r8.get("a_faire", ""))

# ── 6. Judilibre ─────────────────────────────────────────────────────
print("── Jurisprudence")
remettre()
params_vus = []
DECISIONS = {"page": 0, "page_size": 5, "total": 37, "results": [
    {"id": "60794cf99ba5988459c4a1b2", "jurisdiction": "Cour de cassation",
     "chamber": "Troisième chambre civile", "number": "19-24.001",
     "decision_date": "2021-03-18", "solution": "Cassation",
     "summary": "La réception tacite d'un ouvrage suppose la volonté non équivoque " * 8,
     "highlights": {"motivations": ["<em>réception</em> tacite"]}},
    {"id": "5fca7e8a8f3b8a9a1c2d3e4f", "jurisdiction": "Cour de cassation",
     "chamber": "Troisième chambre civile", "number": "18-10.101",
     "decision_date": "2019-11-14", "solution": "Rejet", "summary": "",
     "highlights": {"motivations": ["la <em>prise de possession</em> et le paiement"]}},
]}
ROUTES["/cassation/judilibre/v1.0/search"] = lambda p: params_vus.append(p) or Reponse(200, DECISIONS)
r9 = lancer(droit.jurisprudence({"recherche": "réception tacite", "chambre": "3e chambre civile",
                                 "depuis": "2018", "tri": "date"}, None))
SORTIES.append(r9)
p = params_vus[0] if params_vus else {}
verifier("GET /search sur la base Judilibre",
         appels_vers("/cassation/judilibre/v1.0/search")
         and appels_vers("/cassation/judilibre/v1.0/search")[0][0] == "GET")
verifier("Cour de cassation par défaut", p.get("jurisdiction") == ["cc"], p.get("jurisdiction"))
verifier("chambre en mots → clé civ3", p.get("chamber") == ["civ3"], p.get("chamber"))
verifier("année → date de début ISO", p.get("date_start") == "2018-01-01", p.get("date_start"))
verifier("tri par date décroissante", p.get("sort") == "date" and p.get("order") == "desc")
verifier("pages comptées depuis 0 côté API", p.get("page") == 0)
verifier("deux décisions, liens courdecassation.fr",
         [l["lien"] for l in r9["resultats"]] == [
             "https://www.courdecassation.fr/decision/60794cf99ba5988459c4a1b2",
             "https://www.courdecassation.fr/decision/5fca7e8a8f3b8a9a1c2d3e4f"])
verifier("sommaire borné", all(len(l["sommaire"]) <= 261 for l in r9["resultats"]))
verifier("sans sommaire : l'extrait surligné, sans balises",
         r9["resultats"][1]["sommaire"] == "la prise de possession et le paiement",
         r9["resultats"][1]["sommaire"])
verifier("tableau garanti", r9.get("bloc_garanti") and len(r9["bloc_ui"]["rows"]) == 2)
verifier("page suivante proposée (37 au total)", "page: 2" in r9.get("pour_continuer", ""))
verifier("résultat compact (< 4 000 caractères)",
         len(json.dumps(r9, ensure_ascii=False)) < 4000, len(json.dumps(r9, ensure_ascii=False)))

# Lecture d'une décision : commence aux motifs.
remettre()
entete = "COUR DE CASSATION. Audience publique. Parties et avocats. " * 10
motifs = "Réponse de la Cour. Vu l'article 1792-6 du code civil. La réception tacite… " * 5
dispositif = "PAR CES MOTIFS, la Cour : CASSE et ANNULE l'arrêt."
texte = entete + motifs + dispositif
DECISION = {"id": "60794cf99ba5988459c4a1b2", "jurisdiction": "Cour de cassation",
            "chamber": "Troisième chambre civile", "number": "19-24.001",
            "decision_date": "2021-03-18", "solution": "Cassation",
            "summary": "Réception tacite.", "text": texte,
            "zones": {"motivations": [{"start": len(entete), "end": len(entete) + len(motifs)}],
                      "dispositif": [{"start": len(entete) + len(motifs), "end": len(texte)}]},
            "visa": [{"title": "Article 1792-6 du code civil"}]}
ROUTES["/cassation/judilibre/v1.0/decision"] = lambda p: (
    Reponse(200, DECISION) if p.get("id") == DECISION["id"] else Reponse(404, {}))
r10 = lancer(droit.jurisprudence({"id": "60794cf99ba5988459c4a1b2"}, None))
SORTIES.append(r10)
verifier("la lecture commence aux motifs, pas à l'en-tête",
         r10["texte"].startswith("Réponse de la Cour"), r10["texte"][:40])
verifier("dispositif rendu à part", r10.get("dispositif") == dispositif)
verifier("textes appliqués repris", r10.get("textes_appliques") == ["Article 1792-6 du code civil"])
verifier("numéro, date, lien de la décision",
         r10["numero"] == "19-24.001" and r10["date"] == "2021-03-18"
         and r10["lien"].endswith("/decision/60794cf99ba5988459c4a1b2"))
m = echec(droit.jurisprudence({"id": "inconnu"}, None))
verifier("décision inconnue (404) : message clair", m and "404" in m, m)

# Bac à sable : environnement réglable.
remettre()
CLES["piste_environnement"] = "sandbox"
ROUTES["/cassation/judilibre/v1.0/search"] = lambda p: Reponse(200, DECISIONS)
lancer(droit.jurisprudence({"recherche": "réserves"}, None))
verifier("bac à sable : oauth et API de sandbox",
         appels_vers("sandbox-oauth.piste.gouv.fr") and appels_vers("sandbox-api.piste.gouv.fr"))
CLES["piste_environnement"] = ""

# ── 7. Le secret ne sort nulle part ──────────────────────────────────
print("── Secret")
tout = json.dumps(SORTIES, ensure_ascii=False, default=str)
verifier("aucun résultat ni message ne porte le secret", SECRET not in tout)
verifier("les journaux ne portent pas le secret", SECRET not in journal.getvalue())
verifier("le secret n'est envoyé qu'au serveur d'authentification",
         all(SECRET not in json.dumps(a[2] or {}, default=str) for a in APPELS
             if "oauth" not in a[1]))

# ── 8. Déclarations ──────────────────────────────────────────────────
print("── Déclarations")
for nom in ("texte_de_loi", "jurisprudence"):
    d = droit.SKILLS.get(nom)
    verifier(f"{nom} déclaré en lecture", d is not None and d.effet == "lecture")
    verifier(f"{nom} : la description exige de citer et de rappeler l'absence de conseil",
             d is not None and "conseil juridique" in d.description and "lien" in d.description)

print(f"\n{'✗ ' + str(len(echecs)) + ' ÉCHEC(S)' if echecs else '✓ TOUT PASSE'}\n")
sys.exit(1 if echecs else 0)
