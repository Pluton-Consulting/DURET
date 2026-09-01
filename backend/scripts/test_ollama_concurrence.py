"""
Banc « Ollama Cloud et les appels simultanés » — 01/09.

Noa vient de prendre un abonnement Ollama Cloud et veut y faire passer les
modèles (rapide, puissant, OCR), saisir la clé depuis l'écran d'administration,
et LIMITER le nombre d'appels simultanés — l'abonnement en autorise dix.

Ce banc prouve : le fournisseur `ollama_cloud` est distinct du `ollama` LOCAL
(le piège du chantier), il est déclaré partout où le système l'exige (clés,
cascades, vision, catalogue de l'écran, réglages, campagnes), et la porte de
concurrence — EXÉCUTÉE ici — sérialise réellement les appels, relâche ses
créneaux même sur annulation, et n'attend jamais sans fin.
"""
import ast
import asyncio
import importlib.util
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.resolve().parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ OLLAMA CLOUD ET CONCURRENCE — {BACKEND.resolve().parent}\n")

# ── 1. Le fournisseur, et le piège du nom ────────────────────────────────
config = (BACKEND / "config.py").read_text(encoding="utf-8")
verifier("config : clé, URL et quatre modèles Ollama Cloud",
         all(x in config for x in ("ollama_cloud_api_key", 'ollama_cloud_base_url: str = "https://ollama.com/v1"',
                                   "model_ollama_cloud_rapide", "model_ollama_cloud_puissant",
                                   "model_ollama_cloud_vision", "model_ollama_cloud_vision_secours")))
verifier("les identifiants n'ont PAS le suffixe « :cloud » (il rend 404 sur cette API)",
         ":cloud\"" not in config)
verifier("l'Ollama LOCAL est intact (dernier recours hors ligne)",
         'ollama_base_url: str = "http://localhost:11434"' in config
         and 'ollama_model_light: str = "mistral:7b"' in config)

routeur = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")
verifier("le cloud passe par la voie compatible OpenAI (donc une clé obligatoire)",
         '_OPENAI_COMPAT = ("ollama_cloud"' in routeur)
verifier("les deux fournisseurs restent DISTINCTS : le local garde ChatOllama",
         'if provider == "ollama":' in routeur and "ChatOllama" in routeur)
verifier("le commentaire explique pourquoi les confondre serait une erreur",
         "N'EST PAS `ollama`" in routeur)
verifier("Ollama Cloud est en tête des TROIS paliers",
         routeur.count('("ollama_cloud", s.model_ollama_cloud_rapide)') == 2
         and routeur.count('("ollama_cloud", s.model_ollama_cloud_puissant)') == 1)
verifier("la vision le propose, DERRIÈRE le modèle d'OCR mesuré",
         re.search(r'"openrouter", s\.model_openrouter_vision\).*?'
                   r'"ollama_cloud", s\.model_ollama_cloud_vision\)', routeur, re.S))
verifier("le catalogue de l'écran le montre en premier",
         '("ollama_cloud", "Ollama Cloud"' in routeur)

cles = (BACKEND / "llm" / "cles.py").read_text(encoding="utf-8")
verifier("la clé est connue du gestionnaire (base > .env)", '"ollama_cloud_api_key"' in cles)
reglages = (BACKEND / "llm" / "reglages.py").read_text(encoding="utf-8")
verifier("le fournisseur est acceptable dans « les modèles de l'assistant » (sinon 422)",
         '"ollama_cloud"' in reglages.split("FOURNISSEURS_TEXTE")[1][:200])
enrich = (BACKEND / "learning" / "enrichissement.py").read_text(encoding="utf-8")
verifier("les campagnes lui font confiance (sinon un repli est refusé d'écrire)",
         '"ollama_cloud"' in enrich.split("FOURNISSEURS_DE_CONFIANCE")[1][:200])

# ── 2. La porte, EXÉCUTÉE ────────────────────────────────────────────────
faux_config = types.ModuleType("config")
faux_config.settings = types.SimpleNamespace(
    llm_simultanes=2, llm_simultanes_personne=1, llm_simultanes_fond=2, llm_attente_max_s=1)
sys.modules["config"] = faux_config
faux_reglages = types.ModuleType("llm.reglages")
faux_reglages.valeur = lambda nom: ""
paquet = types.ModuleType("llm"); paquet.__path__ = []
sys.modules.setdefault("llm", paquet)
sys.modules["llm.reglages"] = faux_reglages

spec = importlib.util.spec_from_file_location("conc", BACKEND / "llm" / "concurrence.py")
conc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conc)


async def _scenario_serialisation():
    """Deux appels d'une même personne (plafond 1) ne se chevauchent jamais."""
    conc.porter("user:test", 1)
    ensemble, maxi = [0], [0]

    async def appel():
        async with conc.porte_llm():
            ensemble[0] += 1
            maxi[0] = max(maxi[0], ensemble[0])
            await asyncio.sleep(0.05)
            ensemble[0] -= 1

    await asyncio.gather(*(appel() for _ in range(4)))
    return maxi[0], ensemble[0]


maxi, restant = asyncio.run(_scenario_serialisation())
verifier("plafond personnel de 1 : jamais deux appels de front", maxi == 1, f"observé {maxi}")
verifier("tous les créneaux sont relâchés à la fin", restant == 0)


