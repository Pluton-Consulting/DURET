"""
Banc « LES MESSAGES D'UNE CONVERSATION NE SE LISENT QUE PAR SON PROPRIÉTAIRE » (14/09).

Trouvé chez Duret en vérifiant que deux prénoms d'une même adresse ont chacun
leur conversation, présent à l'identique chez Symbiose : `GET
/api/chat/threads/{id}/messages` ne filtrait que par la RLS, et la politique
de `threads` / `messages` ouvre TOUS les fils à la direction et au
super_admin. Un compte de direction qui connaissait l'identifiant d'un fil
lisait donc la conversation d'un collègue. Poursuivre un fil, lister ses
conversations ou reprendre « la dernière » filtraient déjà par `user_id` :
seule la lecture de l'historique était restée ouverte.

CE QUE CE BANC PROUVE : la route, EXÉCUTÉE contre une base doublée qui applique
la RLS telle qu'elle est (tout pour la direction), ne rend rien à la direction
ni à un collègue pour le fil d'un autre, et rend le sien au propriétaire.
Tombe sur la version d'avant. Le même fichier des deux côtés.
"""
import ast
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


print(f"\n═══ LES MESSAGES D'UNE CONVERSATION — {BACKEND.parent}\n")

chat = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
fn = next((n for n in ast.parse(chat).body
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_thread_messages"), None)
verifier("chat.py porte get_thread_messages", fn is not None)

FILS = {"fil-a": "alice", "fil-b": "bruno"}
MESSAGES = {"fil-a": [{"id": 1, "role": "user", "content": "devis Martin"}],
            "fil-b": [{"id": 2, "role": "user", "content": "chantier du port"}]}


class _Conn:
    async def fetch(self, sql, *a):
        # La RLS de la base laisse la direction tout voir : seul un filtre
        # explicite dans la requête protège le fil d'un autre.
        if "t.user_id = $2" in sql and (len(a) < 2 or str(a[1]) != FILS.get(a[0])):
            return []
        return MESSAGES.get(a[0], [])


class _Rls:
    def __init__(self, uid, role):
        pass

    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *x):
        return False


if fn is not None:
    fn.decorator_list = []
    fn.args.defaults = []
    for a in fn.args.args:
        a.annotation = None
    espace = {"get_rls_db": _Rls}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "chat", "exec"), espace)
    lire = espace["get_thread_messages"]
    qui = lambda uid, role: types.SimpleNamespace(id=uid, role=role)  # noqa: E731
    r = asyncio.run(lire("fil-a", qui("dir", "direction")))
    verifier("EXÉCUTÉ — la direction ne lit PAS la conversation d'un collègue", r == [], r)
    r = asyncio.run(lire("fil-a", qui("sa", "super_admin")))
    verifier("le super_admin non plus", r == [], r)
    r = asyncio.run(lire("fil-a", qui("bruno", "commercial")))
    verifier("un collègue non plus", r == [], r)
    r = asyncio.run(lire("fil-a", qui("alice", "administratif")))
    verifier("la propriétaire lit la sienne", [m["id"] for m in r] == [1], r)

verifier("poursuivre un fil exige d'en être le propriétaire",
         "WHERE langgraph_thread_id = $1 AND user_id = $2" in chat)
verifier("la liste des conversations filtre par personne",
         "WHERE user_id = $1" in chat.split("_SQL_FILS")[1][:200])

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
