"""
Banc des deux modèles — « un rapide, un puissant, et rien d'autre ».

POURQUOI. Noa, 31/08 : « deux modèles fiables et rapides, un pour répondre vite
et un pour les grosses tâches ; on oublie tous les autres LLM pour l'instant ».
Les réglages `modele_rapide` et `modele_puissant` (« fournisseur:modele »)
remplacent le forçage par palier : dès qu'un des deux est posé, la cascade
habituelle n'est PLUS utilisée — le rapide sert LIGHT et STANDARD, le puissant
COMPLEX et les campagnes, chacun secourt l'autre.

CE QUE CE BANC PROUVE, sans base ni réseau : les deux réglages sont connus et
validés ; `_modeles_choisis` (extraite du routeur) rend l'ordre voulu par palier,
un seul modèle sert partout quand l'autre manque, une valeur mal formée est
ignorée ; `_tier_chain` remplace la cascade par ces modèles (et y revient si
aucun n'a de clé) ; les campagnes leur font confiance ; la route et la carte
d'écran existent, et l'ancienne carte a disparu.
"""
import logging
import pathlib
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


reglages_valeurs: dict = {}
faux_reglages = types.ModuleType("llm.reglages")
faux_reglages.valeur = lambda nom: reglages_valeurs.get(nom)
# 01/09 : les appelants passent par `texte()`, qui garantit une CHAÎNE — tous
# les réglages ne sont pas des chaînes dans la configuration, et `8.strip()`
# a mis « HTTP 500 » dans Paramètres trois fois.
faux_reglages.texte = lambda nom: str(reglages_valeurs.get(nom) or "").strip()
sys.modules.setdefault("llm", types.ModuleType("llm"))
sys.modules["llm.reglages"] = faux_reglages

router_src = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")


class LLMTier(Enum):
    LIGHT = "light"
    STANDARD = "standard"
    COMPLEX = "complex"


debut = router_src.index("def _lire_couple(")
fin = router_src.index("def _tier_chain(")
espace = {"LLMTier": LLMTier, "Optional": object, "logger": logging.getLogger("banc"),
          "_OPENAI_COMPAT": ("openrouter", "deepseek", "longcat", "google")}
exec(router_src[debut:fin].replace("Optional[tuple[str, str]]", "object"), espace)  # noqa: S102
_modeles_choisis = espace["_modeles_choisis"]

print(f"\n═══ DEUX MODÈLES — {BACKEND.parent}\n")

print("1. Les réglages sont connus et validés")
reg = (BACKEND / "llm" / "reglages.py").read_text(encoding="utf-8")
verifier("modele_rapide et modele_puissant dans REGLAGES_CONNUS", '"modele_rapide",' in reg and '"modele_puissant",' in reg)
verifier("modele_unique a disparu", "modele_unique" not in reg)
verifier("validation « fournisseur:modele », pour les QUATRE réglages de modèle",
         'if nom in ("modele_rapide", "modele_puissant",' in reg
         and '"modele_vision", "modele_embedding")' in reg)

print("\n2. L'ordre par palier")
reglages_valeurs.clear()
reglages_valeurs.update({"modele_rapide": "openrouter:google/gemini-2.5-flash",
                         "modele_puissant": "openrouter:anthropic/claude-sonnet-4.5"})
R = ("openrouter", "google/gemini-2.5-flash")
P = ("openrouter", "anthropic/claude-sonnet-4.5")
verifier("LIGHT : rapide puis puissant", _modeles_choisis(LLMTier.LIGHT) == [R, P])
verifier("STANDARD : rapide puis puissant", _modeles_choisis(LLMTier.STANDARD) == [R, P])
verifier("COMPLEX : puissant puis rapide", _modeles_choisis(LLMTier.COMPLEX) == [P, R])
reglages_valeurs["modele_puissant"] = ""
verifier("un seul choisi : il sert partout, seul", _modeles_choisis(LLMTier.COMPLEX) == [R])
reglages_valeurs["modele_puissant"] = "openrouter:google/gemini-2.5-flash"
verifier("les deux identiques : une seule entrée (pas de double essai du même modèle)",
         _modeles_choisis(LLMTier.STANDARD) == [R])
