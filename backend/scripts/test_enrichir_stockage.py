"""
Banc « Enrichir les documents » — ouvrir le stockage, apprendre de tout,
proposer des skills (11/09).

Relevé de Noa chez Duret : « dans les paramètres, si je clique sur enrichir le
NAS ça marche pas, alors qu'il devrait ouvrir tous les fichiers du NAS pour
apprendre de tout, faire des skills en auto ». Quatre défauts, tous prouvés
ici en EXÉCUTANT le code livré contre des doublures :

  1. aucun skill n'était JAMAIS créé — la requête avait 4 emplacements et
     recevait 5 valeurs, l'exception était avalée (les deux campagnes) ;
  2. la campagne documentaire ne relisait que ce qu'une synchronisation
     PASSÉE avait laissé en base — elle n'ouvrait jamais le stockage ;
  3. elle s'arrêtait à 30 appels par niveau (règle du 01/09 : jamais bloqué
     en quantité) et ne proposait aucun skill ;
  4. (Duret) la synchronisation du NAS descendait `SYNOLOGY_FOLDERS` à la
     main : racine fantôme muette, corbeille parcourue, 6 niveaux, pas de
     pagination, tout retéléchargé à chaque passage.

Le même fichier des deux côtés : la partie NAS ne s'exécute que là où le
connecteur existe. Sans base, sans réseau, sans fastapi.
"""
import asyncio
import importlib.util
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import types
from contextlib import asynccontextmanager

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
sys.path.insert(0, str(BACKEND))
os.environ["DOCUMENTS_DIR"] = tempfile.mkdtemp(prefix="banc-enrichir-")

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def poser(nom, **attrs):
    mod = sys.modules.get(nom) or types.ModuleType(nom)
    mod.__path__ = getattr(mod, "__path__", [])
    # Une doublure a une « spec » : sans elle, le contrôle des connecteurs au
    # chargement du routeur (`find_spec`) les croirait introuvables.
    mod.__spec__ = getattr(mod, "__spec__", None) or importlib.util.spec_from_loader(nom, loader=None)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nom] = mod
    if "." in nom:
        parent, _, feuille = nom.rpartition(".")
        poser(parent)
        setattr(sys.modules[parent], feuille, mod)
    return mod


def charger(nom, chemin):
    mod = types.ModuleType(nom)
    mod.__file__ = str(BACKEND / chemin)
    exec(compile((BACKEND / chemin).read_text(encoding="utf-8"), mod.__file__, "exec"), mod.__dict__)
    poser(nom)
    sys.modules[nom] = mod
    parent, _, feuille = nom.rpartition(".")
    if parent:
        setattr(sys.modules[parent], feuille, mod)
    return mod


# ── LA BASE DOUBLÉE — elle refuse ce que le vrai asyncpg refuse ─────────────

class Base:
    def __init__(self):
        self.skills = {}               # name -> ligne
        self.documents = []            # lignes de `documents` (morceaux)
        self.ingeres = {}              # source_id -> date d'ingestion
        self.titres = set()            # (source_type, source_filename) en mémoire
        self.syncs = []                # lignes `synchronisations`
        self.voisine_en_cours = False
        self.requetes = []

    @staticmethod
    def _controle(sql, args):
        # « the server expects 4 arguments for this query, 5 were passed »
        attendus = max([int(n) for n in re.findall(r"\$(\d+)", sql)] or [0])
        if attendus != len(args):
            raise RuntimeError(f"the server expects {attendus} arguments for this "
                               f"query, {len(args)} were passed")

    async def execute(self, sql, *args):
        self._controle(sql, args)
        self.requetes.append(sql)
        if "INSERT INTO skills" in sql:
            self._inserer_skill(sql, args)
        return "OK"

    def _inserer_skill(self, sql, args):
        colonnes = re.search(r"INSERT INTO skills \(([^)]*)\)", sql).group(1)
        colonnes = [c.strip() for c in colonnes.split(",")]
        valeurs = re.search(r"VALUES \(([^)]*)\)", sql).group(1)
        ligne = {}
        for c, v in zip(colonnes, [v.strip() for v in valeurs.split(",")]):
            ligne[c] = args[int(v[1:]) - 1] if v.startswith("$") else v.strip("'")
        if ligne["name"] in self.skills:
            return None
        self.skills[ligne["name"]] = ligne
        return ligne["name"]

    async def fetchval(self, sql, *args):
        self._controle(sql, args)
        self.requetes.append(sql)
        if "SELECT 1 FROM skills" in sql:
            return 1 if args[0] in self.skills else None
        if "INSERT INTO skills" in sql:
            return self._inserer_skill(sql, args)
        if "SELECT 1 FROM documents" in sql:
            return 1 if (args[0], args[1]) in self.titres else None
        return None

    async def fetch(self, sql, *args):
        self._controle(sql, args)
        self.requetes.append(sql)
        if "MAX(created_at)" in sql:
            return [{"source_id": k, "d": v} for k, v in self.ingeres.items()]
        if "FROM documents WHERE source_type = ANY" in sql:
            return [l for l in self.documents if l["source_type"] in args[0]]
        return []

    async def fetchrow(self, sql, *args):
        self._controle(sql, args)
        self.requetes.append(sql)
        if "INSERT INTO synchronisations" in sql:
            if self.voisine_en_cours:
                return None
            self.syncs.append({"id": f"s{len(self.syncs) + 1}", "source": args[0],
                               "statut": "en_cours"})
            return {"id": self.syncs[-1]["id"]}
        if "FROM synchronisations" in sql:
            self.voisine_en_cours = False          # la voisine finit pendant qu'on l'attend
            return {"statut": "terminee", "erreur": None,
                    "resultat": json.dumps({"fichiers": 7, "ingérés": 7})}
        return None


