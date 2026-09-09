"""
Banc « LA CONVERSATION SUIT LA PERSONNE, PAS L'APPAREIL » (09/09).

Demande de Noa : « pour chaque utilisateur, la conversation doit se conserver
sur téléphone et PC pour qu'il ait la suite de la conversation sur PC,
téléphone, etc., par utilisateur ».

CE QUI SE PASSAIT. Les fils vivent depuis toujours en base, par personne
(`threads.user_id`, RLS, et `_claim_thread` refuse le fil d'un autre). Mais
l'écran ne retenait le fil COURANT que dans le `localStorage` du navigateur :
un téléphone n'y trouvait rien, ouvrait une conversation neuve, et les deux
appareils avançaient côte à côte sans jamais se voir. Rien ne permettait non
plus de reprendre une conversation passée, ni d'en ouvrir une nouvelle
volontairement.

CE QUE CE BANC PROUVE (sans base, sans navigateur) :
  · `GET /api/chat/threads` et `GET /api/chat/threads/dernier` EXÉCUTÉES
    contre une base doublée : les fils de la PERSONNE (filtre `user_id`),
    du plus récent au plus ancien, sans les fils de la file d'attente
    (`file:…`, sans mémoire), limite bornée, et `thread_id: null` quand la
    personne n'a aucune conversation ;
  · les fonctions pures du composant livré, EXÉCUTÉES par Node : la date en
    mots (« à l'instant », « hier 14:02 »), le titre coupé ;
  · le contrat de `ChatWindow` : le SERVEUR dit quelle conversation rouvrir,
    le stockage local n'est qu'un repli, on ne change pas de conversation
    sous un tour en vol, et un fil dont le serveur porte plus de messages
    (l'autre appareil a écrit) est relu — jamais pendant qu'une bulle attend
    un accord.
Tombe sur la version d'avant (la route `dernier` n'existait pas, l'écran ne
lisait que le stockage local, et rien n'ouvrait une autre conversation).
"""
import ast
import asyncio
import datetime
import pathlib
import re
import subprocess
import sys
import tempfile
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LA CONVERSATION SUIT LA PERSONNE — {BACKEND.parent}\n")

# ══════════════════════════════════════════════════════════════════════════
# 1. LES DEUX ROUTES, EXÉCUTÉES CONTRE UNE BASE DOUBLÉE
# ══════════════════════════════════════════════════════════════════════════
print("── 1. Le serveur : les conversations de la personne")


def _t(jours=0, minutes=0):
    return datetime.datetime(2026, 9, 9, 12, 0) - datetime.timedelta(days=jours, minutes=minutes)


# La base : des fils de deux personnes, dont un fil de file d'attente.
FILS = [
    {"langgraph_thread_id": "fil-recent", "title": "Dossier M. et Mme Camp",
     "agent_type": "agent2", "updated_at": _t(minutes=5), "user_id": "u1"},
    {"langgraph_thread_id": "fil-hier", "title": "Relance des impayés",
     "agent_type": "agent1", "updated_at": _t(jours=1), "user_id": "u1"},
    {"langgraph_thread_id": "fil-sans-titre", "title": "  ",
     "agent_type": "agent1", "updated_at": _t(jours=3), "user_id": "u1"},
    {"langgraph_thread_id": "file:tache-42", "title": "En file",
     "agent_type": "agent1", "updated_at": _t(minutes=1), "user_id": "u1"},
    {"langgraph_thread_id": None, "title": "Fil sans identifiant",
     "agent_type": "agent1", "updated_at": _t(minutes=2), "user_id": "u1"},
    {"langgraph_thread_id": "fil-de-lautre", "title": "Conversation d'un collègue",
     "agent_type": "agent1", "updated_at": _t(minutes=1), "user_id": "u2"},
]
REQUETES = []


class _Conn:
    async def fetch(self, sql, *args):
        REQUETES.append((" ".join(sql.split()), args))
        # On rejoue le SQL À LA MAIN, mais on EXIGE que ses clauses existent :
        # un banc qui inventerait le filtrage prouverait son propre code.
        user_id, limite = args[0], args[1]
        sortie = [f for f in FILS if f["user_id"] == user_id]
        if "langgraph_thread_id IS NOT NULL" in " ".join(sql.split()):
            sortie = [f for f in sortie if f["langgraph_thread_id"]]
        if "NOT LIKE 'file:%'" in " ".join(sql.split()):
            sortie = [f for f in sortie if not str(f["langgraph_thread_id"]).startswith("file:")]
        sortie.sort(key=lambda f: f["updated_at"], reverse=True)
        return sortie[:limite]


class _Base:
    def __call__(self, *a, **k):
        return self

    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


source = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
espace = {"get_rls_db": _Base(), "User": object,
          "Depends": lambda f: None, "get_current_user": None,
          "router": types.SimpleNamespace(get=lambda *a, **k: (lambda f: f))}
