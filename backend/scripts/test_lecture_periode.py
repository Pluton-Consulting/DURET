"""
Banc de la période des mails — les fonctions pures de `mail/lecture.py`.

Pas de réseau, pas de fournisseur : on charge le module avec une configuration
doublée et on exerce `depuis_quand` (ce que l'utilisateur dit → un instant) et
la construction du filtre. Le reste (l'appel Graph / Gmail) ne se teste qu'en
production, et c'est dit.
"""
import sys, types, datetime as dt

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
sys.path.insert(0, BACKEND)

faux = types.ModuleType("config")
class _R:
    ms_domain = "exemple.fr"
    gmail_domain = None
faux.settings = _R()
sys.modules["config"] = faux
m = types.ModuleType("mail.collecte"); m.fournisseur = lambda: "outlook"
paquet = types.ModuleType("mail"); paquet.collecte = m
sys.modules["mail"] = paquet; sys.modules["mail.collecte"] = m

import importlib.util, pathlib  # noqa: E402
spec = importlib.util.spec_from_file_location("mail.lecture", pathlib.Path(BACKEND) / "mail" / "lecture.py")
lecture = importlib.util.module_from_spec(spec); spec.loader.exec_module(lecture)

echecs = []
def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond: echecs.append(nom)

print(f"\n═══ PÉRIODE DES MAILS — {BACKEND}\n")
maintenant = dt.datetime.now(dt.timezone.utc)

print("1. Ce que l'utilisateur dit → un instant de départ")
for valeur, jours in [("7j", 7), ("7 jours", 7), ("semaine", 7), ("cette semaine", 7),
                      ("mois", 30), ("30", 30), (7, 7), ("15 jours", 15), ("hier", 1),
                      ("aujourd'hui", 0)]:
    d = lecture.depuis_quand(valeur)
    attendu = (maintenant - dt.timedelta(days=jours)).date()
    verifier(f"« {valeur} » → il y a {jours} j, à minuit", d is not None and d.date() == attendu
             and d.hour == 0 and d.minute == 0, d)
d = lecture.depuis_quand("2026-08-15")
verifier("une date ISO est prise telle quelle", d is not None and d.date() == dt.date(2026, 8, 15), d)
verifier("la date ISO est rendue en UTC si elle n'a pas de fuseau", d is not None and d.tzinfo is not None)
verifier("rien demandé → None (on lit simplement les plus récents)", lecture.depuis_quand(None) is None)
verifier("vide → None", lecture.depuis_quand("") is None)
verifier("illisible → None, jamais une exception", lecture.depuis_quand("la semaine dernière svp") is None)
verifier("une période absurde est bornée (10 000 jours → 3650)",
         lecture.depuis_quand("10000").date() == (maintenant - dt.timedelta(days=3650)).date())

print("\n2. Le filtre Graph est correctement formé")
# On intercepte l'appel HTTP pour lire l'URL construite.
classe_urls = {}
class _Reponse:
    def raise_for_status(self): pass
    def json(self): return {"value": [], "@odata.count": 84}
class _Client:
    def __init__(self, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, headers=None, params=None):
        # Depuis le 31/08 les paramètres OData passent par `params=` (httpx les
        # encode) : la doublure les recolle à l'URL pour que les contrôles
        # ci-dessous restent lisibles tels quels.
        if params:
            url = url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        classe_urls["url"] = url; classe_urls["headers"] = headers or {}
        return _Reponse()
faux_httpx = types.ModuleType("httpx"); faux_httpx.AsyncClient = _Client
sys.modules["httpx"] = faux_httpx
fo = types.ModuleType("ingestion.connectors.outlook")
async def _jeton(): return "jeton-doublure"
fo._jeton = _jeton
pi = types.ModuleType("ingestion"); pc = types.ModuleType("ingestion.connectors")
sys.modules["ingestion"] = pi; sys.modules["ingestion.connectors"] = pc; sys.modules["ingestion.connectors.outlook"] = fo

import asyncio
msgs, total = asyncio.run(lecture._lire_outlook("x@exemple.fr", "inbox", 25, lecture.depuis_quand("7j")))
url = classe_urls["url"]
verifier("$count=true est demandé (le total, indépendant de $top)", "$count=true" in url)
verifier("ConsistencyLevel: eventual accompagne $count",
         classe_urls["headers"].get("ConsistencyLevel") == "eventual")
verifier("le filtre receivedDateTime ge <ISO Z> est présent",
         "$filter=receivedDateTime ge " in url and url.rstrip().endswith("Z"), url)
verifier("$top reste borné à 25", "$top=25" in url)
verifier("le total remonte depuis @odata.count", total == 84, total)
asyncio.run(lecture._lire_outlook("x@exemple.fr", "inbox", 10, None))
verifier("sans période : aucun $filter, mais toujours le $count", "$filter" not in classe_urls["url"] and "$count=true" in classe_urls["url"])

print("\n3. lire_boite : ce que le modèle doit dire du compte")
async def _faux_outlook(boite, dossier, limite, depuis, **_k):
    return [{"objet": "x", "de": "a@b.fr", "expediteur_interne": False, "expediteur_automatique": False,
             "a": "", "date": "", "lu": True, "apercu": ""}] * 25, 84
lecture._lire_outlook = _faux_outlook
r = asyncio.run(lecture.lire_boite("x@exemple.fr", "recus", 25, depuis="7j"))
verifier("total_periode = 84, nombre détaillé = 25", r["total_periode"] == 84 and r["nombre"] == 25)
verifier("tronque = True quand le total dépasse le détail", r["tronque"] is True)
verifier("le compte est écrit en clair, avec le total ET le détail",
         "84" in r["compte"] and "25" in r["compte"], r["compte"])
verifier("la portée cite le compte", r["compte"] in r["portee"])
async def _faux_outlook_petit(boite, dossier, limite, depuis, **_k):
    return [{"objet": "x", "de": "a@b.fr", "expediteur_interne": False, "expediteur_automatique": False,
             "a": "", "date": "", "lu": True, "apercu": ""}] * 3, 3
lecture._lire_outlook = _faux_outlook_petit
r = asyncio.run(lecture.lire_boite("x@exemple.fr", "recus", 25, depuis="7j"))
verifier("quand tout tient : « tous détaillés », pas de troncature", r["tronque"] is False and "tous" in r["compte"], r["compte"])

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
print("    (l'appel réel à Graph / Gmail n'est pas couvert ici : il se vérifie en production)")
sys.exit(1 if echecs else 0)
