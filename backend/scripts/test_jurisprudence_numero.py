"""
Banc « UN NUMÉRO RG N'EST PAS UNIQUE » (24/09, Duret) — `skills/droit.py::jurisprudence`.

Fil de Damien, 09:07 → 09:08 : le tableau montrait « CA, 29/07/2026, n° 24/02543 »
(sols souples, id 6a6ae81a…) ; « ouvre la décision 24/02543 » a fait ouvrir
678f3830… — une ordonnance d'incompétence d'une AUTRE cour (10/01/2025), même RG.
Judilibre rend 65 décisions pour « 24/02543 », dont trois qui PORTENT ce RG.

CE QUE CE BANC PROUVE, sans réseau (client PISTE et clés doublés, vrai module
exécuté) : un numéro se résout d'abord parmi les décisions montrées à CETTE
personne, sans repasser par Judilibre ; `id: "24/02543"` est lu comme un numéro
(plus de 404) ; sans mémoire, seules les décisions qui portent le numéro sont
retenues, et plusieurs candidates sont RENDUES (tableau, consigne « demande
laquelle »), jamais une prise au hasard ; la mémoire est par personne.
"""
import asyncio
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


print(f"\n═══ UN NUMÉRO RG N'EST PAS UNIQUE — {BACKEND.parent}\n")

CLES = {"piste_client_id": "identifiant-application-piste", "piste_client_secret": "s3cr3t",
        "piste_environnement": ""}
faux_cles = types.ModuleType("llm.cles")
faux_cles.valeur = lambda nom: CLES.get(nom)
faux_llm = types.ModuleType("llm")
faux_llm.cles = faux_cles
sys.modules["llm"] = faux_llm
sys.modules["llm.cles"] = faux_cles

from outils import piste  # noqa: E402
from skills import droit  # noqa: E402
from skills.erreurs import SkillError  # noqa: E402


class Reponse:
    def __init__(self, statut, corps):
        self.status_code, self._corps = statut, corps

    def json(self):
        return self._corps


APPELS, ROUTES = [], {}


class Client:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *x):
        return False

    async def post(self, url, data=None, json=None, headers=None):
        APPELS.append(("POST", url, data if data is not None else json))
        return self._repondre(url, data if data is not None else json)

    async def get(self, url, params=None, headers=None):
        APPELS.append(("GET", url, params))
        return self._repondre(url, params)

    def _repondre(self, url, charge):
        for suffixe, fn in ROUTES.items():
            if url.endswith(suffixe):
                return fn(charge)
        return Reponse(404, {})


piste.fabrique_client = lambda: Client()


def remettre():
    APPELS.clear()
    ROUTES.clear()
    piste.oublier_jetons()
    ROUTES["/api/oauth/token"] = lambda c: Reponse(200, {"access_token": "j", "expires_in": 3600, "token_type": "Bearer"})


def lancer(coro):
    return asyncio.run(coro)


def echec(coro):
    try:
        lancer(coro)
    except SkillError as e:
        return str(e)
    return None


def appels(fragment):
    return [a for a in APPELS if fragment in a[1]]


def decision(ident, numero, date, chambre, resume):
    return {"id": ident, "jurisdiction": "Cour d'appel", "chamber": chambre, "number": numero,
            "numbers": [numero], "decision_date": date, "solution": "", "summary": resume,
            "text": "MOTIFS. " + resume + " PAR CES MOTIFS.", "zones": {}}


# Les trois décisions réelles qui portent le RG 24/02543 (dates et chambres de Judilibre),
# plus une qui ne fait que CITER ce numéro (la recherche plein texte la rend aussi).
RPSO = decision("6a6ae81ad6da0419626f57df", "24/02543", "2026-07-29", "2ème CH - Section 1",
                "REVETEMENT PEINTURE SUD OUEST (RPSO) : travaux de revêtement de sols souples.")
AUTRE_COUR = decision("6a1a77bfcdc6046d47751b45", "24/02543", "2026-05-28", "Chambre 4 SB", "Bail commercial.")
ORDONNANCE = decision("678f383006f4e91c5f36c47a", "24/02543", "2025-01-10", "4ème chambre commerciale",
                      "Ordonnance du conseiller de la mise en état : incompétence.")
CITANTE = decision("688311324d9076bf079c2331", "25/02543", "2025-07-24", "6ème Chambre",
                   "Vu le dossier RG 24/02543 joint.")
TOUTES = {d["id"]: d for d in (RPSO, AUTRE_COUR, ORDONNANCE, CITANTE)}

Damien = types.SimpleNamespace(id="fcd2d7a3", email="damien@exemple-sols.fr")
Nathalie = types.SimpleNamespace(id="d0879ac6", email="nathalie@exemple-sols.fr")

