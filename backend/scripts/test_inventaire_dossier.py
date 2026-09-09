"""
Banc « L'INVENTAIRE D'UN DOSSIER, FICHIER PAR FICHIER » et « L'APERÇU WEB
GARANTI » (08/09 soir).

Demandes de Noa : « lister les fichiers du Drive en les ouvrant un par un et
produire une nouvelle liste, avec le détail de la démarche dans le chat » ;
« confirme que la recherche sur Internet fonctionne, avec la
prévisualisation ».

CE QUE CE BANC PROUVE (skills EXÉCUTÉS contre un stockage, un modèle et un
atelier doublés) : chaque fichier du dossier est ouvert, un fichier illisible
n'arrête pas les autres et sa raison est dite, chaque fichier lu est décrit
en une phrase (les premiers mots si le modèle manque), l'Excel est produit
et la DÉMARCHE est un bloc de liste garanti à côté de la carte ; le nombre
total est dit quand la borne mord ; la source de chaque client expose
`fichiers_du_dossier` / `lire_fichier` ; `ouvrir_page` pose la capture en
bloc `site` garanti et `chercher_web` ses sources. Tombe sur la version d'avant.
"""
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
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    return mod


print(f"\n═══ L'INVENTAIRE D'UN DOSSIER, ET L'APERÇU WEB GARANTI — {BACKEND.parent}\n")

# ── Doublures ──
sys.modules["skills"] = types.ModuleType("skills")
err = types.ModuleType("skills.erreurs")


class SkillError(Exception):
    pass
err.SkillError = SkillError
sys.modules["skills.erreurs"] = err
reg = types.ModuleType("skills.registre")


class Declaration:
    def __init__(self, **kw):
        self.__dict__.update(kw)
reg.Declaration = Declaration
sys.modules["skills.registre"] = reg

FICHIERS = [{"nom": "Devis 2026-041.pdf", "ref": "r1", "octets": 120_000, "type": ""},
            {"nom": "Plan masse.dwg", "ref": "r2", "octets": 3_000_000, "type": ""},
            {"nom": "CCTP lot 3.docx", "ref": "r3", "octets": 45_000, "type": ""},
            {"nom": "Photo chantier.jpg", "ref": "r4", "octets": 900_000, "type": ""}]
TEXTES = {"r1": "DEVIS n° 2026-041 — Aire de jeux, Mairie de Gujan, 12 500 € HT, valable 30 jours.",
          "r3": "CCTP lot 3 plâtrerie cloisons modulaires, IKOS Bordeaux, indice A.", "r4": ""}
LECTURES = []
source = types.ModuleType("classement.source")
source.NOM_STOCKAGE = "Drive d'essai"


async def _fichiers(dossier, user):
    return "Drive/CHANTIERS/IKOS", list(FICHIERS)


async def _lire(ref, user):
    LECTURES.append(ref)
    if ref == "r2":
        raise RuntimeError("format DWG non lisible")
    return TEXTES.get(ref, "")
source.fichiers_du_dossier, source.lire_fichier = _fichiers, _lire
sys.modules["classement"] = types.ModuleType("classement")
sys.modules["classement.source"] = source

APPELS_LLM = []
lc = types.ModuleType("langchain_core.messages")
lc.HumanMessage = lambda content: ("human", content)
lc.SystemMessage = lambda content: ("system", content)
sys.modules["langchain_core"] = types.ModuleType("langchain_core")
sys.modules["langchain_core.messages"] = lc
llm_router = types.ModuleType("llm.router")


class _Modele:
    async def ainvoke(self, messages):
        APPELS_LLM.append(messages[1][1][:40])
        return types.SimpleNamespace(content=f"Document : {messages[1][1][:30]}…")
