"""
Banc de la TRANSCRIPTION DE LA VOIX — dans l'application, pas dans le navigateur.

LA DEMANDE (03/09, Noa) : « le micro peut fonctionner, il faut que le
transcripteur soit intégré à l'app ». La première version s'en remettait à la
reconnaissance vocale du navigateur, absente sur la moitié des postes : le
bouton disait « ce navigateur ne sait pas transcrire la voix » devant un micro
qui marchait.

CE QUE CE BANC PROUVE, le module `voix/transcription.py` EXÉCUTÉ contre une
API Google doublée :
  · l'audio part en `inlineData` avec la consigne de FIDÉLITÉ, à température
    zéro, sous le type MIME nu (le navigateur envoie « audio/webm;codecs=opus ») ;
  · sans clé Google, le refus dit quoi faire — et ne contient jamais la clé ;
  · un 503 se réessaie, un 429 se dit (quota), un 404 passe au modèle suivant ;
  · le texte rendu est nu : guillemets et clôtures retirés ;
  · la route `/api/chat/transcrire` existe, authentifiée, et rend le texte.
"""
import asyncio
import base64
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ TRANSCRIPTION DE LA VOIX — {BACKEND.parent}\n")
source = BACKEND / "voix" / "transcription.py"
if not source.exists():
    print("  ✗ backend/voix/transcription.py est absent — la voix n'est pas transcrite par l'app.")
    sys.exit(1)

# ── LES DOUBLURES ─────────────────────────────────────────────────────────
ETAT = {"cle": "AIza-FAUSSE-CLE-DE-BANC", "reponses": [], "requetes": []}


class _Reponse:
    def __init__(self, statut, json=None, texte=""):
        self.status_code = statut
        self._json = json
        self.text = texte

    def json(self):
        if self._json is None:
            raise ValueError("pas de JSON")
        return self._json


class _Client:
    def __init__(self, timeout=None):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, params=None, json=None):
        ETAT["requetes"].append({"url": url, "params": params, "json": json})
        r = ETAT["reponses"].pop(0) if ETAT["reponses"] else _Reponse(200, {"candidates": [{"content": {"parts": [{"text": "vide"}]}}]})
        if isinstance(r, Exception):
            raise r
        return r


class _HTTPError(Exception):
    pass


mod_httpx = types.ModuleType("httpx")
mod_httpx.AsyncClient = _Client
mod_httpx.HTTPError = _HTTPError
sys.modules["httpx"] = mod_httpx
sys.modules["config"] = types.ModuleType("config")
sys.modules["config"].settings = types.SimpleNamespace(
    model_google_audio="gemini-flash-latest", model_google_vision="gemini-flash-latest",
    model_google_vision_secours="gemini-3.1-flash-lite")
mod_llm = types.ModuleType("llm"); mod_cles = types.ModuleType("llm.cles")
mod_cles.valeur = lambda nom: ETAT["cle"] if nom == "google_api_key" else None
sys.modules["llm"] = mod_llm; sys.modules["llm.cles"] = mod_cles

module = types.ModuleType("transcription")
module.__dict__["__file__"] = str(source)
exec(compile(source.read_text(encoding="utf-8"), str(source), "exec"), module.__dict__)
transcrire = module.transcrire
Indispo = module.TranscriptionIndisponible


def _ok(texte):
    return _Reponse(200, {"candidates": [{"content": {"parts": [{"text": texte}]}}]})


# ── 1. LE CAS NOMINAL ─────────────────────────────────────────────────────
ETAT["reponses"] = [_ok("Bonjour, je voudrais un devis pour une terrasse.")]
ETAT["requetes"].clear()
texte = asyncio.run(transcrire(b"OggS-faux-audio", "audio/webm;codecs=opus"))
verifier("le texte dit est rendu tel quel", texte == "Bonjour, je voudrais un devis pour une terrasse.")
req = ETAT["requetes"][0]
parts = req["json"]["contents"][0]["parts"]
verifier("l'audio part en inlineData, encodé en base64",
         parts[1]["inlineData"]["data"] == base64.b64encode(b"OggS-faux-audio").decode())
verifier("le type MIME est NU (le navigateur envoie « ;codecs=opus »)",
         parts[1]["inlineData"]["mimeType"] == "audio/webm")
verifier("la consigne exige la FIDÉLITÉ, pas un résumé",
         "FIDÈLEMENT" in parts[0]["text"] and "pas de résumé" in parts[0]["text"])
verifier("température zéro : une transcription n'invente pas",
         req["json"]["generationConfig"]["temperature"] == 0.0)
verifier("le modèle audio du réglage est appelé en premier",
         "gemini-flash-latest:generateContent" in req["url"])