arbre = ast.parse(source)
noms = {"list_threads", "dernier_fil", "_SQL_FILS", "_fil_public"}
gardes = []
for n in arbre.body:
    if isinstance(n, ast.AsyncFunctionDef) and n.name in noms:
        n.decorator_list = []
        gardes.append(n)
    elif isinstance(n, ast.FunctionDef) and n.name in noms:
        n.decorator_list = []
        gardes.append(n)
    elif isinstance(n, ast.Assign) and any(isinstance(c, ast.Name) and c.id in noms for c in n.targets):
        gardes.append(n)
verifier("les deux routes et leur requête existent dans routers/chat.py",
         {getattr(n, "name", None) or n.targets[0].id for n in gardes} == noms,
         [getattr(n, "name", None) or n.targets[0].id for n in gardes])
if len(gardes) == 4:
    exec(compile(ast.Module(body=gardes, type_ignores=[]), "chat", "exec"), espace)
    U = types.SimpleNamespace(id="u1", role="direction")
    liste = asyncio.run(espace["list_threads"](current_user=U))
    verifier("la liste rend les conversations de la PERSONNE, la plus récente en tête",
             [f["thread_id"] for f in liste] == ["fil-recent", "fil-hier", "fil-sans-titre"], liste)
    verifier("… avec leur titre, leur expert et leur date",
             liste[0] == {"thread_id": "fil-recent", "titre": "Dossier M. et Mme Camp",
                          "agent_type": "agent2", "updated_at": _t(minutes=5)}, liste[0])
    verifier("un fil sans titre n'est pas vide à l'écran : « Conversation »",
             liste[2]["titre"] == "Conversation", liste[2])
    verifier("les fils de la FILE D'ATTENTE (`file:…`, sans mémoire) n'en font pas partie",
             all(not f["thread_id"].startswith("file:") for f in liste))
    verifier("la conversation d'un collègue n'y est jamais (filtre user_id, en plus de la RLS)",
             "fil-de-lautre" not in [f["thread_id"] for f in liste]
             and "user_id = $1" in REQUETES[-1][0])
    # La limite est bornée : une demande démesurée ne fait pas remonter toute la
    # table, et une valeur vide ou nulle retombe sur le défaut (30) plutôt que
    # de rendre une liste vide, ce qui passerait pour « aucune conversation ».
    defaut = REQUETES[-1][1][1]
    asyncio.run(espace["list_threads"](limite=9999, current_user=U))
    haut = REQUETES[-1][1][1]
    asyncio.run(espace["list_threads"](limite=0, current_user=U))
    zero = REQUETES[-1][1][1]
    verifier("la limite est bornée : 30 par défaut, 200 au plus, et 0 retombe sur le défaut",
             (defaut, haut, zero) == (30, 200, 30), (defaut, haut, zero))
    dernier = asyncio.run(espace["dernier_fil"](current_user=U))
    verifier("`/threads/dernier` rend LA conversation à rouvrir : la plus récente de la personne",
             dernier["thread_id"] == "fil-recent" and dernier["titre"] == "Dossier M. et Mme Camp", dernier)
    verifier("… en ne demandant qu'UNE ligne à la base", REQUETES[-1][1][1] == 1, REQUETES[-1][1])
    vide = asyncio.run(espace["dernier_fil"](current_user=types.SimpleNamespace(id="u9", role="terrain")))
    verifier("sans aucune conversation : `thread_id` vaut null (l'écran ouvre un fil neuf)",
             vide == {"thread_id": None}, vide)

