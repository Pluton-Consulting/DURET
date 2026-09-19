"""
LE NAVIGATEUR SUR OLLAMA CLOUD, PAR LE RELAIS DU BACKEND (19/09, banc Duret).

Décision de Noa : « utiliser les modèles Ollama Cloud au maximum ». Le navigateur
autonome tournait sur OpenRouter (compte vide le 19/09). Il passe par le relais
`llm/relais_navigateur.py` du guichet interne : pas de clé dans le conteneur, le
modèle et la bride de réflexion de l'assistant, et le JSON rendu propre — Ollama
Cloud n'impose pas le schéma, browser-use lit la réponse strictement.

Le module est chargé tel quel, ses dépendances (configuration, réglages, routeur,
réseau) doublées.
"""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

RACINE = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + ("" if cond else f"  → {detail}"))
    if not cond:
        echecs.append(nom)


reglages = {"modele_rapide": "ollama_cloud:deepseek-v4.1-flash", "modele_puissant": "ollama_cloud:deepseek-v4-pro:0813"}
sys.modules["config"] = types.SimpleNamespace(settings=types.SimpleNamespace(
    model_ollama_cloud_rapide="deepseek-v4-flash:0731", model_ollama_cloud_puissant="deepseek-v4-pro:0813",
    model_ollama_cloud_vision="kimi-k3", model_ollama_cloud_vision_secours="qwen3.5:397b",
    model_ollama_cloud_navigateur="kimi-k3", ollama_cloud_base_url="https://ollama.com/v1"))
llm = types.ModuleType("llm")
llm.__path__ = []
sys.modules["llm"] = llm
sys.modules["llm.reglages"] = types.SimpleNamespace(texte=lambda nom: reglages.get(nom, ""))
sys.modules["llm.router"] = types.SimpleNamespace(
    reflexion_mesuree=lambda f, m, palier="standard", usage="texte": "low" if str(m).startswith("kimi") else ("none" if "deepseek" in str(m) else None),
    _cle=lambda f: "cle-factice")
spec = importlib.util.spec_from_file_location("relais_banc", RACINE / "llm" / "relais_navigateur.py")
rel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rel)

print("═══ RELAIS DU NAVIGATEUR — " + str(RACINE / "llm" / "relais_navigateur.py"))
propre = rel.json_propre('```json\n{"action": [{"click": {"index": 12}}]}\n```')
verifier("une réponse entre clôtures ```json rend son objet", json.loads(propre or "null") == {"action": [{"click": {"index": 12}}]}, propre)
propre = rel.json_propre('Voici ma décision : {"memory": "menu", "action": []} — j\'ouvre le menu.')
verifier("un objet entouré de phrases est extrait", json.loads(propre or "null") == {"memory": "menu", "action": []}, propre)
propre = rel.json_propre('{"memory": "x", "action": [{"click": {"index": 3}}],}')
verifier("une virgule de trop est réparée", (json.loads(propre or "{}") or {}).get("action") == [{"click": {"index": 3}}], propre)
verifier("une réponse sans objet reste telle quelle (None)", rel.json_propre("Page lue, rien à signaler.") is None)

schema_msg = {"role": "system", "content": "Tu pilotes un navigateur.\n<json_schema>\n{...}\n</json_schema>"}
verifier("le schéma posé dans la consigne système par browser-use = JSON attendu",
         rel.attend_du_json({"messages": [schema_msg, {"role": "user", "content": "go"}]}))
verifier("une extraction de texte n'attend pas de JSON",
         not rel.attend_du_json({"messages": [{"role": "system", "content": "Résume la page."}]}))

c = rel.corps_ollama({"messages": [schema_msg], "max_completion_tokens": 999999, "temperature": 0.2}, "kimi-k3")
verifier("le corps envoyé : plafond borné, réflexion bridée, JSON demandé, pas de schéma imposé",
         c["max_tokens"] == rel.MAX_JETONS and c["reasoning_effort"] == "low"
         and c["response_format"] == {"type": "json_object"} and c["temperature"] == 0.2, c)
c = rel.corps_ollama({"messages": [{"role": "user", "content": "OK"}], "max_tokens": 1}, "deepseek-v4.1-flash")
verifier("la sonde d'un jeton passe telle quelle (pas de JSON, réflexion coupée)",
         c["max_tokens"] == 1 and "response_format" not in c and c["reasoning_effort"] == "none", c)

verifier("« navigateur » → le modèle par défaut du navigateur", rel.modele_du_navigateur() == "kimi-k3")
reglages["modele_navigateur"] = "ollama_cloud:deepseek-v4-pro:0813"
verifier("le réglage `modele_navigateur` le remplace", rel.modele_du_navigateur() == "deepseek-v4-pro:0813")
reglages["modele_navigateur"] = "openrouter:gpt-quelconque"
verifier("un réglage hors Ollama Cloud est ignoré", rel.modele_du_navigateur() == "kimi-k3")
del reglages["modele_navigateur"]
permis = rel.modeles_permis()
verifier("les modèles de l'assistant peuvent être demandés par leur nom, pas un autre",
         {"deepseek-v4.1-flash", "kimi-k3", "deepseek-v4-pro:0813"} <= permis and "gpt-5" not in permis, permis)

