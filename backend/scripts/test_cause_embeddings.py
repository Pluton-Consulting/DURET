"""
Banc « la mémoire vectorielle dit pourquoi elle ne vectorise pas » — 15/09.

Relevé de Noa chez Duret : « le bouton re-vectoriser le corpus marche pas ».
L'écran montrait 0 morceau vectorisé sur 36 795, le bouton grisé, et la même
phrase partout : « Le modèle n'a rendu aucun vecteur. Vérifiez la clé du
fournisseur et le nom du modèle ». Trois défauts derrière, tous muets :

  · LA CLÉ GOOGLE DE PARAMÈTRES N'ATTEIGNAIT PAS LES EMBEDDINGS.
    `vectorstore/embeddings.py` lisait `settings.google_api_key` (le `.env`),
    jamais `llm.cles` : une clé valide saisie à l'écran — sur la ligne qui dit
    « Embeddings de la mémoire d'entreprise » — restait sans effet, et celle
    du `.env` de Duret est refusée par Google ;
  · UN MODÈLE DE CONVERSATION ÉTAIT ACCEPTÉ POUR VECTORISER : faute
    d'embedding reconnu chez Ollama Cloud, la ligne proposait toute sa liste,
    et « ollama_cloud:deepseek-v4-flash:0731 » a été posé. L'écriture ne
    vérifiait que la forme ;
  · LA RÉPONSE DU FOURNISSEUR ÉTAIT JETÉE (seul le nom de l'exception était
    journalisé), donc aucun écran ne pouvait dire QUEL geste faire.

Et un trou de parité : Duret n'essayait que `/v1/embeddings` chez Ollama Cloud,
que l'abonnement rend en 404 (mesuré chez Symbiose le 02/09).

Le banc EXÉCUTE le module contre un fournisseur doublé : aucun réseau.
"""
import ast
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LA CAUSE D'UNE MÉMOIRE QUI NE VECTORISE PAS — {BACKEND.resolve().parent}\n")

CLE_ENV = "AIzaCLEDUENVREFUSEE0000000000000000000"
CLE_PARAMETRES = "AIzaCLEDEPARAMETRESVALIDE00000000000000"

# ── Les dépendances doublées ─────────────────────────────────────────────
settings = types.SimpleNamespace(
    google_api_key=CLE_ENV, openai_api_key=None, embedding_provider="gemini",
    gemini_embedding_model="gemini-embedding-001", embedding_dimensions=1536,
    embedding_max_chars=8000, embedding_min_interval_s=0.0,
    embedding_daily_request_cap=100000, embedding_cooldown_s=600,
    ollama_cloud_base_url="https://ollama.com/v1", ollama_cloud_embedding_model="embeddinggemma",
    ollama_base_url="http://localhost:11434", ollama_embedding_model="bge-m3",
    embedding_model="text-embedding-3-small")
sys.modules["config"] = types.SimpleNamespace(settings=settings)
# httpx n'est pas sur tous les postes : le client est doublé plus bas.
sys.modules.setdefault("httpx", types.SimpleNamespace(AsyncClient=object))

CLES = {"google_api_key": CLE_PARAMETRES, "ollama_cloud_api_key": "cle-ollama"}
REGLAGES = {"modele_embedding": ""}
llm = types.ModuleType("llm")
llm.__path__ = []
sys.modules["llm"] = llm
sys.modules["llm.cles"] = types.SimpleNamespace(
    valeur=lambda nom: CLES.get(nom) or getattr(settings, nom, None))
sys.modules["llm.reglages"] = types.SimpleNamespace(texte=lambda nom: REGLAGES.get(nom, ""))

# L'heuristique d'usage, la VRAIE, extraite de llm/router.py.
source_router = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")
arbre = ast.parse(source_router)
morceaux = [n for n in arbre.body
            if (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("_MARQUES_EMBEDDING", "_MARQUES_VISION") for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "usage_du_modele")]
espace_router: dict = {}
exec(compile(ast.Module(body=morceaux, type_ignores=[]), "router", "exec"), espace_router)
sys.modules["llm.router"] = types.SimpleNamespace(usage_du_modele=espace_router["usage_du_modele"])

vectorstore = types.ModuleType("vectorstore")
vectorstore.__path__ = []
sys.modules["vectorstore"] = vectorstore


async def _dimension_attendue():
    return 1536
