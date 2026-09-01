"""
Banc « la question avant sa réponse » — 01/09.

Relevé par Noa : en changeant de page, sa question s'affichait SOUS la réponse.
Cause : les deux messages d'un tour sont insérés dans la MÊME transaction
(executemany), NOW() y est figé, les deux lignes portent le même created_at —
et l'ORDER BY sur la seule date rendait leur ordre au hasard. Ce banc fige le
départage par rôle dans la lecture de l'historique.
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ ORDRE DES MESSAGES — {BACKEND.resolve().parent}\n")
chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
verifier("l'historique départage l'égalité de date par le rôle (user avant assistant)",
         re.search(r"ORDER BY m\.created_at ASC,\s*\n?\s*CASE WHEN m\.role = 'user' "
                   r"THEN 0 ELSE 1 END ASC", chat))
verifier("le tour écrit bien la question PUIS la réponse (executemany, dans cet ordre)",
         re.search(r'\[\(uuid\.UUID\(thread_pk\), "user", user_content or ""\),\s*\n'
                   r'\s*\(uuid\.UUID\(thread_pk\), "assistant", assistant_content or ""\)\]', chat))
print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s)' if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