# ══════════════════════════════════════════════════════════════════════════
# 2. LE COMPOSANT : SES FONCTIONS PURES, EXÉCUTÉES PAR NODE
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. Le choix de la conversation, à l'écran")
composant = FRONTEND / "components" / "chat" / "Conversations.tsx"
verifier("le composant `Conversations.tsx` existe", composant.exists())
if composant.exists():
    texte = composant.read_text(encoding="utf-8")
    m_date = re.search(r"export function libelleDate\(iso\?: string \| null, maintenant: Date = new Date\(\)\): string \{(.*?)\n\}", texte, re.S)
    m_titre = re.search(r"export function titreCourt\(titre\?: string \| null, max = 48\): string \{(.*?)\n\}", texte, re.S)
    verifier("`libelleDate` et `titreCourt` sont des fonctions pures du composant livré",
             m_date is not None and m_titre is not None)
    if m_date and m_titre:
        js = (
            "function libelleDate(iso, maintenant = new Date()) {"
            + re.sub(r": [A-Za-z|\[\]. ]+(?=[,)])", "", m_date.group(1)) + "\n}\n"
            "function titreCourt(titre, max = 48) {" + m_titre.group(1) + "\n}\n"
            "const N = new Date('2026-09-09T12:00:00');\n"
            "const out = [\n"
            "  libelleDate(new Date(N - 30 * 1000).toISOString(), N),\n"
            "  libelleDate(new Date(N - 12 * 60 * 1000).toISOString(), N),\n"
            "  libelleDate(new Date('2026-09-09T09:15:00').toISOString(), N),\n"
            "  libelleDate(new Date('2026-09-08T14:02:00').toISOString(), N),\n"
            "  libelleDate(new Date('2026-09-03T10:00:00').toISOString(), N),\n"
            "  libelleDate(null, N), libelleDate('pas une date', N),\n"
            "  titreCourt('  Dossier   M. et Mme Camp  '), titreCourt(''), titreCourt(null),\n"
            "  titreCourt('a'.repeat(80)).length, titreCourt('a'.repeat(80)).endsWith('…'),\n"
            "];\n"
            "process.stdout.write(JSON.stringify(out));")
        with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as f:
            f.write(js)
            chemin = f.name
        try:
            r = subprocess.run(["node", chemin], capture_output=True, text=True, timeout=20)
            sortie = r.stdout
        except (OSError, subprocess.TimeoutExpired):
            sortie = ""
        import json as _j
        vals = _j.loads(sortie) if sortie.startswith("[") else []
        verifier("la date se lit en mots : « à l'instant », « il y a 12 min », l'heure aujourd'hui, « hier … », la date au-delà",
                 vals[:5] == ["à l'instant", "il y a 12 min", "09:15", "hier 14:02", "3 sept."], sortie or "node injoignable")
        verifier("une date absente ou illisible ne rend rien (aucun « Invalid Date » à l'écran)",
                 vals[5:7] == ["", ""], vals[5:7] if vals else sortie)
        verifier("le titre est resserré ; vide, il dit « Nouvelle conversation » ; long, il est coupé",
                 vals[7:] == ["Dossier M. et Mme Camp", "Nouvelle conversation", "Nouvelle conversation", 48, True],
                 vals[7:] if vals else sortie)
    verifier("la liste vient du SERVEUR (aucun stockage local dans ce composant)",
             "localStorage" not in texte and "FilConversation" in texte)
    verifier("on ne change pas de conversation sous un tour en vol (`occupe` désactive tout)",
             "disabled={occupe || f.thread_id === courant}" in texte
             and "disabled={occupe}" in texte)
    verifier("« Nouvelle conversation » existe, en menu et en bouton",
             texte.count("onNouvelle") >= 2 and "+ Nouvelle" in texte)
    verifier("la bibliothèque d'abord : le menu vient de components/ui, rien de sur-mesure",
             "@/components/ui/dropdown-menu" in texte and "@/components/ui/button" in texte)

# ══════════════════════════════════════════════════════════════════════════
# 3. LE CONTRAT DE L'ÉCRAN
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. Ce que fait ChatWindow au chargement")
cw = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("au chargement, c'est le SERVEUR qui dit la conversation à rouvrir",
         '"/api/chat/threads/dernier"' in cw and "const distant = r?.thread_id || null" in cw)
verifier("le stockage local n'est plus que le repli (serveur muet, ou hors ligne)",
         "else if (local) ouvrir(local)" in cw and ".catch(() => { if (local) ouvrir(local) })" in cw)
verifier("un tour ENCORE EN VOL sur cet appareil garde la main (on ne bascule pas sous lui)",
         "if (local && reprendreTour(local)) { ouvrir(local); return" in cw)
verifier("un fil passé en prop (lien direct, historique du tableau de bord) prime sur tout",
         "if (initialThreadId) { ouvrir(initialThreadId); return" in cw)
verifier("la liste des conversations est chargée, et rafraîchie à la fin de chaque tour",
         '"/api/chat/threads?limite=30"' in cw
         and "if (token && !loading) chargerConversations()" in cw)
verifier("changer de conversation : le fil est mémorisé, l'écran vidé, l'historique relu",
         "const reprendreConversation = (tid: string) => {" in cw
         and "rememberThread(tid)" in cw and "setMessages([])" in cw)
verifier("« nouvelle conversation » oublie le fil et repart à blanc, jamais pendant un tour",
         "const nouvelleConversation = () => {" in cw
         and "if (loading || principalOccupeRef.current) return" in cw and "forgetThread()" in cw)
verifier("L'AUTRE APPAREIL A ÉCRIT : plus de messages au serveur que sur cet écran → on relit le fil",
         "(rows || []).length > affiches.length" in cw and "chargerHistorique(tid).catch(() => {})" in cw)
verifier("… mais jamais pendant qu'une bulle attend (accord, tâche de fond)",
         "const bulleEnAttente = affiches.some((m) => m.placeholder || m.tacheId)" in cw
         and "if (!bulleEnAttente && " in cw)
verifier("le composant est monté au-dessus de la saisie, avec l'état d'occupation",
         "<Conversations fils={conversations} courant={threadId}" in cw
         and "occupe={loading || principalOccupe}" in cw)
css = (FRONTEND / "app" / "interface-v2.css").read_text(encoding="utf-8")
mobile = (FRONTEND / "app" / "mobile.css").read_text(encoding="utf-8")
verifier("les styles existent, et le palier téléphone les reprend",
         ".v2-fils {" in css and ".v2-fils {" in mobile)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