sys.modules["vectorstore.revectorisation"] = types.SimpleNamespace(dimension_attendue=_dimension_attendue)

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("vectorstore.embeddings", BACKEND / "vectorstore" / "embeddings.py")
emb = importlib.util.module_from_spec(spec)
sys.modules["vectorstore.embeddings"] = emb
async def _actif(): return emb.modele_courant()
sys.modules["vectorstore.generation"] = types.SimpleNamespace(actif=_actif)
spec.loader.exec_module(emb)


# ── Le fournisseur doublé ────────────────────────────────────────────────
class _Rep:
    def __init__(self, code, corps):
        self.status_code, self._corps = code, corps
        import json
        self.text = json.dumps(corps) if not isinstance(corps, str) else corps

    def json(self):
        if isinstance(self._corps, str):
            raise ValueError("pas du JSON")
        return self._corps

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} pour une URL qui porte la clé")


APPELS: list = []
REPONSES: dict = {}


class _Client:
    is_closed = False

    async def post(self, url, json=None, headers=None):
        APPELS.append(url)
        for motif, rep in REPONSES.items():
            if motif in url:
                return rep(json) if callable(rep) else rep
        return _Rep(500, {"error": {"message": "inattendu"}})


emb._client = lambda: _Client()


def _gemini_ok(corps):
    return _Rep(200, {"embeddings": [{"values": [0.1] * 1536} for _ in corps["requests"]]})


# 1. La clé de Paramètres est celle qui part chez Google.
APPELS.clear(); REPONSES.clear()
REPONSES["batchEmbedContents"] = _gemini_ok
v = asyncio.run(emb.embed_texts(["essai"]))
verifier("EXÉCUTÉ — la clé Google saisie dans Paramètres est celle envoyée",
         APPELS and CLE_PARAMETRES in APPELS[-1] and CLE_ENV not in APPELS[-1], str(APPELS[-1:])[:80])
verifier("et un vecteur revient", bool(v and v[0] and len(v[0]) == 1536))

# 2. Google refuse la clé : la cause est dite, sans la clé.
APPELS.clear(); REPONSES.clear()
REPONSES["batchEmbedContents"] = _Rep(400, {"error": {
    "code": 400, "status": "INVALID_ARGUMENT",
    "message": f"API key not valid. Please pass a valid API key. key={CLE_PARAMETRES}"}})
v = asyncio.run(emb.embed_texts(["essai"]))
cause = emb.raison_du_silence()
verifier("EXÉCUTÉ — un refus de Google rend None sans lever", v == [None])
verifier("la cause dit « HTTP 400 » et que la clé Google est refusée",
         "HTTP 400" in cause and "clé Google est refusée" in cause, cause)
verifier("le message de Google reste lisible (« API key not valid »)", "API key not valid" in cause, cause)
verifier("la cause ne porte JAMAIS la clé, même quand Google la recopie",
         CLE_PARAMETRES not in cause and CLE_ENV not in cause, cause)

# 3. Une API non activée sur le projet se reconnaît.
REPONSES["batchEmbedContents"] = _Rep(403, {"error": {"code": 403, "status": "PERMISSION_DENIED",
    "message": "Generative Language API has not been used in project 123 before or it is disabled."}})
asyncio.run(emb.embed_texts(["essai"]))
verifier("un 403 « API non activée » le dit", "n'est pas activée" in emb.raison_du_silence(), emb.raison_du_silence())

# 4. Un succès efface le refus.
REPONSES["batchEmbedContents"] = _gemini_ok
asyncio.run(emb.embed_texts(["essai"]))
verifier("après un succès, plus aucune cause n'est affichée", emb.raison_du_silence() == "",
         emb.raison_du_silence())

# 5. Le cas exact de Duret : un modèle de conversation chez Ollama Cloud.
APPELS.clear(); REPONSES.clear()
REPONSES["/v1/embeddings"] = _Rep(404, '404 page not found')
REPONSES["/api/embed"] = _Rep(400, {"error": 'model "deepseek-v4-flash:0731" does not support embeddings'})
REGLAGES["modele_embedding"] = "ollama_cloud:deepseek-v4-flash:0731"
v = asyncio.run(emb.embed_texts(["essai"]))
cause = emb.raison_du_silence()
verifier("EXÉCUTÉ — les DEUX routes d'Ollama Cloud sont essayées (parité avec Symbiose)",
         any("/v1/embeddings" in a for a in APPELS) and any(a.endswith("/api/embed") for a in APPELS), str(APPELS))
