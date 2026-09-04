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
module.asyncio = types.SimpleNamespace(sleep=lambda s: _vrai_sleep(0), to_thread=asyncio.to_thread)
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
         "/api/chat/transcrire" in dictee and "chunk_b64" in dictee)
verifier("le texte s'écrit AU FUR ET À MESURE : tout depuis le début, à cadence régulière",
         "CADENCE_MS" in dictee and "new Blob(morceaux" in dictee)
verifier("l'ancien message faux a disparu", "Chrome, Edge ou Safari le savent" not in dictee)
barre = (FRONTEND / "components" / "chat" / "InputBar.tsx").read_text(encoding="utf-8")
verifier("la barre passe le jeton de session à la dictée",
         "token={token}" in (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
         and "apiUrl: API_URL," in barre and "token," in barre)
verifier("le champ dit quand il transcrit", "(je transcris)" in barre)


# ── 5. SANS JETON D'IA : WHISPER LOCAL, ET SON CACHE INCRÉMENTAL ──────────
# Noa : « il n'y a pas une solution pour retranscrire sans token IA ? ». Si :
# faster-whisper sur le CPU du conteneur. Le banc double la bibliothèque et
# vérifie ce qui compte — qu'un enregistrement qui GRANDIT n'est transcrit
# que pour sa partie neuve, avec un recouvrement, et que Google ne sert plus
# que de secours.
APPELS = []

class _Segment:
    def __init__(self, t): self.text = t

class _Whisper:
    def __init__(self, nom, device=None, compute_type=None, download_root=None, **kw):
        ETAT["whisper_kw"] = kw
        ETAT["whisper_nom"] = nom; ETAT["whisper_root"] = download_root
    def transcribe(self, audio, **kw):
        APPELS.append({"n": len(audio), "amorce": kw.get("initial_prompt")})
        # Le texte « entendu » dépend de la LONGUEUR : 16 000 échantillons = 1 s = un mot.
        secondes = len(audio) // 16000
        return ([_Segment(" ".join(f"mot{i}" for i in range(secondes)))], None)

mod_fw = types.ModuleType("faster_whisper"); mod_fw.WhisperModel = _Whisper
mod_fw_audio = types.ModuleType("faster_whisper.audio")
# Chaque octet = un centième de seconde : 100 octets → 1 s → 16 000 échantillons.
mod_fw_audio.decode_audio = lambda f, sampling_rate=16000: [0.0] * (len(f.getvalue()) * 160)
sys.modules["faster_whisper"] = mod_fw; sys.modules["faster_whisper.audio"] = mod_fw_audio
sys.modules["config"].settings.transcription_moteur = "local"
sys.modules["config"].settings.whisper_modele = "small"
module._LOCAL_INDISPONIBLE = None
module._MODELE = None
module._CACHE.clear()

verifier("Whisper local est le moteur par défaut dès qu'il est installé",
         module.moteur_choisi() == "local")
ETAT["requetes"].clear()
t1 = asyncio.run(transcrire(b"a" * 300, "audio/webm", cle_cache="noa"))     # 3 s
verifier("une dictée de 3 s donne 3 mots, sans AUCUN appel Google",
         t1 == "mot0 mot1 mot2" and not ETAT["requetes"], t1)
verifier("le modèle demandé est celui du réglage, rangé dans le volume des documents",
         ETAT["whisper_nom"] == "small" and ETAT["whisper_root"].endswith("modeles"))
t2 = asyncio.run(transcrire(b"a" * 600, "audio/webm", cle_cache="noa"))     # 6 s, même début
verifier("L'ENREGISTREMENT QUI GRANDIT N'EST TRANSCRIT QUE POUR SA PARTIE NEUVE (+1 s de recouvrement)",
         APPELS[-1]["n"] == 4 * 16000, str(APPELS[-1]))
verifier("le texte d'avant sert d'amorce à la suite", APPELS[-1]["amorce"] == "mot0 mot1 mot2")
# Le modèle doublé nomme les mots par leur rang depuis le début de CE qu'on
# lui donne : la fin relue (4 s) rend « mot0 mot1 mot2 mot3 », dont les trois
# premiers sont le recouvrement déjà connu — ils ne doivent pas être répétés.
verifier("le texte rendu est recollé sans répéter le recouvrement",
         t2 == "mot0 mot1 mot2 mot3", t2)
t3 = asyncio.run(transcrire(b"b" * 600, "audio/webm", cle_cache="noa"))     # un AUTRE début
verifier("un autre enregistrement (autre début) repart de zéro", APPELS[-1]["n"] == 6 * 16000)
verifier("« _recoller » retire les mots relus dans le recouvrement",
         module._recoller("bonjour je voudrais un devis", "un devis pour une terrasse")
         == "bonjour je voudrais un devis pour une terrasse")
sys.modules["config"].settings.transcription_moteur = "google"
verifier("le réglage « google » force le secours", module.moteur_choisi() == "google")
sys.modules["config"].settings.transcription_moteur = "local"
module._LOCAL_INDISPONIBLE = "faster-whisper absent"
verifier("sans faster-whisper installé, Google prend le relais", module.moteur_choisi() == "google")
module._LOCAL_INDISPONIBLE = None
requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
verifier("faster-whisper est dans l'image", "faster-whisper" in requirements)
verifier("le modèle est téléchargé AU BUILD, et un échec de téléchargement ne casse pas l'image",
         "WhisperModel('" in dockerfile and "|| echo" in dockerfile)
verifier("la route donne la clé du cache (qui dicte)", "cle_cache=str(current_user.id)" in chat)


# ── 6. « BEAUCOUP TROP LENT » (03/09, sur la version déployée) ─────────────
src = source.read_text(encoding="utf-8")
verifier("le modèle par défaut est `base` (trois fois plus rapide que `small` sur un CPU)",
         'whisper_modele: str = "base"' in config and 'getattr(settings, "whisper_modele", "base")' in src)
verifier("décodage glouton (beam_size=1) : deux fois plus rapide pour une dictée qu'on relit",
         "beam_size=1" in src and "beam_size=2" not in src)
verifier("tous les cœurs du conteneur travaillent (cpu_threads transmis au modèle)",
         "cpu_threads=max(2, os.cpu_count() or 2)" in src and ETAT.get("whisper_kw", {}).get("cpu_threads", 0) >= 2)
verifier("le modèle est PRÉCHARGÉ au démarrage du backend (la première dictée n'attend pas)",
         "async def prechauffer" in src
         and "asyncio.create_task(prechauffer())" in (BACKEND / "main.py").read_text(encoding="utf-8"))
verifier("l'image télécharge `base` au build", "WhisperModel('base'" in dockerfile)


# ── 7. LE FLUX : « le voir s'écrire en direct » (04/09) ───────────────────
# Le navigateur n'envoie que le NOUVEAU son ; le serveur l'ajoute au tampon de
# la dictée et ne transcrit que la fin. Exécuté contre le Whisper doublé.
sys.modules["config"].settings.transcription_moteur = "local"
module._LOCAL_INDISPONIBLE = None
module._CACHE.clear(); module._TAMPONS.clear(); APPELS.clear()
f1 = asyncio.run(module.transcrire_flux("noa:d1", b"a" * 200))          # 2 s
f2 = asyncio.run(module.transcrire_flux("noa:d1", b"a" * 200))          # +2 s → 4 s au tampon
verifier("chaque morceau s'AJOUTE au tampon de la dictée (le texte s'allonge)",
         f1 == "mot0 mot1" and f2 == "mot0 mot1 mot2", f"{f1!r} / {f2!r}")
verifier("seule la fin est transcrite (2 s neuves + 1 s de recouvrement)",
         APPELS[-1]["n"] == 3 * 16000, str(APPELS[-1]))
f3 = asyncio.run(module.transcrire_flux("noa:d1", b"a" * 100, definitif=True))
verifier("le dernier morceau rend le texte entier et FERME la dictée (tampon et cache oubliés)",
         f3.count("mot") == 5 and "noa:d1" not in module._TAMPONS and "noa:d1" not in module._CACHE)
verifier("deux dictées (deux onglets) ne se mélangent pas",
         asyncio.run(module.transcrire_flux("noa:d2", b"b" * 100)) == "mot0")
chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
verifier("la route accepte le morceau et la session, et ferme sur `definitif`",
         "chunk_b64: Optional[str] = None" in chat and "transcrire_flux(cle, octets" in chat
         and "definitif=body.definitif" in chat)
verifier("la clé du tampon porte la personne ET la dictée",
         'f"{current_user.id}:{body.session[:40]}"' in chat)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
