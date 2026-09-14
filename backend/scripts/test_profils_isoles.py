"""
Banc « CHAQUE PROFIL SON ESPACE, MÊME SUR LA MÊME ADRESSE » (14/09, Duret).

Demande de Noa : « chaque profil doit avoir sa conversation indépendante,
comme Symbiose, même s'ils ont le même mail » ; et « tous les profils hors
admin et direction doivent avoir en Paramètres de quoi changer leur code, mais
pas leur compte Google ».

Audit fait avant d'écrire : les conversations, messages, tâches, consignes,
documents produits, suivis du courrier, factures et appareils sont rangés par
`users.id`. Deux fuites restaient :
  * `GET /api/chat/threads/{id}/messages` ne filtrait que par la RLS, qui
    ouvre TOUS les fils à la direction : un compte de direction lisait la
    conversation d'un collègue dont il connaissait l'identifiant ;
  * le contexte pré-inscrit du tableau de bord vivait dans le stockage du
    navigateur SANS nom de profil : sur un poste partagé, la tâche que
    Nathalie ouvrait apparaissait dans le chat d'Éric.

CE QUE CE BANC PROUVE :
  * la route des messages, EXÉCUTÉE contre une base doublée, ne rend rien à
    la direction pour le fil d'un autre et rend le sien au propriétaire ;
  * tout ce qui range « à quelqu'un » s'appuie sur l'identifiant du profil,
    jamais sur l'adresse (atelier, fil courant de l'écran) ;
  * le contexte pré-inscrit porte son destinataire, le chat l'écarte sinon ;
  * Paramètres : « Mon code de connexion » pour les profils métier, « Mon
    compte Google » pour l'administration et la direction seulement.
Tombe sur la version d'avant.
"""
import ast
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel):
    return (RACINE / rel).read_text(encoding="utf-8")


print(f"\n═══ CHAQUE PROFIL SON ESPACE — {RACINE}\n")

print("— Les messages d'une conversation")
chat = lire("backend/routers/chat.py")
fn = next((n for n in ast.parse(chat).body
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_thread_messages"), None)
verifier("chat.py porte get_thread_messages", fn is not None)

FILS = {"fil-nathalie": "nat", "fil-eric": "eric"}
MESSAGES = {"fil-nathalie": [{"id": 1, "role": "user", "content": "devis Martin"}],
            "fil-eric": [{"id": 2, "role": "user", "content": "chantier Mérignac"}]}


class _Conn:
    async def fetch(self, sql, *a):
        fil = a[0]
        proprietaire = FILS.get(fil)
        # La doublure applique la RLS telle qu'elle est en base : la direction
        # voit TOUS les fils. Seul un filtre explicite dans la requête protège.
        if "t.user_id = $2" in sql and (len(a) < 2 or str(a[1]) != proprietaire):
            return []
        return MESSAGES.get(fil, [])


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
    lire_fil = espace["get_thread_messages"]
    qui = lambda uid, role: types.SimpleNamespace(id=uid, role=role)  # noqa: E731
    r = asyncio.run(lire_fil("fil-nathalie", qui("dir", "direction")))
    verifier("EXÉCUTÉ — la direction ne lit PAS la conversation de Nathalie", r == [], r)
    r = asyncio.run(lire_fil("fil-nathalie", qui("eric", "terrain")))
    verifier("Éric (même adresse) ne la lit pas non plus", r == [], r)
    r = asyncio.run(lire_fil("fil-nathalie", qui("nat", "administratif")))
    verifier("Nathalie lit la sienne", [m["id"] for m in r] == [1], r)
verifier("poursuivre un fil exige toujours d'en être le propriétaire",
         "WHERE langgraph_thread_id = $1 AND user_id = $2" in chat)
verifier("la liste des conversations et « la dernière » filtrent par profil",
         "WHERE user_id = $1" in chat.split("_SQL_FILS")[1][:200])

print("— Ce qui est « à quelqu'un » est rangé par identifiant, jamais par adresse")
for rel in ("backend/skills/bureau.py", "backend/skills/outils.py"):
    src = lire(rel)
    verifier(f"{rel} : le propriétaire d'un document est l'identifiant du profil",
             'return str(getattr(user, "id", "") or "")' in src)
fenetre = lire("frontend/components/chat/ChatWindow.tsx")
verifier("l'écran range le fil courant sous l'identifiant du profil (l'adresse en dernier recours)",
         "(session as any)?.user?.id || (session as any)?.user?.email" in fenetre)
auth_front = lire("frontend/lib/auth.ts")
verifier("la session porte l'identifiant du profil, pas l'adresse",
         "id: data.user_id ||" in auth_front and "(session.user as any).id = token.sub" in auth_front)

print("— Le contexte pré-inscrit du tableau de bord")
tableau = lire("frontend/components/tableau/TableauDeBord.tsx")
verifier("il porte son destinataire (`pour`)", "pour?: string | null" in tableau
         and tableau.count("preinscrire({ pour: profilDuJeton(token), ") == 3)
verifier("le chat écarte un contexte destiné à un autre profil",
         "c.pour === monProfil" in fenetre and "if (!monProfil) return" in fenetre)

print("— Paramètres")
reglages = lire("frontend/app/(app)/parametres/SettingsClient.tsx")
verifier("« Mon code de connexion » pour les profils métier",
         '{ key: "code", label: "Mon code de connexion", roles: ["commercial", "bureau_etudes", "conducteur", "administratif", "terrain"] }' in reglages
         and "<MonCode jeton={backendToken} />" in reglages)
verifier("« Mon compte Google » pour l'administration et la direction seulement",
         '{ key: "google", label: "Mon compte Google", roles: ["super_admin", "direction"] }' in reglages)
composant = lire("frontend/components/settings/MonCode.tsx")
verifier("le composant lit et change SON code (/api/users/me/code)",
         "/api/users/me/code" in composant and 'method: "PUT"' in composant)
verifier("Mon profil utilise le même composant (une seule vérité)",
         'import MonCode from "@/components/settings/MonCode"' in lire("frontend/app/(app)/profil/page.tsx"))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
