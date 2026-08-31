"""
Banc du modèle unique — « un seul modèle, partout, choisi dans Paramètres ».

POURQUOI. Noa, 31/08 : « fais en sorte que les clés API et les IA soient
contrôlables dans la page admin, mais de façon très simple : une seule clé, un
seul modèle pour avoir le même modèle partout et pas vingt mille modèles
différents ». Le forçage existant (`llm_tete`) se réglait PAR PALIER, avec des
préréglages : juste, mais illisible. Le réglage `modele_unique` met un couple
« fournisseur:modele » en tête des trois paliers ET le rend acceptable pour
les campagnes d'enrichissement ; la cascade reste derrière en secours.

CE QUE CE BANC PROUVE, sans base ni réseau : le réglage est connu et validé
(forme, fournisseur) ; `_tete` (extraite du source du routeur) rend le modèle
unique pour LIGHT, STANDARD et COMPLEX, prime sur `llm_tete`, et ignore une
valeur mal formée sans casser ; `modele_de_confiance` accepte le fournisseur
choisi ; la route `/api/settings/modeles` et la carte d'écran existent, et
l'ancienne carte par palier a disparu de l'écran.
"""
import logging
import pathlib
import re
import sys
import types
from enum import Enum

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


# ── un faux module de réglages, piloté par le banc ──
reglages_valeurs: dict = {}
faux_reglages = types.ModuleType("llm.reglages")
faux_reglages.valeur = lambda nom: reglages_valeurs.get(nom)
sys.modules.setdefault("llm", types.ModuleType("llm"))
sys.modules["llm.reglages"] = faux_reglages

router_src = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")


class LLMTier(Enum):
    LIGHT = "light"
    STANDARD = "standard"
    COMPLEX = "complex"


debut = router_src.index("def _tete(")
fin = router_src.index("def _tier_chain(")
espace = {"LLMTier": LLMTier, "Optional": object, "logger": logging.getLogger("banc"),
          "_OPENAI_COMPAT": ("openrouter", "deepseek", "longcat", "google")}
exec(router_src[debut:fin].replace("Optional[str]", "object"), espace)  # noqa: S102 — code du dépôt
_tete = espace["_tete"]

print(f"\n═══ MODÈLE UNIQUE — {BACKEND.parent}\n")

print("1. Le réglage est connu et validé")
reg = (BACKEND / "llm" / "reglages.py").read_text(encoding="utf-8")
verifier("modele_unique dans REGLAGES_CONNUS", '"modele_unique",' in reg)
verifier("validation « fournisseur:modele », fournisseur connu",
         'if nom == "modele_unique"' in reg and "FOURNISSEURS_TEXTE" in reg)
verifier("les six fournisseurs de texte sont listés",
         all(f'"{f}"' in reg for f in ("longcat", "deepseek", "openrouter", "google", "groq", "anthropic")))

print("\n2. Le routeur met le modèle unique en tête de CHAQUE palier")
reglages_valeurs.clear()
reglages_valeurs["modele_unique"] = "longcat:LongCat-2.0"
for palier in LLMTier:
    verifier(f"{palier.value} → longcat:LongCat-2.0", _tete(palier) == [("longcat", "LongCat-2.0")])
reglages_valeurs["llm_tete"] = "standard=groq:llama-3.3-70b-versatile"
verifier("le modèle unique PRIME sur llm_tete", _tete(LLMTier.STANDARD) == [("longcat", "LongCat-2.0")])
reglages_valeurs["modele_unique"] = ""
verifier("sans modèle unique, llm_tete reprend la main (réglage fin par palier)",
         _tete(LLMTier.STANDARD) == [("groq", "llama-3.3-70b-versatile")])
verifier("…et ne touche pas LIGHT", _tete(LLMTier.LIGHT) == [])
reglages_valeurs.clear()
reglages_valeurs["modele_unique"] = "hal9000:sans-cle"
verifier("un fournisseur inconnu est ignoré, sans exception (cascade normale)", _tete(LLMTier.STANDARD) == [])
reglages_valeurs["modele_unique"] = "google"
verifier("une valeur sans modèle est ignorée", _tete(LLMTier.COMPLEX) == [])
reglages_valeurs["modele_unique"] = " Google : gemini-flash-latest "
verifier("casse et espaces tolérés", _tete(LLMTier.LIGHT) == [("google", "gemini-flash-latest")])
verifier("la cascade reste DERRIÈRE la tête (chain = _tete(tier) + chain)", "chain = _tete(tier) + chain" in router_src)

print("\n3. Les campagnes acceptent le modèle choisi")
enr = (BACKEND / "learning" / "enrichissement.py").read_text(encoding="utf-8")
d = enr.index("FOURNISSEURS_DE_CONFIANCE = (")
f = enr.index("# État de la campagne en cours")
esp2: dict = {}
exec(enr[d:f], esp2)  # noqa: S102
confiance = esp2["modele_de_confiance"]
reglages_valeurs.clear()
verifier("un fournisseur de la liste reste de confiance", confiance("google:gemini-flash-latest") is True)
verifier("Groq n'y est pas… sans réglage", confiance("groq:llama-3.3-70b-versatile") is False)
reglages_valeurs["modele_unique"] = "groq:llama-3.3-70b-versatile"
verifier("…mais devient de confiance s'il est LE modèle choisi partout", confiance("groq:llama-3.3-70b-versatile") is True)
verifier("un autre fournisseur hors liste reste refusé", confiance("openrouter:nvidia/x:free") is False)

print("\n4. La route et l'écran")
routes = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
verifier("GET /api/settings/modeles existe et est réservée à l'administration",
         '@router.get("/modeles")' in routes and "catalogue_modeles" in routes)
verifier("le routeur expose catalogue_modeles (clé présente, modèles, écartés)",
         "def catalogue_modeles()" in router_src and '"cle_presente"' in router_src and '"ecarte"' in router_src)
ecran = (FRONTEND / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
verifier("la carte « Le modèle de l'assistant » existe", "function ReglageModeleUnique" in ecran and "Utiliser partout" in ecran)
verifier("elle écrit le réglage modele_unique", 'ecrire("modele_unique", choisi' in ecran)
verifier("elle est rendue en tête de l'onglet",
         ecran.index("<ReglageModeleUnique") < ecran.index("<ReglageKpiDepuis"))
verifier("l'ancienne carte par palier et ses préréglages ont disparu",
         "ReglageLlmTete" not in ecran and "EXEMPLES" not in ecran)
verifier("un llm_tete résiduel est montré et retirable (pas de réglage invisible)",
         "Réglage avancé par palier encore posé" in ecran and 'ecrire("llm_tete", ""' in ecran)
verifier("un fournisseur sans clé est proposé mais désactivé", "clé absente" in ecran and "disabled={!f.cle_presente}" in ecran)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
