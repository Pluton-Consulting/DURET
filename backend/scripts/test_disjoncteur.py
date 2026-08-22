"""
Banc du disjoncteur de cascade — sur le VRAI module, pas sur une copie.

`llm/router.py` n'importe au niveau module que `config` et `optim.tokens` ; les
dépendances lourdes (langchain) sont importées à l'intérieur de `_build_model`.
On peut donc charger le module réel en remplaçant ces deux-là par des doublures,
et exercer le disjoncteur avec les erreurs EXACTES relevées dans Langfuse.
"""
import sys, types, time, pathlib

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
sys.path.insert(0, BACKEND)

# ── Doublures : une configuration permissive, un compteur de jetons neutre ──
faux_config = types.ModuleType("config")


class _Reglages:
    """Une configuration complète et RÉALISTE.

    Deux pièges appris en écrivant ce banc : rendre le même nom de modèle
    partout fait dédoublonner la cascade jusqu'à un seul candidat, et
    `llm_fallback_enabled` faux la tronque au premier. Une doublure qui ment
    sur ces deux points teste un routeur qui n'existe pas.
    """

    def __getattr__(self, nom):
        if nom.endswith("_api_key"):
            return "sk-doublure"          # tous les fournisseurs sont configurés
        if nom == "llm_fallback_enabled":
            return True                   # sinon la cascade est tronquée au premier
        if nom == "llm_max_retries":
            return 1
        if nom == "llm_retry_base_delay":
            return 0.0
        if nom.startswith("model_") or nom.startswith("ollama_"):
            return f"m-{nom}"             # un nom DISTINCT par réglage : pas de dédoublonnage
        if nom == "llm_tete":
            return ""
        return ""


faux_config.settings = _Reglages()
sys.modules["config"] = faux_config

faux_optim = types.ModuleType("optim.tokens")
faux_optim.tier_max_tokens = lambda t: 2048
paquet = types.ModuleType("optim")
paquet.tokens = faux_optim
sys.modules["optim"] = paquet
sys.modules["optim.tokens"] = faux_optim

from llm import router  # noqa: E402  — après les doublures, à dessein

echecs = []


def verifier(nom, condition, detail=""):
    print(f"  {'✓' if condition else '✗'} {nom}" + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        echecs.append(nom)


print(f"\n═══ DISJONCTEUR DE CASCADE — {BACKEND}\n")

# ── 1. Les erreurs réelles de production sont bien reconnues ───────────────
print("1. Reconnaissance des pannes relevées dans Langfuse le 21/08")
CAS = [
    ("Error code: 401 - {'error': {'message': 'User not found.', 'code': 401}}", "clé refusée", 1800),
    ("Error code: 404 - {'error': {'message': 'The model `llama-3.3-70b-versatile` does not exist'}}",
     "modèle inconnu de cette clé", 1800),
    ("Error code: 429 - rate limit exceeded", "quota épuisé", 300),
    ("All connection attempts failed", None, 0),          # réseau : ponctuel
    ("Read timeout after 60s", None, 0),                  # lenteur : ponctuel
]
for message, raison_attendue, duree_attendue in CAS:
    motif = router._motif_quarantaine(RuntimeError(message))
    if raison_attendue is None:
        verifier(f"« {message[:44]}… » n'écarte PAS", motif is None, f"a rendu {motif}")
    else:
        verifier(f"« {message[:44]}… » → {raison_attendue}",
                 motif is not None and motif[1] == raison_attendue and motif[0] == duree_attendue,
                 f"a rendu {motif}")

# ── 2. Un candidat écarté disparaît de la cascade ──────────────────────────
print("\n2. Mise à l'écart et filtrage")
router._QUARANTAINE.clear()
chaine = router._tier_chain(router.LLMTier.STANDARD)
verifier("la cascade STANDARD n'est pas vide", len(chaine) > 1, f"{len(chaine)} candidats")
premier = chaine[0]
router._ecarter(premier[0], premier[1], RuntimeError("Error code: 401 - User not found."))
filtree = router._filtrer_quarantaine(chaine)
verifier("le candidat mort a disparu", premier not in filtree)
verifier("les autres sont conservés", len(filtree) == len(chaine) - 1,
         f"{len(filtree)} au lieu de {len(chaine) - 1}")
verifier("la raison est lisible", router._ecarte(*premier) == "clé refusée",
         router._ecarte(*premier))

# ── 3. On n'écarte JAMAIS tout le monde ───────────────────────────────────
print("\n3. Garde-fou : une cascade entièrement morte reste tentée")
for p, m in chaine:
    router._ecarter(p, m, RuntimeError("Error code: 401 - User not found."))
filtree = router._filtrer_quarantaine(chaine)
verifier("tout écarter revient à n'écarter personne", filtree == chaine,
         f"{len(filtree)} candidats")

# ── 4. La quarantaine EXPIRE — une clé rechargée revient seule ────────────
print("\n4. Expiration")
router._QUARANTAINE.clear()
p, m = chaine[0]
router._QUARANTAINE[(p, m)] = (time.monotonic() - 1.0, "clé refusée")   # déjà périmée
verifier("un écart périmé ne compte plus", router._ecarte(p, m) is None)
verifier("le candidat est de nouveau dans la cascade",
         chaine[0] in router._filtrer_quarantaine(chaine))

# ── 5. Le gain réel : combien d'appels morts évités ───────────────────────
print("\n5. Gain mesuré sur la panne du 21/08")
router._QUARANTAINE.clear()
MORTS = {"deepseek", "groq", "ollama", "openrouter"}      # ce qui échouait en production
chaine = router._tier_chain(router.LLMTier.STANDARD)
avant = sum(1 for p, _ in chaine if p in MORTS)
for p, m in chaine:
    if p in MORTS:
        router._ecarter(p, m, RuntimeError("Error code: 401 - User not found."))
apres = sum(1 for p, _ in router._filtrer_quarantaine(chaine) if p in MORTS)
verifier("les candidats morts ne sont plus essayés", apres == 0, f"{apres} restent")
print(f"     → {avant} appels voués à l'échec par appel LLM, désormais évités.")
print(f"     → sur un tour de 15 appels : {avant * 15} allers-retours en moins.")

# ── 6. L'état est lisible pour l'écran Paramètres ─────────────────────────
print("\n6. Rapport de santé")
sante = router.sante_cascade()
verifier("la santé couvre les trois paliers",
         {l["palier"] for l in sante} == {"light", "standard", "complex"},
         str({l["palier"] for l in sante}))
ecartes = [l for l in sante if l["ecarte"]]
verifier("les candidats écartés y figurent avec leur raison",
         bool(ecartes) and all(l["raison"] for l in ecartes))
verifier("le délai de reprise est renseigné", all(l["reprise_dans_s"] > 0 for l in ecartes))

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