BASE = Base()


@asynccontextmanager
async def get_db():
    yield BASE


poser("database.connection", get_db=get_db)
poser("security.acces", NIVEAUX=("all", "commercial_plus", "bureau_etudes_plus",
                                  "direction_only", "admin_only"),
      niveaux_visibles=lambda role: ["all"])
poser("llm.reglages", valeur=lambda nom: "")
poser("llm.concurrence", porter=lambda *a, **k: None)

CODES = []


async def _generer_code_skill(item):
    CODES.append(item["nom"])
    return "def run(data: dict) -> dict:\n    return {}\n"


# `debrief` est chargé VRAI (bibliothèque standard seulement) : c'est son
# `enregistrer` qui porte le « sans doublon ».
INGESTIONS = []


async def _ingest_document(**k):
    INGESTIONS.append(k)
    BASE.ingeres[k["source_id"]] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc)
    BASE.titres.add((k["source_type"], (k.get("source_filename") or "")[:200]))
    return 1


poser("ingestion.pipeline", ingest_document=_ingest_document)
poser("security.anonymizer", anonymizer=types.SimpleNamespace(
    rehydrate=lambda t, c: t, find_placeholders=lambda t: [],
    spacy_available=True, desactivee=lambda: True,
    anonymize_chunks=lambda textes, carte: (textes, {})))
debrief = charger("learning.debrief", "learning/debrief.py")
debrief.generer_code_skill = _generer_code_skill
enrichissement = charger("learning.enrichissement", "learning/enrichissement.py")

print(f"\n═══ ENRICHIR LES DOCUMENTS — {BACKEND}\n")

# ── 1. les skills se créent enfin ───────────────────────────────────────────
print("1. Les brouillons de skills s'écrivent (ils ne s'écrivaient JAMAIS)")
BASE.skills["deja_la"] = {"name": "deja_la"}
crees = asyncio.run(enrichissement._creer_skills(
    [{"nom": "metre_surface_lot", "description": "Calcule la surface d'un lot à partir des cotes.",
      "entrees": "longueur, largeur"},
     {"nom": "deja_la", "description": "Un skill déjà au catalogue, à ne pas recréer."}],
    acces="direction_only"))
verifier("un skill neuf est créé (4 emplacements pour 5 valeurs : il échouait toujours)",
         crees == ["metre_surface_lot"], crees)
ligne = BASE.skills.get("metre_surface_lot") or {}
verifier("…en BROUILLON désactivé : du code écrit par un modèle ne s'exécute pas sans relecture",
         ligne.get("status") == "draft" and ligne.get("enabled") == "false", ligne)
verifier("…avec le niveau d'accès demandé (la colonne de la migration 017 est nommée)",
         ligne.get("access_level") == "direction_only", ligne.get("access_level"))
verifier("un nom déjà au catalogue n'est ni recréé, ni compté, ni payé en code",
         "deja_la" not in crees and CODES == ["metre_surface_lot"], CODES)

# ── 2. la confiance juge le MODÈLE, pas l'agrégateur ────────────────────────
print("\n2. Le garde du modèle : l'agrégateur n'est pas le modèle")
C = enrichissement.modele_de_confiance
verifier("openrouter:deepseek/deepseek-v4-flash (toute la cascade de Duret) est de confiance",
         C("openrouter:deepseek/deepseek-v4-flash"))
