"""
Banc de la reprise visible — « Approuver » ne laisse plus un écran figé.

POURQUOI. Noa, 31/08 : « quand j'appuie sur autoriser le plan, il y a trop de
délai avant que le chat bouge, on a l'impression que ça s'est arrêté ». La
reprise post-validation exécutait le graphe dans un `ainvoke` MUET : plusieurs
minutes de plan sans un signe. Désormais la reprise streame nœud par nœud,
enregistre sa progression (`_REPRISES`), une route l'expose, et l'écran la
sonde pendant l'accord : le libellé « je … » bouge dès le clic.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ REPRISE VISIBLE — {BACKEND.parent}\n")
runtime = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
reprise = runtime[runtime.index("async def resume_turn("):runtime.index("async def stream_turn(")]
verifier("la reprise STREAME le graphe nœud par nœud (plus d'ainvoke muet)",
         "astream" in reprise and "graph.ainvoke" not in reprise)
verifier("chaque nœud enregistre sa progression, avec son libellé « je … »",
         "_REPRISES[" in reprise and "libelle(node_name" in reprise)
verifier("la progression s'efface quoi qu'il arrive (finally)",
         re.search(r"finally:\s*\n\s*_REPRISES\.pop", reprise) is not None)
verifier("une nouvelle interruption est capturée depuis le flux (plus de result d'ainvoke)",
         "_extract_interrupt(result)" not in reprise and "interruption" in reprise)
verifier("l'accès pour l'écran existe (progression_reprise)", "def progression_reprise(" in runtime)
validation = (BACKEND / "routers" / "validation.py").read_text(encoding="utf-8")
verifier("la route GET /{id}/reprise expose la progression",
         '"/{validation_id}/reprise"' in validation and "progression_reprise" in validation)
chat = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("dès le clic : le journal parle (« j'exécute ce que vous venez d'approuver »)",
         "j'exécute ce que vous venez d'approuver" in chat)
verifier("l'écran sonde la progression pendant l'accord, et la sonde s'arrête seule",
         "/reprise" in chat and "accordEnCoursRef.current !== id" in chat)
verifier("la frise s'anime pendant la reprise (loading inclut l'accord en cours)",
         re.search(r"loading=\{loading \|\| accordEnCours !== null\}", chat) is not None)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
