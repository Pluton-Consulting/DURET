"""
Banc du RELAIS DOCUMENTAIRE (17/09) : sur un appel de fond qui tarde, le secours
part en parallèle au lieu d'attendre l'échec du principal (deux minutes perdues
à chaque gros appel du mémoire réel de Noa). Exécuté sur le module livré, avec
des modèles doublés ; sans base ni réseau.

    python backend/scripts/test_relais_documentaire.py backend
"""
import asyncio, os, sys, time
from pathlib import Path

BACKEND = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
for k, v in {"DATABASE_URL": "postgresql://x:x@localhost/x", "JWT_SECRET_KEY": "x" * 40, "RESEND_API_KEY": "x"}.items():
    os.environ.setdefault(k, v)
ECHECS = []


def verifier(nom, condition, detail=""):
    print(("  ✓ " if condition else "  ✗ ") + nom + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        ECHECS.append(nom)


import llm.router as R

R._filtrer_quarantaine = lambda c: c
R._tier_chain = lambda t: [("p", "principal"), ("s", "secours")]
notes, appels = [], []


async def note(d):
    notes.append(d)

R._preciser_activite = note
R.RELAIS_DOCUMENTAIRE_S = 0.2


class Faux:
    lent, casse, annules = 0.05, False, 0

    def __init__(self, tier):
        pass

    async def ainvoke(self, messages, **k):
        appels.append(dict(k))
        if k.get("_a_partir_de"):
            await asyncio.sleep(0.1)
            return "secours"
        try:
            await asyncio.sleep(Faux.lent)
        except asyncio.CancelledError:
            Faux.annules += 1
            raise
        if Faux.casse:
            raise TimeoutError("délai")
        return "principal"

R.ResilientLLM = Faux


async def main():
    r = await R.appel_documentaire("complex", [], _secours_timeout_documentaire=True)
    verifier("principal rapide : sa réponse, aucun relais, rien à l'écran", r == "principal" and not notes and len(appels) == 1)
    Faux.lent = 5; t = time.time()
    r = await R.appel_documentaire("complex", [], _secours_timeout_documentaire=True)
    verifier("principal lent : le secours part en parallèle et sa réponse est gardée, sans attendre l'échec", r == "secours" and time.time() - t < 1, f"{r} {time.time() - t:.2f}s")
    verifier("l'écran le dit, sans nommer de modèle", len(notes) == 1 and "second modèle" in notes[0] and "principal" not in notes[0].replace("modèle principal", ""))
    await asyncio.sleep(0.05)
    verifier("l'appel perdant est annulé (pas de créneau gardé pour rien)", Faux.annules == 1)
    verifier("le relais part du SECOURS et garde les options de l'appel", appels[-1].get("_a_partir_de") == 1 and appels[-1].get("_secours_timeout_documentaire") is True)
    Faux.lent, Faux.casse = 0.3, True
    verifier("principal en échec après le relais : la réponse du secours", await R.appel_documentaire("complex", []) == "secours")
    R._tier_chain = lambda t: [("p", "principal")]; Faux.lent, Faux.casse = 0.3, False; avant = len(notes)
    verifier("sans secours disponible : l'appel ordinaire, aucun relais", await R.appel_documentaire("complex", []) == "principal" and len(notes) == avant)
    # 18/09 : un travail annulé à son plafond PENDANT la première attente laissait le principal tourner seul
    # (appel payant perdu, « Task exception was never retrieved »). Il est annulé avec l'appel.
    R._tier_chain = lambda t: [("p", "principal"), ("s", "secours")]; Faux.lent, Faux.casse = 5, False
    avant_annules = Faux.annules
    tache = asyncio.ensure_future(R.appel_documentaire("complex", []))
    await asyncio.sleep(0.05)
    tache.cancel()
    try:
        await tache
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.05)
    verifier("un appel annulé pendant la première attente annule aussi le principal", Faux.annules == avant_annules + 1, Faux.annules - avant_annules)

asyncio.run(main())
composeur = (BACKEND / "skills" / "documents_dossier.py").read_text(encoding="utf-8")
verifier("les appels documentaires passent par le relais", "appel_documentaire(palier,messages," in composeur and "get_llm(palier).ainvoke(" not in composeur)
print(("✗ %d échec(s)" % len(ECHECS)) if ECHECS else "✓ 0 échec")
sys.exit(1 if ECHECS else 0)
