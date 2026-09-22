"""
Banc de LA SATURATION DU FOURNISSEUR (22/09, Duret : le quantitatif de Maxime, six essais échoués).

Ollama Cloud répondait « Error code: 429 - {'error': 'too many concurrent requests'} ». Le
routeur lisait « 429 » : quota épuisé → cinq minutes de quarantaine pour le modèle puissant,
puis pour le rapide, 39 refus en une seconde, et « Tous les modèles LLM ont échoué ». Le
plafond commun d'appels (8) croyait le compte capable de dix : sa limite réelle est plus basse.

CE QUE CE BANC PROUVE (le VRAI `ResilientLLM.ainvoke` de llm/router.py et la VRAIE porte de
llm/concurrence.py EXÉCUTÉS ; seuls la liste des candidats et le fournisseur sont doublés) :
  · un refus de concurrence n'est PAS une quarantaine : le MÊME modèle est retenté après une
    attente, et l'appel réussit sans passer au suivant ;
  · le plafond commun descend au nombre d'appels que le fournisseur acceptait, puis remonte
    au bout de sa durée ;
  · un vrai 429 de quota garde sa quarantaine et le passage au candidat suivant ;
  · un fournisseur saturé sans fin finit par rendre la main (attentes bornées).
Tombe sur la version d'avant (le refus de concurrence met le modèle en quarantaine).

Usage : python backend/scripts/test_saturation_fournisseur.py [backend]
"""
import asyncio
import os
import pathlib
import sys
import time

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
for cle, valeur in (("DATABASE_URL", "postgresql://banc:banc@localhost/banc"),
                    ("JWT_SECRET_KEY", "banc"), ("RESEND_API_KEY", "banc")):
    os.environ.setdefault(cle, valeur)
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


try:
    from llm import router as R
    from llm import concurrence as C
except Exception as e:  # noqa: BLE001
    print(f"llm/router.py ne s'importe pas ici ({e}) : banc non jouable hors du conteneur.")
    sys.exit(0)

if not hasattr(C, "signaler_saturation") or not hasattr(R, "refus_de_concurrence"):
    verifier("le routeur reconnaît le refus de concurrence et la porte apprend le plafond", False, "absents")
    print(f"\n✗ {len(echecs)} échec(s)")
    sys.exit(1)

REFUS_CONCURRENCE = RuntimeError("Error code: 429 - {'error': 'too many concurrent requests'}")
REFUS_QUOTA = RuntimeError("Error code: 429 - {'error': 'rate limit exceeded, quota'}")
appels = []
SCENARIO = {}
ATTENTES = []


class _Reponse:
    def __init__(self, texte):
        self.content = texte
        self.response_metadata = {}
        self.usage_metadata = {}


class _Faux:
    def __init__(self, nom):
        self.nom = nom

    async def ainvoke(self, messages, **options):
        appels.append(self.nom)
        refus = SCENARIO.get(self.nom, [])
        if refus:
            raise refus.pop(0)
        return _Reponse(f"réponse de {self.nom}")


R._tier_chain = lambda tier: [("ollama_cloud", "puissant"), ("ollama_cloud", "rapide")]
R._build_model = lambda provider, model, *a, **k: _Faux(model)
R._QUARANTAINE.clear()
_sommeil = asyncio.sleep


async def _sans_attendre(s, *a, **k):
    ATTENTES.append(s)
    await _sommeil(0)


R.asyncio.sleep = _sans_attendre           # le banc ne dort pas ; il compte les attentes

print("1. Un refus de concurrence se retente sur le même modèle")
SCENARIO["puissant"] = [REFUS_CONCURRENCE, REFUS_CONCURRENCE]
C._EN_VOL[0] = 3
resultat = asyncio.run(R.ResilientLLM(R.LLMTier.COMPLEX).ainvoke([]))
verifier("l'appel réussit, sur le MÊME modèle", getattr(resultat, "content", "") == "réponse de puissant",
         getattr(resultat, "content", resultat))
verifier("aucun passage au modèle suivant", "rapide" not in appels, appels)
verifier("deux attentes, croissantes", len(ATTENTES) == 2 and ATTENTES[1] > ATTENTES[0] * 1.2, ATTENTES)
verifier("aucune quarantaine posée", not R._QUARANTAINE, R._QUARANTAINE)

print("2. Le plafond commun apprend la limite du fournisseur")
configure = C._plafond_configure()
verifier(f"le plafond descend au nombre d'appels acceptés (3 sur {configure})", C.plafond_global() == 3,
         C.plafond_global())
C._APPRIS["jusqu_a"] = time.monotonic() - 1
verifier("il remonte au réglage une fois sa durée passée", C.plafond_global() == configure, C.plafond_global())
C._EN_VOL[0] = 0
C.signaler_saturation()
verifier("il ne descend jamais sous 2", C.plafond_global() == 2, C.plafond_global())
C._APPRIS.clear()

print("3. Un vrai quota garde sa quarantaine")
appels.clear()
ATTENTES.clear()
SCENARIO["puissant"] = [REFUS_QUOTA]
resultat = asyncio.run(R.ResilientLLM(R.LLMTier.COMPLEX).ainvoke([]))
verifier("un quota épuisé passe au modèle suivant", appels == ["puissant", "rapide"], appels)
verifier("et le met en quarantaine", ("ollama_cloud", "puissant") in R._QUARANTAINE, R._QUARANTAINE)
R._QUARANTAINE.clear()

print("4. Une saturation sans fin rend la main")
appels.clear()
ATTENTES.clear()
SCENARIO["puissant"] = [REFUS_CONCURRENCE] * 50
SCENARIO["rapide"] = [REFUS_CONCURRENCE] * 50
try:
    asyncio.run(R.ResilientLLM(R.LLMTier.COMPLEX).ainvoke([]))
    fini = "réussi"
except Exception as e:  # noqa: BLE001
    fini = type(e).__name__
verifier("l'appel finit par échouer proprement", fini != "réussi", fini)
verifier(f"attentes bornées ({len(ATTENTES)} au plus {2 * R.MAX_ATTENTES_CONCURRENCE})",
         len(ATTENTES) <= 2 * R.MAX_ATTENTES_CONCURRENCE and max(ATTENTES or [0]) <= 45, ATTENTES)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