verifier("openrouter:google/gemini-2.5-pro est de confiance", C("openrouter:google/gemini-2.5-pro"))
verifier("une variante GRATUITE ne l'est pas", not C("openrouter:deepseek/deepseek-r1:free"))
verifier("un petit modèle local ne l'est pas", not C("ollama:mistral:7b"))
verifier("un petit modèle Groq ne l'est pas", not C("groq:llama-3.1-8b-instant"))
verifier("les fournisseurs de confiance le restent", C("longcat:LongCat-2.0") and C("google:gemini-flash-latest"))

# ── 3. la campagne : ouvrir, puis TOUT lire, puis proposer ──────────────────
print("\n3. La campagne ouvre le stockage AVANT de lire, lit tout, propose des skills")
ORDRE = []
SYNCS = []


async def _synchroniser(source, user_id=None, email=None):
    SYNCS.append((source, user_id, email))
    ORDRE.append("collecte")
    # La synchronisation remplit la base : AVANT elle, il n'y a RIEN à relire —
    # exactement l'état de Duret quand Noa a cliqué.
    BASE.documents[:] = [
        {"source_id": f"synology:/home/Drive/AO/{i:02d}.pdf", "source_type": "nas",
         "source_filename": f"{i:02d}.pdf", "access_level": "all",
         "content": f"CCTP lot {i} : doublage placo BA13, ratio 1,05 m² par m²", "chunk_index": 0}
        for i in range(40)]
    return {"etat": "terminee", "resultat": {"fichiers": 44, "ingérés": 40, "format_non_lu": 4},
            "erreur": None}


poser("routers.ingestion", synchroniser_et_attendre=_synchroniser)
poser("classement.source", CONNECTEUR="synology", NOM_STOCKAGE="serveur de fichiers (NAS)")


async def _niveau_reel(sid, st):
    return None


poser("learning.acces_docs", niveau_reel=_niveau_reel)
campagne = charger("learning.enrichissement_docs", "learning/enrichissement_docs.py")

APPELS_LOT = []
ENREGISTRES = []


async def _lire_lot_docs(niveau, textes, exiger):
    ORDRE.append("analyse")
    APPELS_LOT.append(len(textes))
    # Le titre dépend du DOCUMENT lu : relancée, la campagne relit les mêmes
    # documents et en tire les mêmes connaissances.
    fichier = textes[0].split("]", 1)[0].strip("[")
    return ({"connaissances": [{"titre": f"Ratio doublage ({fichier})", "contenu": "Ratio de 1,05 m² de plaque par m² de cloison."}],
             "procedures": [],
             "competences": ([{"nom": "ratio_plaques_cloison",
                               "description": "Quantité de plaques BA13 pour une surface de cloison.",
                               "entrees": "surface_m2"}] if fichier in ("00.pdf", "01.pdf") else [])},
            {}, "openrouter:deepseek/deepseek-v4-flash")


_vrai_enregistrer = debrief.enregistrer


async def _enregistrer(propositions, carte, prefixe_source, acces_force=None, sans_doublon=False):
    ENREGISTRES.append(sans_doublon)
    return await _vrai_enregistrer(propositions, carte, prefixe_source, acces_force, sans_doublon)


debrief.enregistrer = _enregistrer
campagne._lire_lot_docs = _lire_lot_docs
enrichissement.PAUSE_ENTRE_LOTS_S = 0
enrichissement.BUDGET_CARACTERES_PAR_APPEL = 60      # un document par appel : 40 appels
BASE.documents = []
etat = asyncio.run(campagne.executer("noa@exemple-sols.fr", lance_par_id="u-1"))
verifier("la campagne OUVRE le stockage (sa synchronisation), une fois, au nom de qui l'a lancée",
         SYNCS == [("synology", "u-1", "noa@exemple-sols.fr")], SYNCS)
verifier("…AVANT de lire : la base était vide au clic, elle ne l'est plus à l'analyse",
         ORDRE[:1] == ["collecte"] and "analyse" in ORDRE and etat["documents"] == 40,
         (ORDRE[:3], etat["documents"]))
verifier("TOUT le corpus est lu : 40 appels pour 40 lots (l'écran bornait à 30 par niveau)",
         etat["appels_analyse"] == 40 and etat["appels_prevus"] == 40,
         (etat["appels_analyse"], etat["appels_prevus"]))
verifier("les tâches qui reviennent deviennent des BROUILLONS de skills, sans doublon",
         etat["skills"] == ["ratio_plaques_cloison"], etat["skills"])