reglages_valeurs.clear()
verifier("rien de choisi : liste vide (cascade habituelle)", _modeles_choisis(LLMTier.STANDARD) == [])
reglages_valeurs["modele_rapide"] = "hal9000:x"
verifier("fournisseur inconnu : ignoré sans exception", _modeles_choisis(LLMTier.STANDARD) == [])
reglages_valeurs["modele_rapide"] = " OpenRouter : deepseek/deepseek-v4-flash "
verifier("casse et espaces tolérés", _modeles_choisis(LLMTier.LIGHT) == [("openrouter", "deepseek/deepseek-v4-flash")])

print("\n3. La cascade est REMPLACÉE, pas préfixée")
verifier("_tier_chain : chain = choisis quand ils ont une clé", "        chain = choisis\n" in router_src)
verifier("…et retombe sur la cascade (llm_tete compris) sinon, en le disant",
         "Modèles choisis sans clé disponible" in router_src and "chain = _tete(tier) + chain" in router_src)
verifier("_tete ne connaît plus modele_unique", "modele_unique" not in router_src)

print("\n4. Les campagnes font confiance aux modèles choisis")
enr = (BACKEND / "learning" / "enrichissement.py").read_text(encoding="utf-8")
d = enr.index("FOURNISSEURS_DE_CONFIANCE = (")
f = enr.index("# État de la campagne en cours")
esp2: dict = {}
exec(enr[d:f], esp2)  # noqa: S102
confiance = esp2["modele_de_confiance"]
reglages_valeurs.clear()
verifier("Groq hors liste sans réglage", confiance("groq:llama-3.3-70b-versatile") is False)
reglages_valeurs["modele_puissant"] = "groq:llama-3.3-70b-versatile"
verifier("…de confiance s'il est le modèle puissant choisi", confiance("groq:llama-3.3-70b-versatile") is True)
reglages_valeurs.clear()
reglages_valeurs["modele_rapide"] = "openrouter:x/y"
verifier("…ou le modèle rapide choisi", confiance("openrouter:x/y") is True)
verifier("la liste historique reste valable", confiance("google:gemini-flash-latest") is True)

print("\n5. La route et l'écran")
routes = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
verifier("GET /api/settings/modeles rend les deux choix",
         '"modele_rapide"' in routes and '"modele_puissant"' in routes and "catalogue_modeles" in routes)
ecran = (FRONTEND / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
# 01/09 : QUATRE lignes désormais — rapide, puissant, vision/OCR, embeddings.
# Relevé de Noa : « je vois pas le choix des modèles pour embedding ou image ou
# OCR ». La génération d'images, elle, s'affiche mais ne se choisit pas.
verifier("la carte porte les QUATRE lignes réglables",
         "function ReglageModeles" in ecran and ecran.count("<LigneModele") == 4)
verifier("vision et embeddings sont bien deux d'entre elles",
         'ecrire("modele_vision", v' in ecran and 'ecrire("modele_embedding", v' in ecran)
verifier("la génération d'images se MONTRE sans se choisir",
         "Génération d&apos;images" in ecran and 'ecrire("modele_image"' not in ecran)
verifier("et le coût d'un changement d'embedding est dit AVANT le clic",
         "re-vectoriser tout le corpus" in ecran)
verifier("elle écrit modele_rapide et modele_puissant",
         'ecrire("modele_rapide", v' in ecran and 'ecrire("modele_puissant", v' in ecran)
verifier("elle dit que la cascade n'est plus utilisée", "deux modèles seulement" in ecran)
verifier("rendue en tête de l'onglet", ecran.index("<ReglageModeles") < ecran.index("<ReglageKpiDepuis"))
verifier("plus de carte unique ni de forçage par palier à l'écran",
         "ReglageModeleUnique" not in ecran and "ReglageLlmTete" not in ecran and "modele_unique" not in ecran)
verifier("un llm_tete résiduel reste visible et retirable", 'ecrire("llm_tete", ""' in ecran)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