verifier("la cause reprend la réponse d'Ollama Cloud", "does not support embeddings" in cause, cause)
verifier("et dit que c'est un modèle de conversation, avec un modèle qui vectorise",
         "modèle de conversation" in cause and "gemini-embedding-001" in cause, cause)

# 6. Ollama Cloud qui vectorise par la route native.
APPELS.clear(); REPONSES.clear()
REPONSES["/v1/embeddings"] = _Rep(404, '404 page not found')
REPONSES["/api/embed"] = lambda corps: _Rep(200, {"embeddings": [[0.2] * 768 for _ in corps["input"]]})
REGLAGES["modele_embedding"] = "ollama_cloud:embeddinggemma"
v = asyncio.run(emb.embed_texts(["un", "deux"]))
verifier("EXÉCUTÉ — un 404 sur /v1/embeddings retombe sur /api/embed, qui vectorise",
         v and all(x and len(x) == 768 for x in v), str(v)[:80])
verifier("et le refus précédent est oublié", emb.raison_du_silence() == "", emb.raison_du_silence())
REGLAGES["modele_embedding"] = ""

# 7. La mesure garde la priorité de la pause de quota.
emb._gemini_throttle._cooldown_until = emb.time.monotonic() + 120
verifier("une pause de quota reste dite telle quelle", "pause de quota" in emb.raison_du_silence())
emb._gemini_throttle._cooldown_until = 0.0

# ── L'écriture du réglage mesure le modèle ───────────────────────────────
source_settings = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
fn = next((n for n in ast.parse(source_settings).body
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "_refus_du_modele_embedding"), None)
verifier("la route des réglages porte `_refus_du_modele_embedding`", fn is not None)
if fn is not None:
    MESURE = {"rep": (None, "")}

    async def _mesurer(modele=""):
        return MESURE["rep"]
    sys.modules["vectorstore.revectorisation"] = types.SimpleNamespace(
        mesurer_dimension=_mesurer, dimension_attendue=_dimension_attendue)
    espace: dict = {"Optional": __import__("typing").Optional}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "settings", "exec"), espace)
    refus = espace["_refus_du_modele_embedding"]
    MESURE["rep"] = (None, "Le modèle n'a rendu aucun vecteur : Ollama Cloud refuse la requête (HTTP 400)")
    r = asyncio.run(refus("modele_embedding", "ollama_cloud:deepseek-v4-flash:0731"))
    verifier("EXÉCUTÉ — un modèle qui ne rend aucun vecteur est REFUSÉ, avec la cause",
             r.startswith("Rien n'a changé") and "HTTP 400" in r, r)
    MESURE["rep"] = (None, "Le modèle n'a rendu aucun vecteur : Gemini est en pause de quota encore 30 s")
    verifier("une pause de quota n'empêche pas de choisir",
             asyncio.run(refus("modele_embedding", "google:gemini-embedding-001")) == "")
    MESURE["rep"] = (1536, "1536 dimensions")
    verifier("un modèle qui vectorise passe", asyncio.run(refus("modele_embedding", "google:gemini-embedding-001")) == "")
    verifier("les autres réglages ne sont pas mesurés",
             asyncio.run(refus("modele_rapide", "ollama_cloud:deepseek-v4-flash:0731")) == "")
    verifier("« Retirer » (valeur vide) n'est jamais bloqué", asyncio.run(refus("modele_embedding", "")) == "")
verifier("la route appelle la mesure AVANT d'enregistrer",
         "_refus_du_modele_embedding(body.cle" in source_settings
         and source_settings.index("_refus_du_modele_embedding(body.cle")
         < source_settings.index("effective = await enregistrer(body.cle"))

carte = (BACKEND.resolve().parent / "frontend" / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
verifier("la ligne « Embeddings » ne propose plus la liste des modèles de conversation",
         'if (usage === "embedding") return { ...f, modeles: [] }' in carte)
verifier("un menu vide le dit", "aucun modèle d'embedding connu chez ce fournisseur" in carte)
verifier("le module ne lit plus la clé Google du seul `.env`",
         "def _cle(" in (src := emb.__loader__.get_source("vectorstore.embeddings"))
         and "settings.google_api_key" not in src.split("def _cle(")[1])

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