async def _scenario_global():
    """Le plafond global s'applique même à des personnes différentes."""
    ensemble, maxi = [0], [0]

    async def appel(i):
        conc.porter(f"user:{i}", 5)          # personnel large : c'est le global qui borne
        async with conc.porte_llm():
            ensemble[0] += 1
            maxi[0] = max(maxi[0], ensemble[0])
            await asyncio.sleep(0.05)
            ensemble[0] -= 1

    await asyncio.gather(*(appel(i) for i in range(6)))
    return maxi[0]


verifier("plafond global de 2 : jamais plus de deux appels de front, tous comptes confondus",
         asyncio.run(_scenario_global()) <= 2)


async def _scenario_attente():
    """Passé le délai, on renonce — on n'attend JAMAIS sans fin."""
    conc.porter("user:lent", 1)
    ouvert = asyncio.Event()

    async def tenir():
        async with conc.porte_llm():
            ouvert.set()
            await asyncio.sleep(5)           # bien au-delà de llm_attente_max_s = 1

    tache = asyncio.create_task(tenir())
    await ouvert.wait()
    try:
        async with conc.porte_llm():
            resultat = "passé"
    except conc.TropDeDemandes as e:
        resultat = str(e)
    tache.cancel()
    try:
        await tache
    except asyncio.CancelledError:
        pass
    return resultat


r = asyncio.run(_scenario_attente())
verifier("saturé : on renonce après le délai, avec une raison lisible",
         "TropDeDemandes" not in r and "simultanés" in r, r[:80])


async def _scenario_annulation():
    """Une tâche annulée en attente ne fuit pas son créneau."""
    conc.porter("user:annule", 1)
    ouvert = asyncio.Event()

    async def tenir():
        async with conc.porte_llm():
            ouvert.set()
            await asyncio.sleep(0.3)

    t1 = asyncio.create_task(tenir())
    await ouvert.wait()
    t2 = asyncio.create_task(tenir())
    await asyncio.sleep(0.05)
    t2.cancel()
    try:
        await t2
    except asyncio.CancelledError:
        pass
    await t1
    # Si le créneau avait fui, celui-ci n'aboutirait jamais.
    try:
        await asyncio.wait_for(tenir(), timeout=2)
        return True
    except asyncio.TimeoutError:
        return False


verifier("une attente annulée ne fuit pas de créneau", asyncio.run(_scenario_annulation()))

etat = conc.etat()
verifier("l'état se lit pour l'écran d'administration",
         etat["plafond_global"] == 2 and "attente_max_s" in etat)

# ── 3. Le branchement : les trois points d'appel de modèle ───────────────
verifier("la porte entoure l'appel de la cascade, PAS la cascade elle-même",
         re.search(r"async with porte_llm\(\):\s*\n\s*result = await llm\.ainvoke\(messages",
                   routeur))
verifier("le backoff reste HORS de la porte",
         routeur.index("await asyncio.sleep(delay)") > routeur.index("async with porte_llm()"))
a2 = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
pieces = (BACKEND / "mail" / "pieces.py").read_text(encoding="utf-8")
verifier("les deux appels de vision hors cascade sont gardés aussi",
         "async with porte_llm():" in a2 and "async with porte_llm():" in pieces)
runtime = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
verifier("le tour déclare QUI consomme, avant d'entrer dans le graphe",
         runtime.count("porter(f\"user:{user_id}\"") == 2)
verifier("les tâches de fond ont leur propre budget",
         'porter("fond:taches"' in (BACKEND / "tasks" / "worker.py").read_text(encoding="utf-8")
         and 'porter("fond:enrichissement"' in enrich)

# ── 4. Le réglage : migration, routes, écran ─────────────────────────────
mig = BACKEND / "database" / "migrations" / "029_concurrence_llm.sql"
verifier("migration 029 : plafond par rôle et par compte, idempotente",
         mig.exists() and "ADD COLUMN IF NOT EXISTS concurrent_limit" in mig.read_text(encoding="utf-8")
         and "ADD COLUMN IF NOT EXISTS llm_simultanes" in mig.read_text(encoding="utf-8"))
settings_py = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
verifier("routes de lecture et d'écriture, réservées à l'administration système",
         '@router.get("/concurrence")' in settings_py and '@router.put("/concurrence")' in settings_py
         # Les deux routes vérifient le droit — cherché dans le corps de chacune,
         # pas dans une fenêtre de caractères (le docstring en fait davantage).
         and all("manage_system" in settings_py.split(m)[1].split("@router")[0]
                 for m in ('@router.get("/concurrence")', '@router.put("/concurrence")')))
verifier("un plafond de zéro est refusé (il empêcherait de travailler)",
         "1 <= n <= 64" in settings_py)
cles_tsx = (FRONTEND / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
verifier("l'écran propose la clé Ollama Cloud", "ollama_cloud_api_key:" in cles_tsx)
# 01/09 soir : ce contrôle a été RESSERRÉ, sur décision de Noa — « ce paramètre
# concerne l'ensemble des comptes cumulés ». Les tableaux par rôle et par compte
# ont disparu de l'écran, et avec eux la seule dépendance de cette carte à
# l'état des migrations. Le plafond par personne reste un garde INTERNE, dont la
# valeur vient du code.
verifier("l'écran règle UN plafond, tous comptes confondus",
         "ReglageConcurrence" in cles_tsx
         and "Tous comptes confondus" in cles_tsx
         and "par_utilisateur" not in cles_tsx)
verifier("le garde par personne existe toujours, hors de l'écran",
         "llm_simultanes_personne" in (BACKEND / "config.py").read_text(encoding="utf-8"))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
