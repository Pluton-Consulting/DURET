"""
Banc « LE RÉSUMÉ GLISSANT NE RETIENT PLUS LE TOUR » (08/09 après-midi).

Chronométré sur l'export de 11:33 (Duret) : avant que le tour ne commence, la
fonte des messages sortis de la fenêtre — un appel au modèle léger — coûtait
9 secondes sur le chemin critique, à chaque tour, pour un texte qui ne décrit
que le passé. Le 31/08 l'avait mise en parallèle du rappel vectoriel ; ça ne
suffisait pas. Désormais le tour PART avec le résumé tel qu'il est, lance la
fonte en fond, et le tour suivant la reprend.

CE QUE CE BANC PROUVE (fonte doublée, module EXÉCUTÉ) : le lancement ne
bloque pas ; une seule fonte par fil à la fois ; le résultat est repris une
fois puis n'est plus rendu ; un échec de fonte ne lève jamais ; et rag_node
ne l'attend plus. Tombe sur la version d'avant.
"""
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LE RÉSUMÉ GLISSANT EN FOND — {BACKEND.parent}\n")

sys.modules["config"] = types.ModuleType("config")
sys.modules["config"].settings = types.SimpleNamespace()
src = BACKEND / "agents" / "memoire_conversation.py"
mod = types.ModuleType("memoire_double")
mod.__dict__["__file__"] = str(src)
exec(compile(src.read_text(encoding="utf-8"), str(src), "exec"), mod.__dict__)

verifier("`fondre_en_fond` et `resume_pret` existent",
         callable(getattr(mod, "fondre_en_fond", None)) and callable(getattr(mod, "resume_pret", None)))
if callable(getattr(mod, "fondre_en_fond", None)):
    APPELS = []

    async def _fondre(state, messages, anciens):
        APPELS.append((int(state.get("resume_couvre") or 0), anciens))
        await asyncio.sleep(0.05)
        return {"resume_conversation": "RÉSUMÉ FONDU", "resume_couvre": anciens}

    mod.fondre_dans_le_resume = _fondre

    async def scenario():
        boucle = asyncio.get_event_loop()
        verifier("avant toute fonte, rien n'est prêt", mod.resume_pret("fil-1") == {})
        t0 = boucle.time()
        mod.fondre_en_fond("fil-1", {"resume_couvre": 0}, ["a", "b", "c", "d"], 4)
        mod.fondre_en_fond("fil-1", {"resume_couvre": 0}, ["a", "b", "c", "d"], 4)
        verifier("le lancement ne bloque pas le tour (moins de 20 ms)", boucle.time() - t0 < 0.02)
        verifier("pendant la fonte, le tour part SANS résumé neuf", mod.resume_pret("fil-1") == {})
        await asyncio.sleep(0.12)
        maj = mod.resume_pret("fil-1")
        verifier("au tour suivant, le résumé fondu est repris avec sa couverture",
                 maj.get("resume_conversation") == "RÉSUMÉ FONDU" and maj.get("resume_couvre") == 4, maj)
        verifier("repris une fois, il n'est plus rendu", mod.resume_pret("fil-1") == {})
        verifier("une seule fonte par fil à la fois (le second lancement est ignoré)", APPELS == [(0, 4)], APPELS)
        # Deux fils ne se gênent pas.
        mod.fondre_en_fond("fil-2", {"resume_couvre": 2}, ["a"] * 6, 6)
        await asyncio.sleep(0.12)
        verifier("un autre fil a sa propre fonte", mod.resume_pret("fil-2").get("resume_couvre") == 6)

        async def _casse(state, messages, anciens):
            raise RuntimeError("modèle léger absent")
        mod.fondre_dans_le_resume = _casse
        mod.fondre_en_fond("fil-3", {}, ["a", "b"], 2)
        await asyncio.sleep(0.05)
        verifier("une fonte qui échoue ne lève jamais et ne laisse rien de prêt", mod.resume_pret("fil-3") == {})
        verifier("…et le fil est de nouveau libre pour une fonte", "fil-3" not in mod._FONTES_EN_COURS)

    asyncio.run(scenario())

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("rag_node ne fait plus `await fondre_dans_le_resume(` : le tour ne l'attend plus",
         "await fondre_dans_le_resume(" not in agent1)
verifier("rag_node reprend le résumé fondu (`resume_pret`) puis lance la suivante (`fondre_en_fond`)",
         "maj_memoire = resume_pret(_tid)" in agent1
         and "fondre_en_fond(_tid, {**state, **maj_memoire}, _tous, _anciens)" in agent1)
verifier("le rappel vectoriel (un embedding, pas un appel de modèle) reste attendu",
         "_rappels = await rappeler_echanges(_tid, query, _premier_rang_fenetre)" in agent1)
verifier("le résumé repris entre bien dans l'état du tour (`**maj_memoire` dans le retour)",
         "**maj_memoire" in agent1)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
