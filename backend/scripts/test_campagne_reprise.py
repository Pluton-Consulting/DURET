"""
Banc de la reprise des campagnes — « un trou d'air de la cascade ne tue plus l'enrichissement ».

POURQUOI. Le 31/08 à 12:02 (journaux du VPS) : LongCat expire deux fois, Gemini
répond 503, Groq et OpenRouter sont morts depuis des jours, Ollama absent →
« Tous les modèles LLM ont échoué » → « Tout enrichir » ET « Enrichir les
documents » interrompues au premier lot venu (la documentaire à zéro appel).
Deux minutes de panne, une après-midi perdue, et rien d'autre à faire que
relancer à la main.

CE QUE CE BANC PROUVE, sans base ni réseau : `avec_reprise` (extraite du source
livré) rejoue le lot après une panne de TOUTE la cascade, avec les attentes
déclarées ; ne rejoue PAS un refus (`ModeleDegrade`, anonymisation
indisponible) ; renonce après la dernière attente en laissant remonter la vraie
erreur ; et que les deux campagnes passent par elle.
"""
import asyncio
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


src = (BACKEND / "learning" / "enrichissement.py").read_text(encoding="utf-8")
debut = src.index("REPRISES_CASCADE_S = (")
fin = src.index("async def _lire_lot(")
attentes = []


class _Journal:
    def warning(self, *a, **k): pass


class ModeleDegrade(RuntimeError):
    pass


async def _faux_sleep(s):
    attentes.append(s)


espace = {"asyncio": type("A", (), {"sleep": staticmethod(_faux_sleep)}),
          "logger": _Journal(), "ModeleDegrade": ModeleDegrade}
exec(src[debut:fin], espace)  # noqa: S102 — code du dépôt
avec_reprise = espace["avec_reprise"]
REPRISES = espace["REPRISES_CASCADE_S"]

PANNE = RuntimeError("Tous les modèles LLM ont échoué (dernier : All connection attempts failed)")


def scenario(issues):
    """Une fabrique d'appels qui rejoue `issues` dans l'ordre : une exception
    est levée, toute autre valeur est rendue."""
    compteur = {"n": 0}

    async def appel():
        i = compteur["n"]
        compteur["n"] += 1
        issue = issues[min(i, len(issues) - 1)]
        if isinstance(issue, BaseException):
            raise issue
        return issue
    return appel, compteur


print(f"\n═══ REPRISE DES CAMPAGNES — {BACKEND.parent}\n")

print("1. Une panne passagère se rejoue, puis le lot passe")
attentes.clear()
appel, c = scenario([PANNE, PANNE, ("ok", {}, "longcat:LongCat-2.0")])
phases = []
res = asyncio.run(avec_reprise(appel, "lot de test", sur_attente=phases.append))
verifier("le résultat du troisième essai est rendu", res[0] == "ok")
verifier("trois appels, pas un de plus", c["n"] == 3)
verifier(f"les deux attentes sont les deux premières déclarées {REPRISES[:2]}", attentes == list(REPRISES[:2]))
verifier("l'écran est informé pendant l'attente (phase)", len(phases) == 2 and "nouvel essai" in phases[0])

print("\n2. Un REFUS ne se rejoue pas")
attentes.clear()
appel, c = scenario([ModeleDegrade("aucun modèle de confiance n'a répondu")])
try:
    asyncio.run(avec_reprise(appel, "lot"))
    verifier("ModeleDegrade remonte", False)
except ModeleDegrade:
    verifier("ModeleDegrade remonte immédiatement", c["n"] == 1 and attentes == [])
appel, c = scenario([RuntimeError("Anonymisation indisponible : campagne interrompue.")])
try:
    asyncio.run(avec_reprise(appel, "lot"))
    verifier("anonymisation indisponible remonte", False)
except RuntimeError as e:
    verifier("anonymisation indisponible remonte immédiatement", c["n"] == 1 and "Anonymisation" in str(e))
appel, c = scenario([ValueError("JSON illisible")])
try:
    asyncio.run(avec_reprise(appel, "lot"))
    verifier("une autre exception remonte", False)
except ValueError:
    verifier("une exception ordinaire remonte immédiatement (le lot est compté en échec par l'appelant)", c["n"] == 1)

print("\n3. Après la dernière attente, on renonce pour de bon")
attentes.clear()
appel, c = scenario([PANNE])
try:
    asyncio.run(avec_reprise(appel, "lot"))
    verifier("la panne persistante remonte", False)
except RuntimeError as e:
    verifier("la panne persistante remonte, telle quelle", "Tous les modèles" in str(e))
    verifier(f"{len(REPRISES) + 1} essais, {len(REPRISES)} attentes", c["n"] == len(REPRISES) + 1 and attentes == list(REPRISES))
verifier("les attentes vont en croissant (on ne martèle pas un fournisseur à terre)",
         list(REPRISES) == sorted(REPRISES) and REPRISES[0] >= 30)

print("\n4. Les deux campagnes passent par la reprise")
verifier("campagne des mails : _lire_lot est appelé via avec_reprise",
         re.search(r"await avec_reprise\(\s*lambda: _lire_lot\(", src) is not None)
docs = (BACKEND / "learning" / "enrichissement_docs.py").read_text(encoding="utf-8")
verifier("campagne documentaire : _lire_lot_docs est appelé via avec_reprise",
         re.search(r"await avec_reprise\(\s*lambda: _lire_lot_docs\(", docs) is not None)
verifier("aucun appel direct restant à _lire_lot(…) dans la boucle des mails",
         "= await _lire_lot(" not in src)
verifier("aucun appel direct restant à _lire_lot_docs(…) dans la boucle documentaire",
         "= await _lire_lot_docs(" not in docs)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