verifier("…au niveau d'accès des fichiers dont ils viennent",
         BASE.skills["ratio_plaques_cloison"]["access_level"] == "all")
verifier("l'écriture en mémoire refuse les doublons (une campagne se relance)",
         ENREGISTRES and all(ENREGISTRES), ENREGISTRES[:3])
verifier("la phase finale dit « terminée », le bilan de l'ouverture est rendu à l'écran",
         etat["phase"] == "terminée" and "40 ingérés" in (etat.get("collecte") or {}).get("resume", ""),
         (etat["phase"], etat.get("collecte")))
verifier("le nom du stockage voyage jusqu'à l'écran", etat.get("stockage") == "serveur de fichiers (NAS)")

# Relancée : les mêmes connaissances ne se réécrivent pas.
avant = len(INGESTIONS)
etat2 = asyncio.run(campagne.executer("noa@exemple-sols.fr", lance_par_id="u-1"))
verifier("relancée, la campagne ne réécrit pas ce qu'elle sait déjà",
         len(INGESTIONS) == avant and etat2["deja_connues"] == 40,
         (len(INGESTIONS) - avant, etat2["deja_connues"]))

# Un stockage qui ne répond pas : la campagne le DIT, en tête.


async def _sync_en_panne(source, user_id=None, email=None):
    return {"etat": "non_configure", "resultat": None,
            "erreur": "Synology non configuré : SYNOLOGY_USER et SYNOLOGY_PASSWORD manquants dans le .env."}


sys.modules["routers.ingestion"].synchroniser_et_attendre = _sync_en_panne
BASE.documents = []
etat = asyncio.run(campagne.executer("noa@exemple-sols.fr"))
verifier("un stockage injoignable se dit avec SA raison (plus jamais « ça marche pas » muet)",
         any("SYNOLOGY_USER" in e and "serveur de fichiers (NAS)" in e for e in etat["echecs"]),
         etat["echecs"])
verifier("…et une base vide le dit aussi, en nommant le stockage",
         "aucun document lisible" in etat["phase"] and "serveur de fichiers (NAS)" in etat["phase"],
         etat["phase"])

SYNCS.clear()
sys.modules["routers.ingestion"].synchroniser_et_attendre = _synchroniser
asyncio.run(campagne.executer("noa@exemple-sols.fr", collecter=False))
verifier("`collecter: false` relit seulement la base (le geste d'avant reste possible)", SYNCS == [])

# Un plafond explicite reste un échantillon, et le garde d'emballement parle.
APPELS_LOT.clear()
etat = asyncio.run(campagne.executer("noa@exemple-sols.fr", max_lots_par_niveau=5))
verifier("un nombre explicite borne à un échantillon", etat["appels_analyse"] == 5, etat["appels_analyse"])
campagne.MAX_APPELS_CAMPAGNE = 12
etat = asyncio.run(campagne.executer("noa@exemple-sols.fr"))
verifier("le garde d'emballement s'arrête ET le dit",
         etat["appels_analyse"] == 12 and any("emballement" in e for e in etat["echecs"]),
         (etat["appels_analyse"], etat["echecs"][-1:]))
campagne.MAX_APPELS_CAMPAGNE = 2000
src_camp = (BACKEND / "learning" / "enrichissement_docs.py").read_text(encoding="utf-8")
verifier("l'analyse passe toujours par la reprise de cascade",
         re.search(r"await avec_reprise\(\s*lambda: _lire_lot_docs\(", src_camp) is not None)

# ── 4. la porte « synchroniser et attendre » (routers/ingestion.py) ─────────
print("\n4. La collecte passe par la MÊME porte que le bouton")


class _HTTPException(Exception):
    def __init__(self, status_code=None, detail=None):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class _Routeur:
    def __getattr__(self, _):
        return lambda *a, **k: (lambda f: f)


poser("fastapi", APIRouter=lambda *a, **k: _Routeur(), Depends=lambda *a, **k: None,
      File=lambda *a, **k: None, Header=lambda *a, **k: None, HTTPException=_HTTPException,
      UploadFile=object, status=types.SimpleNamespace(
          HTTP_403_FORBIDDEN=403, HTTP_404_NOT_FOUND=404, HTTP_409_CONFLICT=409,
          HTTP_400_BAD_REQUEST=400, HTTP_422_UNPROCESSABLE_ENTITY=422,
          HTTP_413_REQUEST_ENTITY_TOO_LARGE=413, HTTP_502_BAD_GATEWAY=502,
          HTTP_500_INTERNAL_SERVER_ERROR=500))