llm_router.LLMTier = types.SimpleNamespace(LIGHT="light")
llm_router.get_llm = lambda tier: _Modele()
sys.modules["llm"] = types.ModuleType("llm")
sys.modules["llm.router"] = llm_router
ATELIER = {}
at = types.ModuleType("bureautique.atelier")
at.ouvrir = lambda entete, proprio: ATELIER.setdefault("jeton", "JETON1") if not ATELIER.update({"entete": entete}) else "JETON1"
at.ajouter = lambda jeton, elements, proprio: ATELIER.update({"elements": elements})
at.terminer = lambda jeton, proprio: {"octets": 4321}
sys.modules["bureautique"] = types.ModuleType("bureautique")
sys.modules["bureautique.atelier"] = at

src = BACKEND / "skills" / "inventaire.py"
verifier("le skill `skills/inventaire.py` existe", src.exists())
if not src.exists():
    sys.exit(1)
inv = charger(src, "inventaire_double")
U = types.SimpleNamespace(id="u1", role="direction")
r = asyncio.run(inv.inventaire_dossier({"dossier": "IKOS"}, U))
verifier("chaque fichier du dossier est ouvert, une seule fois", sorted(LECTURES) == ["r1", "r2", "r3", "r4"])
verifier("un fichier illisible n'arrête pas les autres : 2 lus, 1 illisible (raison dite), 1 sans texte",
         r["lus"] == 2 and set(r["illisibles"]) == {"Plan masse.dwg", "Photo chantier.jpg"}
         and any("format DWG non lisible" in l for l in r["demarche"]))
verifier("chaque fichier lu est décrit en une phrase par le modèle léger (deux appels, pas quatre)",
         len(APPELS_LLM) == 2 and all(l["description"].startswith("Document :") for l in r["lignes"] if l["lecture"] == "lu"))
verifier("l'Excel est produit par l'atelier : une ligne par fichier, cinq colonnes",
         ATELIER["elements"][0]["entetes"] == ["Fichier", "Type", "Taille", "Lecture", "Description"]
         and len(ATELIER["elements"][0]["lignes"]) == 4 and ATELIER["elements"][0]["lignes"][0][1] == "pdf"
         and ATELIER["elements"][0]["lignes"][1][2] == "2.9 Mo")
blocs = r["bloc_ui"]
verifier("DEUX blocs garantis : la carte du classeur et la liste de la démarche",
         r["bloc_garanti"] is True and isinstance(blocs, list) and blocs[0]["type"] == "fichier"
         and blocs[0]["url"] == "/api/documents/JETON1" and blocs[1]["type"] == "list"
         and blocs[1]["titre"] == "Démarche suivie" and len(blocs[1]["items"]) >= 6)
verifier("la démarche dit ce qui a été listé, ouvert, lu, décrit, écrit",
         r["demarche"][0].startswith("Dossier « Drive/CHANTIERS/IKOS » listé sur le Drive d'essai : 4 fichier(s)")
         and any(d.startswith("Ouvert « Devis 2026-041.pdf » : lu") for d in r["demarche"])
         and any("décrit(s) en une phrase" in d for d in r["demarche"])
         and any("classeur Excel" in d for d in r["demarche"]))
verifier("la consigne interdit de recopier la liste et demande deux phrases",
         "ne recopie ni la liste" in r["a_faire"] and "deux phrases" in r["a_faire"])
LECTURES.clear(); APPELS_LLM.clear()
r2 = asyncio.run(inv.inventaire_dossier({"dossier": "IKOS", "limite": 2, "resume": "false"}, U))
verifier("`limite: 2` : deux fichiers ouverts sur quatre, le reste DIT ; `resume: false` : aucun appel de modèle",
         r2["ouverts"] == 2 and r2["nombre"] == 4 and len(LECTURES) == 2 and not APPELS_LLM
         and any("2 suivants attendent" in d for d in r2["demarche"]))
verifier("sans modèle : les premiers mots du document servent de description",
         inv.description_de_secours("DEVIS   n° 2026-041\n\nAire de jeux") == "DEVIS n° 2026-041 Aire de jeux"
         and r2["lignes"][0]["description"].startswith("DEVIS n° 2026-041"))


async def _casse(ref, user):
    raise RuntimeError("stockage injoignable")
source.lire_fichier = _casse
r3 = asyncio.run(inv.inventaire_dossier({"dossier": "IKOS"}, U))
verifier("stockage injoignable : l'inventaire se rend quand même, tout marqué illisible",
         r3["lus"] == 0 and len(r3["illisibles"]) == 4)