# ── relayer, réseau doublé ──
envois = []
file_reponses = []


class _Rep:
    def __init__(self, code, donnees):
        self.status_code, self._d, self.text = code, donnees, json.dumps(donnees)

    def json(self):
        return self._d


class _Client:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        envois.append((url, json, headers))
        if file_reponses:
            suivante = file_reponses.pop(0)
            if isinstance(suivante, int):
                return _Rep(suivante, {"error": "surcharge"})
            return _Rep(200, suivante)
        return _Rep(200, {"choices": [{"message": {"role": "assistant",
                                                   "content": '```json\n{"action": [{"navigate": {"url": "https://www.gerflor.fr"}}]}\n```'}}],
                          "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


class _HTTPError(Exception):
    pass


sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=_Client, HTTPError=_HTTPError)


class _HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        super().__init__(detail)
        self.status_code = status_code


sys.modules["fastapi"] = types.SimpleNamespace(HTTPException=_HTTPException)
r = asyncio.run(rel.relayer({"model": "gpt-5", "messages": [schema_msg]}))
verifier("un nom de modèle inconnu → le modèle du navigateur ; la clé posée par le backend",
         envois and envois[-1][1]["model"] == "kimi-k3" and envois[-1][2]["Authorization"] == "Bearer cle-factice"
         and envois[-1][0] == "https://ollama.com/v1/chat/completions", envois[-1][:2] if envois else None)
verifier("la réponse rend le seul objet JSON (clôtures retirées)",
         json.loads(r["choices"][0]["message"]["content"])["action"][0]["navigate"]["url"] == "https://www.gerflor.fr")
asyncio.run(rel.relayer({"model": "deepseek-v4.1-flash", "messages": [schema_msg]}))
verifier("un modèle de l'assistant demandé par son nom est servi", envois[-1][1]["model"] == "deepseek-v4.1-flash")

vide = {"choices": [{"message": {"role": "assistant", "content": ""}}]}
bonne = {"choices": [{"message": {"role": "assistant", "content": '{"action": [{"done": {"text": "ok"}}]}'}}]}
file_reponses[:] = [vide, bonne]
n0 = len(envois)
r = asyncio.run(rel.relayer({"model": "kimi-k3", "messages": [schema_msg]}))
verifier("une réponse VIDE (réflexion qui mange la sortie) se redemande une fois, au relais",
         len(envois) - n0 == 2 and json.loads(r["choices"][0]["message"]["content"])["action"][0]["done"]["text"] == "ok",
         len(envois) - n0)
file_reponses[:] = [{"choices": [{"message": {"role": "assistant", "content": "",
                                              "reasoning": 'Je clique. {"action": [{"click": {"index": 4}}]}'}}]}]
n0 = len(envois)
r = asyncio.run(rel.relayer({"model": "kimi-k3", "messages": [schema_msg]}))
verifier("le JSON rangé dans le champ de réflexion vaut réponse (pas de second appel)",
         len(envois) - n0 == 1 and json.loads(r["choices"][0]["message"]["content"])["action"][0]["click"]["index"] == 4)
file_reponses[:] = [vide, vide]
n0 = len(envois)
asyncio.run(rel.relayer({"model": "kimi-k3", "messages": [schema_msg]}))
verifier("deux réponses vides : on s'arrête là, l'agent décide (pas de boucle)", len(envois) - n0 == 2)

file_reponses[:] = [503, bonne]
n0 = len(envois)
r = asyncio.run(rel.relayer({"model": "kimi-k3", "messages": [schema_msg]}))
verifier("un modèle saturé (503) cède la place au modèle rapide de l'assistant",
         [e[1]["model"] for e in envois[n0:]] == ["kimi-k3", "deepseek-v4.1-flash"], [e[1]["model"] for e in envois[n0:]])
file_reponses[:] = [400]
try:
    asyncio.run(rel.relayer({"model": "kimi-k3", "messages": [schema_msg]}))
    refuse = False
except _HTTPException as e:
    refuse = e.status_code == 400
verifier("une requête refusée (400) ne passe pas au secours : l'erreur remonte", refuse)

# ── le guichet et le conteneur ──
src_g = (RACINE / "routers" / "navigateur_interne.py").read_text(encoding="utf-8")
verifier("la route du relais vit au guichet, derrière le secret (Bearer ou X-Navigateur-Secret)",
         '@router.post("/llm/v1/chat/completions")' in src_g and "_verifier(x_navigateur_secret or jeton)" in src_g)
src_f = (RACINE.parent / "browser-worker" / "llm_factory.py").read_text(encoding="utf-8")
verifier("le conteneur essaie Ollama Cloud en premier, sans clé à lui, schéma dans la consigne",
         '_ORDRE_REPLI = ("ollama_cloud",' in src_f and "add_schema_to_system_prompt=True" in src_f
         and 'secret = _require("BROWSER_WORKER_SECRET")' in src_f)
compose = (RACINE.parent / "docker-compose.yml").read_text(encoding="utf-8")
verifier("par défaut, le navigateur est sur Ollama Cloud", "${BROWSER_LLM_PROVIDER:-ollama_cloud}" in compose)

print("\n" + ("✓ 0 échec" if not echecs else f"✗ {len(echecs)} échec(s)"))
sys.exit(1 if echecs else 0)