poser("pydantic", BaseModel=object)
poser("auth.dependencies", get_current_user=lambda: None)
poser("database.models", User=object)
poser("security.rbac", has_permission=lambda role, f: role == "super_admin")


async def _log_action(**k):
    return None


poser("security.audit", log_action=_log_action)
poser("config", settings=types.SimpleNamespace())
routeur_src = (BACKEND / "routers" / "ingestion.py").read_text(encoding="utf-8")
CONNECTEURS = dict(re.findall(r'^\s+"(\w+)": \("[^"]+", "(ingestion\.connectors\.\w+)"\)',
                              routeur_src, re.M))
for cle, module in CONNECTEURS.items():
    async def _sync(avancer=None, _cle=cle):
        if avancer:
            await avancer(3, 10, "j'ouvre devis.pdf")
        return {"fichiers": 10, "ingérés": 10}
    poser(module, sync=_sync)
try:
    ingestion = charger("routers.ingestion", "routers/ingestion.py")
except Exception as e:  # noqa: BLE001
    ingestion = None
    verifier("routers/ingestion.py se charge", False, repr(e))
if ingestion is not None:
    source_cle = re.search(r'^CONNECTEUR = "(\w+)"',
                           (BACKEND / "classement" / "source.py").read_text(encoding="utf-8"), re.M)
    verifier("le stockage de ce client est déclaré et c'est un connecteur de l'écran",
             bool(source_cle) and source_cle.group(1) in ingestion.CONNECTEURS,
             source_cle and source_cle.group(1))
    BASE.syncs.clear()
    r = asyncio.run(ingestion.synchroniser_et_attendre(source_cle.group(1), "u-1", "noa@exemple-sols.fr"))
    verifier("la synchronisation est ATTENDUE et son bilan rendu",
             r.get("etat") == "terminee" and (r.get("resultat") or {}).get("ingérés") == 10, r)
    verifier("…par une ligne `synchronisations` (la carte du connecteur montre l'avancement)",
             len(BASE.syncs) == 1 and any("UPDATE synchronisations SET traites" in q for q in BASE.requetes))
    BASE.voisine_en_cours = True
    _vrai_sleep = asyncio.sleep
    ingestion.asyncio = types.SimpleNamespace(sleep=lambda s: _vrai_sleep(0),
                                              create_task=asyncio.create_task)
    r = asyncio.run(ingestion.synchroniser_et_attendre(source_cle.group(1), "u-1", "noa@exemple-sols.fr"))
    verifier("une synchronisation déjà lancée à la main est ATTENDUE, pas doublée",
             r.get("etat") == "terminee" and (r.get("resultat") or {}).get("ingérés") == 7
             and len(BASE.syncs) == 1, r)
    try:
        asyncio.run(ingestion.synchroniser_et_attendre("inconnu"))
        verifier("une source inconnue est refusée", False)
    except ValueError:
        verifier("une source inconnue est refusée", True)
    verifier("le bouton passe par le même verrou (`_ouvrir_sync`)",
             "await _ouvrir_sync(" in routeur_src.split("async def demarrer_sync")[1].split("\nasync def ")[0])

routes = (BACKEND / "routers" / "learning.py").read_text(encoding="utf-8")
corps = routes.split('"/enrichir-documents")')[1][:1600]
verifier("la route transmet `collecter` et l'identité de qui lance",
         "collecter=body.collecter" in corps and "lance_par_id=current_user.id" in corps)
verifier("la route n'impose plus 30/60 appels : 0 = tout", "max_lots_par_niveau: int = 0" in routes)
ecran = (BACKEND.parent / "frontend" / "components" / "settings" / "SyncTab.tsx").read_text(encoding="utf-8")
verifier("l'écran lance l'ouverture du stockage et tout le corpus",
         "collecter: true" in ecran and "max_lots_par_niveau: 0" in ecran)
verifier("l'écran montre la phase EN ENTIER, les skills créés et les dernières erreurs",
         "{enrichDocs.phase}</div>" in ecran and "enrichDocs.skills" in ecran
         and "enrichDocs.echecs.slice(-3)" in ecran)

# ── 5. (là où il existe) la synchronisation du NAS ──────────────────────────
CONNECTEUR_NAS = BACKEND / "ingestion" / "connectors" / "synology.py"
if not CONNECTEUR_NAS.exists():
    print("\n5. Synchronisation du NAS — sans objet ici (le stockage est le Drive)")
    drive = (BACKEND / "ingestion" / "connectors" / "google_drive.py").read_text(encoding="utf-8")
    verifier("la synchronisation du Drive rend compte de son avancement (`avancer`)",
             "async def sync(folder_id: Optional[str] = None, avancer=None)" in drive)