try:
    asyncio.run(inv.inventaire_dossier({}, U))
    verifier("sans dossier : refusé", False)
except SkillError:
    verifier("sans dossier : refusé avec ce qui manque", True)
decl = inv.SKILLS["inventaire_dossier"]
verifier("déclaré en LECTURE, `dossier` requis, libellé « je … »",
         decl.effet == "lecture" and decl.requis == ["dossier"] and decl.libelle.startswith("j'"))

print("— la source de ce client")
s = (BACKEND / "classement" / "source.py").read_text(encoding="utf-8")
verifier("`fichiers_du_dossier` et `lire_fichier` existent dans la source du client",
         "async def fichiers_du_dossier(" in s and "async def lire_fichier(" in s)
if (BACKEND / "outils" / "drive.py").exists():
    verifier("Drive : le compte de la PERSONNE et ses périmètres, lecture par type (images comprises), jamais de dépôt",
             "_identite(user)" in s and "_garde_perimetre(vise, perimetres)" in s
             and "d._binaire(" in s and "lire_sans_deposer(" in s)
else:
    verifier("NAS : le rôle est contrôlé, lecture par type (images comprises), rien n'est déposé",
             "verifier_role(user)" in s and "nas.octets(str(ref))" in s and "lire_sans_deposer(" in s)
ag1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("l'inventaire est un résultat généreux (la liste ne passe pas par la coupe courte)",
         '"inventaire_dossier"' in ag1.split("RESULTATS_GENEREUX = {")[1].split("}")[0])
verifier("le menu éclair propose l'inventaire",
         "Inventaire d'un dossier" in (BACKEND.parent / "frontend" / "lib" / "raccourcis.ts").read_text(encoding="utf-8"))

print("— l'aperçu web garanti")
tools = types.ModuleType("browser.tools")


async def _fetch(url, user_id, agent_id, reason=""):
    return {"success": True, "content": "Texte de la page", "url": url, "apercu": "cle-capture-1", "title": "Vivre en Bois — clôtures"}


async def _search(query, user_id, agent_id, max_results):
    return {"success": True, "content": "…", "sources": ["https://a.fr/x", "https://b.fr/y"]}
tools.fetch_url, tools.web_search = _fetch, _search
sys.modules["browser"] = types.ModuleType("browser")
sys.modules["browser.tools"] = tools
bsk = charger(BACKEND / "browser" / "skills.py", "browser_skills_double")
p = asyncio.run(bsk.ouvrir_page({"url": "vivreenbois.com"}, U))
verifier("`ouvrir_page` pose la capture en bloc `site` GARANTI (url, titre, aperçu), et dit de ne pas le réécrire",
         p.get("bloc_garanti") is True and p["bloc_ui"] == {"type": "site", "url": "https://vivreenbois.com",
                                                             "titre": "Vivre en Bois — clôtures", "apercu": "cle-capture-1"}
         and "n'écris aucun bloc `site`" in p["a_faire"])
w = asyncio.run(bsk.chercher_web({"requete": "panneaux Tokyo"}, U))
verifier("`chercher_web` pose le tableau des adresses consultées, garanti",
         w.get("bloc_garanti") is True and w["bloc_ui"]["type"] == "table"
         and [l[0] for l in w["bloc_ui"]["rows"]] == ["https://a.fr/x", "https://b.fr/y"]
         and w["bloc_ui"]["columns"] == ["Adresse consultée", "Ce qu'on y a lu"])


async def _fetch_sans(url, user_id, agent_id, reason=""):
    return {"success": True, "content": "Texte", "url": url}
tools.fetch_url = _fetch_sans
p2 = asyncio.run(bsk.ouvrir_page({"url": "https://x.fr"}, U))
verifier("sans capture : pas de bloc, le texte seul (rien d'inventé)", "bloc_ui" not in p2 and p2["contenu"] == "Texte")

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs)); sys.exit(1)
print("✓ 0 échec")