print("── 1. Le numéro se résout parmi les décisions montrées à la personne")
remettre()
ROUTES["/cassation/judilibre/v1.0/search"] = lambda p: Reponse(200, {"total": 1009, "results": [RPSO, CITANTE]})
ROUTES["/cassation/judilibre/v1.0/decision"] = lambda p: Reponse(200, TOUTES[p["id"]]) if p.get("id") in TOUTES else Reponse(404, {})
r = lancer(droit.jurisprudence({"recherche": "revêtement de sols marché public", "tri": "date",
                                "juridiction": "toutes"}, Damien))
verifier("la recherche montre la décision RPSO (RG 24/02543)", [l["numero"] for l in r["resultats"]] == ["24/02543", "25/02543"])
verifier("la consigne dit d'ouvrir par l'id de la ligne, jamais par une recherche sur le numéro",
         "`id` de SA ligne" in r["a_faire"] and "plusieurs cours" in r["a_faire"])
APPELS.clear()
r2 = lancer(droit.jurisprudence({"numero": "24/02543"}, Damien))
verifier("« ouvre la décision 24/02543 » → LA décision montrée, celle des sols souples",
         r2.get("id") == RPSO["id"] and r2.get("date") == "2026-07-29", r2.get("id"))
verifier("sans repasser par la recherche Judilibre (l'identifiant vient de la mémoire)",
         not appels("/search") and len(appels("/decision")) == 1)
APPELS.clear()
r3 = lancer(droit.jurisprudence({"id": "24/02543"}, Damien))
verifier("`id: \"24/02543\"` est lu comme un numéro (avant : 404 sec, puis recherche au hasard)",
         r3.get("id") == RPSO["id"] and not appels("/search"))
verifier("le résultat d'une lecture dit de signaler une décision qui n'est pas celle annoncée",
         "n'est PAS celle" in r3.get("a_faire", ""))

print("── 2. La mémoire est par personne")
APPELS.clear()
ROUTES["/cassation/judilibre/v1.0/search"] = lambda p: Reponse(200, {"total": 65, "results": [CITANTE, RPSO, AUTRE_COUR, ORDONNANCE]})
r4 = lancer(droit.jurisprudence({"numero": "24/02543"}, Nathalie))
verifier("Nathalie n'a rien vu : Judilibre est interrogé sur le numéro", len(appels("/search")) == 1
         and appels("/search")[0][2].get("query") == "24/02543")
verifier("seules les décisions qui PORTENT le numéro sont candidates (celle qui le cite est écartée)",
         [c["id"] for c in r4.get("candidats", [])] == [RPSO["id"], AUTRE_COUR["id"], ORDONNANCE["id"]],
         [c["id"] for c in r4.get("candidats", [])])
verifier("trois candidates → aucune n'est ouverte, elles sont rendues en tableau garanti",
         "texte" not in r4 and r4.get("bloc_garanti") and len(r4["bloc_ui"]["rows"]) == 3)
verifier("la consigne : ne devine pas, demande laquelle (boutons)",
         "NE devine pas" in r4["a_faire"] and "quick_replies" in r4["a_faire"])
verifier("le message dit pourquoi (un RG n'est unique que dans sa juridiction)",
         "n'est unique que dans sa juridiction" in r4["message_final"])

print("── 3. Un seul porteur, ou aucun")
APPELS.clear()
ROUTES["/cassation/judilibre/v1.0/search"] = lambda p: Reponse(200, {"total": 2, "results": [CITANTE, ORDONNANCE]})
r5 = lancer(droit.jurisprudence({"rg": "24/02543"}, Nathalie))
verifier("un seul porteur → ouvert directement", r5.get("id") == ORDONNANCE["id"] and "texte" in r5)
ROUTES["/cassation/judilibre/v1.0/search"] = lambda p: Reponse(200, {"total": 1, "results": [CITANTE]})
m = echec(droit.jurisprudence({"numero": "24/02543"}, Nathalie))
verifier("aucun porteur → échec dit, qui renvoie à l'id de la ligne", m and "Aucune décision ne porte" in m, m)
m2 = echec(droit.jurisprudence({}, Nathalie))
verifier("sans rien : le message nomme `numero`", m2 and "numero" in m2, m2)

print("── 4. Formes de numéro et catalogue")
verifier("RG et pourvoi reconnus, un identifiant Judilibre non",
         droit.est_un_numero("24/02543") and droit.est_un_numero("19-24.001")
         and not droit.est_un_numero("678f383006f4e91c5f36c47a") and not droit.est_un_numero("décennale"))
decl = droit.SKILLS["jurisprudence"]
verifier("`numero` déclaré et expliqué au modèle",
         "numero" in decl.optionnels and "plusieurs cours" in decl.description)
verifier("la mémoire est bornée", droit.MAX_DECISIONS_VUES == 300)

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