else:
    print("\n5. La synchronisation du NAS part du catalogue, pagine, et ne relit pas l'inchangé")
    ARBRE = {"/home": [("Drive", True), ("#recycle", True)],
             "/home/#recycle": [("vieux-devis.pdf", False)],
             "/home/Drive": [("03-Appel d'offres etudes", True), ("photo-chantier.jpg", False),
                             ("DCE.zip", False)],
             "/home/Drive/03-Appel d'offres etudes": [(f"CCTP-{i:03d}.pdf", False) for i in range(250)]}
    profond = "/home/Drive/03-Appel d'offres etudes"
    for n in range(1, 10):                      # neuf niveaux : l'ancienne synchro s'arrêtait à six
        nom = f"niveau {n} " + "x" * 22
        ARBRE.setdefault(profond, []).append((nom, True))
        profond = f"{profond}/{nom}"
    ARBRE[profond] = [("RC tres profond.pdf", False)]
    LISTES = []
    TELECHARGES = []

    async def _appel(client, base, api, method, version, sid=None, **p):
        if api == "SYNO.FileStation.List" and method == "list":
            chemin = p["folder_path"]
            LISTES.append((chemin, p.get("offset"), p.get("limit")))
            if chemin not in ARBRE:
                raise RuntimeError("Synology (SYNO.FileStation.List.list) : ce dossier N'EXISTE PAS")
            tout = ARBRE[chemin]
            debut, lim = int(p.get("offset") or 0), int(p.get("limit") or 100)
            return {"total": len(tout), "files": [
                {"name": n, "path": f"{chemin}/{n}", "isdir": d,
                 "additional": {"size": None if d else 2048, "time": {"mtime": 1_700_000_000}}}
                for n, d in tout[debut:debut + lim]]}
        return {}

    async def _telecharger_ou_raison(client, base, sid, chemin):
        TELECHARGES.append(chemin)
        return b"contenu", ""

    poser("config", settings=types.SimpleNamespace(
        synology_folders="/home,/Drive", synology_access_level="all",
        synology_source_type="nas", synology_max_file_mb=25, synology_verify_tls=False))
    poser("skills.affichage", garantir_fichier_lu=lambda r, *a, **k: r)
    parsers = charger("ingestion.parsers", "ingestion/parsers.py")

    def _analyser(nom, brut):
        if nom.endswith(".jpg"):
            raise parsers.FichierNonSupporte("Aucun texte reconnu dans cette image.")
        return {"kind": "document", "text": f"texte de {nom}", "rows": [], "columns": []}

    parsers.analyser = _analyser
    synology = charger("ingestion.connectors.synology", "ingestion/connectors/synology.py")
    synology._appel = _appel
    synology._telecharger_ou_raison = _telecharger_ou_raison
    acces = charger("nas.acces", "nas/acces.py")
    # 13/09 : le NAS se filtre par niveau de dossier (nas/niveaux.py) pour le
    # lecteur posé par l'exécuteur (security/lecteur.py). Hors d'un geste, aucun
    # lecteur : ces bancs, qui jouent le système, voient tout comme avant.
    charger("security.lecteur", "security/lecteur.py")
    charger("nas.niveaux", "nas/niveaux.py")
    # 15/09 : le tri avant la lecture (`nas/tri.py`) — sans règle validée, tout
    # est « à apprendre », mais les photos sont écartées sans être ouvertes.
    import os as _os, tempfile as _tempfile
    _os.environ["DOCUMENTS_DIR"] = _tempfile.mkdtemp(prefix="banc-nas-")
    charger("nas.tri", "nas/tri.py")

    @asynccontextmanager
    async def _connexion():
        yield None, "http://nas", "sid"

    acces.connexion = _connexion

    r = asyncio.run(acces.lister("/home/Drive/03-Appel d'offres etudes"))
    verifier("le listage du CHAT reste borné à 200 et le dit", len(r["entrees"]) == 200 and r["tronque"])
    INGESTIONS.clear()
    BASE.ingeres.clear()
    AVANCES = []

    async def _avancer(t, total, etape):
        AVANCES.append((t, total))

    res = asyncio.run(synology.sync(avancer=_avancer))
    noms = {pathlib.PurePosixPath(k["source_filename"]).name for k in INGESTIONS}
    verifier("les 250 CCTP d'un même dossier sont TOUS ouverts (la page de 200 n'arrête plus rien)",
             sum(1 for n in noms if n.startswith("CCTP-")) == 250, len(noms))
    verifier("un fichier à neuf niveaux de profondeur est ouvert (l'ancienne synchro s'arrêtait à six)",
             "RC tres profond.pdf" in noms)
    verifier("la corbeille du NAS n'est jamais ouverte", not any("#recycle" in c for c in TELECHARGES))
    verifier("la racine fantôme du .env se DIT au lieu de passer pour un NAS vide",
             res.get("racines_introuvables") == "/Drive", res)
    verifier("une archive n'est pas téléchargée, elle est comptée", res.get("format_non_lu") == 1
             and not any(c.endswith(".zip") for c in TELECHARGES), res)
    # 15/09 : une photo n'est plus ouverte du tout (tri sans IA) — elle est comptée.
    verifier("une photo n'est pas ouverte, elle est comptée", res.get("photos") == 1
             and not any(c.endswith(".jpg") for c in TELECHARGES), res)
    verifier("l'avancement est rendu à l'écran, total compris",
             AVANCES and AVANCES[-1] == (251, 251), AVANCES[-1:])
    ids = [k["source_id"] for k in INGESTIONS]
    verifier("aucun identifiant ne dépasse les 255 caractères de la colonne",
             max(len(i) for i in ids) <= 255 and any(i.startswith("synology:#") for i in ids),
             max(len(i) for i in ids))
    verifier("l'identifiant long reste STABLE (resynchronisation sans doublon)",
             synology._source_id(profond + "/RC tres profond.pdf")
             == synology._source_id(profond + "/RC tres profond.pdf"))

    TELECHARGES.clear()
    acces._CATALOGUE["construit_le"] = time.monotonic()        # catalogue frais : pas de nouveau relevé
    res2 = asyncio.run(synology.sync())
    verifier("relancée, elle ne rouvre RIEN d'inchangé (ni la photo)",
             TELECHARGES == [] and res2.get("inchangés") == 251 and res2.get("photos") == 1,
             (len(TELECHARGES), res2))
    # 15/09 — PAR PALIERS, SANS SATURER LE SERVEUR. Noa : « 9 000 fichiers
    # prennent plusieurs jours, il faudrait des paliers en minutes sans que ça
    # bouche ou sature le CPU ». Horloge doublée : chaque lecture de l'horloge
    # avance de 7 s ; les pauses sont ENREGISTRÉES, pas dormies.
    print("\n5 bis. Par paliers, et jamais sur un serveur chargé")
    import time as _vrai_temps
    horloge = [1000.0]
    ancienne_monotonic = _vrai_temps.monotonic

    def _fausse_monotonic():
        horloge[0] += 7
        return horloge[0]
    PAUSES = []

    async def _fausse_pause(sec):
        PAUSES.append(sec)
        horloge[0] += sec
    async def _rien_d_ingere():
        return {}
    sys.modules["config"].settings.nas_palier_minutes = 1
    sys.modules["config"].settings.nas_pause_minutes = 2
    sys.modules["config"].settings.nas_charge_max = 0.75
    charges = [0.95, 0.95, 0.40]
    synology._charge = lambda: (charges.pop(0) if charges else 0.30)
    synology._dates_ingerees = _rien_d_ingere
    synology._lire_ecartes = lambda: {}
    sys.modules["nas.tri"].fenetre_de_nuit = lambda heure=None: False
    vrai_sleep = synology._asyncio.sleep
    synology._asyncio = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith("__")})
    synology._asyncio.sleep = _fausse_pause
    ETAPES = []

    async def _noter(t, total, etape):
        ETAPES.append(etape)
    _vrai_temps.monotonic = _fausse_monotonic
    try:
        acces._CATALOGUE["construit_le"] = horloge[0] + 10 ** 6
        res3 = asyncio.run(synology.sync(avancer=_noter))
    finally:
        _vrai_temps.monotonic = ancienne_monotonic
    verifier("un serveur chargé fait ATTENDRE la lecture suivante (et le dit)",
             PAUSES[0] == synology.ATTENTE_CHARGE_S
             and any("serveur chargé" in e for e in ETAPES), (PAUSES[:3], ETAPES[:2]))
    verifier("au bout d'un palier, une PAUSE de souffle, annoncée avec l'heure de reprise",
             120 in PAUSES and any("palier 1 terminé" in e and "reprise vers" in e for e in ETAPES),
             [e for e in ETAPES if "palier" in e][:1])
    verifier("tout est quand même lu, palier après palier", res3.get("ingérés") == 251, res3)
    verifier("l'écran dit le rythme et le temps restant", any("fichier(s)/min" in e and "reste ~" in e for e in ETAPES))
    verifier("le compte rendu dit où passe le temps (NAS, lecture, base)",
             set(res3.get("temps_moyen_s") or {}) == {"telechargement", "lecture", "base"}, res3)
    # 15/09 (suite) — UN PALIER AUTOMATIQUE S'ARRÊTE À SON TEMPS, et le serveur
    # en relance un à chaque cycle, sans navigateur.
    print("\n5 ter. L'intégration continue : un palier borné, relancé par le serveur")
    horloge[0] = 1000.0
    PAUSES.clear()
    _vrai_temps.monotonic = _fausse_monotonic
    try:
        res4 = asyncio.run(synology.sync(budget_s=120))
    finally:
        _vrai_temps.monotonic = ancienne_monotonic
    verifier("le palier s'arrête à son budget, dit ce qui reste, et ne fait AUCUNE pause",
             res4.get("palier") and 0 < res4.get("ingérés", 0) < 251 and res4.get("reste_a_lire")
             and 120 not in PAUSES and "prochain palier" in res4.get("raison_partielle", ""), res4)
    tri_mod = sys.modules["nas.tri"]
    LANCES = []

    async def _ouvrir(source, uid, email):
        return None if LANCES and LANCES[-1] == "occupe" else "sync-1"

    async def _executer(source, module, uid, sync_id, **options):
        LANCES.append(options.get("budget_s"))
        routeur_double._SYNCS["synology"] = {"resultat": {"ouverts": 0}}
    routeur_double = poser("routers.ingestion", CONNECTEURS={"synology": ("NAS", "x")}, _SYNCS={},
                           _executer_sync=_executer, _ouvrir_sync=_ouvrir)
    poser("llm.reglages", valeur=lambda nom: "active")
    sys.modules["config"].settings.nas_cycle_minutes = 10
    sys.modules["config"].settings.nas_palier_lecture_minutes = 8
    tri_mod._CONTINU.update({"prochain": None, "dernier": None, "catalogue_vu": None, "rien_a_lire": False})
    asyncio.run(tri_mod.palier_si_du(maintenant=10_000))
    verifier("le serveur lance lui-même un palier de 8 min", LANCES == [480], LANCES)
    asyncio.run(tri_mod.palier_si_du(maintenant=10_000 + 300))
    verifier("pas de second palier avant la fin du cycle de 10 min", LANCES == [480], LANCES)
    asyncio.run(tri_mod.palier_si_du(maintenant=10_000 + 601))
    verifier("rien lu la dernière fois et NAS non relevé depuis : pas de palier inutile", LANCES == [480], LANCES)
    acces._CATALOGUE["construit_le"] = "nouveau relevé"
    asyncio.run(tri_mod.palier_si_du(maintenant=10_000 + 1300))
    verifier("le NAS relevé à nouveau : le palier repart", LANCES == [480, 480], LANCES)
    poser("llm.reglages", valeur=lambda nom: "desactivee")
    asyncio.run(tri_mod.palier_si_du(maintenant=10_000 + 5000))
    verifier("« Intégration continue » coupée : aucun palier", LANCES == [480, 480], LANCES)
    principal = (BACKEND / "main.py").read_text(encoding="utf-8")
    routeur_src = (BACKEND / "routers" / "ingestion.py").read_text(encoding="utf-8")
    verifier("la boucle démarre avec le serveur, et les tâches de fond sont TENUES (pas ramassées en route)",
             "lancer_en_fond(boucle_continue())" in principal and "_TACHES.add(tache)" in routeur_src
             and "lancer_en_fond(_executer_sync(" in routeur_src)

    parsers_src = (BACKEND / "ingestion" / "parsers.py").read_text(encoding="utf-8")
    verifier("les threads de lecture (et l'OCR qu'ils lancent) passent APRÈS le chat (nice 15)",
             "initializer=_basse_priorite" in parsers_src and "os.setpriority" in parsers_src)
    verifier("le jour, un fichier trop long à lire est remis à la NUIT au lieu d'être perdu",
             "lourds_remis_à_la_nuit" in CONNECTEUR_NAS.read_text(encoding="utf-8"))

    src_nas = CONNECTEUR_NAS.read_text(encoding="utf-8")
    verifier("l'ancien parcours maison a disparu (une seule façon de voir le NAS)",
             "_lister_recursif" not in src_nas and "catalogue_attendu" in src_nas)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