verifier("la clé voyage en paramètre, jamais dans le corps",
         req["params"]["key"] == ETAT["cle"] and ETAT["cle"] not in str(req["json"]))

# ── 2. LE TEXTE NU ────────────────────────────────────────────────────────
ETAT["reponses"] = [_ok('« Rappelle le client demain. »')]
verifier("les guillemets posés par le modèle sont retirés",
         asyncio.run(transcrire(b"x", "audio/mp4")) == "Rappelle le client demain.")
ETAT["reponses"] = [_ok("```\nTexte dicté\n```")]
verifier("une clôture de code aussi", asyncio.run(transcrire(b"x", "audio/mp4")) == "Texte dicté")
verifier("un enregistrement vide rend une chaîne vide, sans appel",
         asyncio.run(transcrire(b"", "audio/webm")) == "")

# ── 3. LES REFUS, DITS EN FRANÇAIS, SANS LA CLÉ ───────────────────────────
ETAT["cle"] = ""
try:
    asyncio.run(transcrire(b"x"))
    verifier("sans clé Google, le refus dit où la configurer", False)
except Indispo as e:
    verifier("sans clé Google, le refus dit où la configurer", "Paramètres > Clés API" in str(e))
ETAT["cle"] = "AIza-FAUSSE-CLE-DE-BANC"

ETAT["reponses"] = [_Reponse(429, {"error": {"message": "quota"}})]
try:
    asyncio.run(transcrire(b"x"))
    verifier("un 429 se dit comme un quota, pas comme une panne", False)
except Indispo as e:
    verifier("un 429 se dit comme un quota, pas comme une panne",
             "quota" in str(e).lower() and ETAT["cle"] not in str(e))

ETAT["reponses"] = [_Reponse(503), _ok("Après la surcharge.")]
ETAT["requetes"].clear()
# Les pauses de réessai (3 s, 8 s) ne doivent pas ralentir le banc : le module
# reçoit un `asyncio` doublé dont le sommeil est instantané.
_vrai_sleep = asyncio.sleep
module.asyncio = types.SimpleNamespace(sleep=lambda s: _vrai_sleep(0))
verifier("un 503 est réessayé, et la suite est rendue",
         asyncio.run(transcrire(b"x")) == "Après la surcharge." and len(ETAT["requetes"]) == 2)

ETAT["reponses"] = [_Reponse(404), _ok("Par le secours.")]
ETAT["requetes"].clear()
verifier("un 404 passe au modèle de secours",
         asyncio.run(transcrire(b"x")) == "Par le secours."
         and "gemini-3.1-flash-lite" in ETAT["requetes"][-1]["url"])

try:
    asyncio.run(transcrire(b"x" * (module.MAX_OCTETS + 1)))
    verifier("une dictée trop longue est refusée en le disant (une réunion se colle en texte)", False)
except Indispo as e:
    verifier("une dictée trop longue est refusée en le disant (une réunion se colle en texte)",
             "réunion" in str(e))

# ── 4. LA ROUTE ET L'ÉCRAN ────────────────────────────────────────────────
chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
verifier("la route /api/chat/transcrire existe, authentifiée",
         '@router.post("/transcrire")' in chat and "current_user: User = Depends(get_current_user)" in chat)
verifier("un refus du service devient un 503 lisible, pas un 500 nu",
         "HTTP_503_SERVICE_UNAVAILABLE" in chat and "TranscriptionIndisponible" in chat)
config = (BACKEND / "config.py").read_text(encoding="utf-8")
verifier("le modèle audio est un réglage, même clé que la vision",
         'model_google_audio: str = "gemini-flash-latest"' in config)
dictee = (FRONTEND / "lib" / "dictee.ts").read_text(encoding="utf-8")
verifier("le navigateur ENREGISTRE (MediaRecorder) et n'essaie plus de transcrire lui-même",
         "new (window as any).MediaRecorder" in dictee and "webkitSpeechRecognition" not in dictee)
verifier("il envoie l'enregistrement à l'application",
         "/api/chat/transcrire" in dictee and "audio_b64" in dictee)
verifier("le texte s'écrit AU FUR ET À MESURE : tout depuis le début, à cadence régulière",
         "CADENCE_MS" in dictee and "new Blob(morceaux" in dictee)
verifier("l'ancien message faux a disparu", "Chrome, Edge ou Safari le savent" not in dictee)
barre = (FRONTEND / "components" / "chat" / "InputBar.tsx").read_text(encoding="utf-8")
verifier("la barre passe le jeton de session à la dictée",
         "token={token}" in (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
         and "apiUrl: API_URL," in barre and "token," in barre)
verifier("le champ dit quand il transcrit", "(je transcris)" in barre)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
