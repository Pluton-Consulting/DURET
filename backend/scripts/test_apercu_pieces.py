"""
Banc « L'APERÇU DES PIÈCES JOINTES » — relevé de Noa du 07/09 :
« tu n'as pas fait la petite prévisualisation sur les pièces jointes ».

CE QUI MANQUAIT :
  · la bulle de la personne ne portait que « 📎 nom, nom » ;
  · une fois la conversation rechargée, PLUS RIEN : la table `messages` ne
    gardait que le texte de la question, les fichiers avaient disparu du fil ;
  · la barre de saisie montrait le nom du fichier choisi, jamais l'image ;
  · et l'expert vision remontrait les photos qu'on venait d'envoyer, juste
    sous la question — une doublure de plus.

CE QUE CE BANC PROUVE (sans base, sans réseau, sans navigateur) :
  · `_persist_messages` (EXÉCUTÉ contre une base doublée) écrit les pièces de
    la question dans `messages.metadata` — nom, type, clé de dépôt — en JSON
    sérialisé (le pool n'a pas de codec JSONB), jamais les octets ;
  · `_pieces_persistables` rapproche les clés par le nom, et un fichier texte
    (sans clé) garde son nom ;
  · `pieces_du_tour_persistables` (runtime, EXÉCUTÉ) ne laisse passer ni les
    pages ni le base64 de l'état ;
  · les trois retours du runtime portent `pieces` (POST, reprise, WebSocket) ;
  · l'écran : le composant `PiecesJointes` existe et sait les deux sources
    (contenu à l'envoi, clé au rechargement, pastille sinon), la bulle
    l'affiche, l'historique relit `metadata` en chaîne OU en objet, la barre
    de saisie montre une vignette ;
  · `prechiffrage_node` (EXÉCUTÉ) ne remontre plus le bloc des photos à
    l'écran, et le garde dans l'historique du fil.

Tombe sur la version d'avant dès la première ligne.
"""
import asyncio
import json
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def _poser(nom, **attrs):
    mod = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nom] = mod
    return mod


def _exec_module(chemin: pathlib.Path, nom: str):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    return mod


print(f"\n═══ L'APERÇU DES PIÈCES JOINTES — {BACKEND.parent}\n")

# ══════════════════════════════════════════════════════════════════════════
# LES DOUBLURES de routers/chat.py — la base note ce qu'on lui écrit.
# ══════════════════════════════════════════════════════════════════════════
ECRITURES: list = []


class _ConnDouble:
    async def executemany(self, sql, lignes):
        ECRITURES.append((sql, list(lignes)))

    async def fetch(self, *a, **k):
        return []


class _RlsDouble:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return _ConnDouble()

    async def __aexit__(self, *a):
        return False


class _Champ:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


_routeur = types.SimpleNamespace()
for verbe in ("get", "post", "put", "delete", "websocket"):
    setattr(_routeur, verbe, lambda *a, **k: (lambda f: f))
_poser("fastapi", APIRouter=lambda *a, **k: _routeur, Depends=lambda f=None: None,
       HTTPException=type("HTTPException", (Exception,), {}),
       WebSocket=object, WebSocketDisconnect=type("WSD", (Exception,), {}),
       status=types.SimpleNamespace(**{n: 0 for n in (
           "HTTP_403_FORBIDDEN", "HTTP_409_CONFLICT", "HTTP_429_TOO_MANY_REQUESTS",
           "HTTP_401_UNAUTHORIZED", "HTTP_404_NOT_FOUND", "HTTP_400_BAD_REQUEST",
           "WS_1008_POLICY_VIOLATION")}))
_poser("pydantic", BaseModel=_Champ)
_poser("auth")
_poser("auth.dependencies", get_current_user=None)
_poser("auth.jwt_handler", decode_access_token=None)
_poser("database")
_poser("database.models", User=object)
_poser("database.connection", get_db=None, get_rls_db=lambda *a, **k: _RlsDouble())
_poser("security")
_poser("security.rbac", has_permission=lambda *a: True, SCHEDULE_EXEMPT_ROLES=())
_poser("security.audit", log_action=None)
_poser("agents")
_poser("agents.runtime", run_turn=None, stream_turn=None,
       FilOccupe=type("FilOccupe", (Exception,), {}))
_poser("config", settings=types.SimpleNamespace(max_body_mb=10))
_poser("ingestion")
_poser("ingestion.parsers", analyser=None, ligne_en_texte=None, famille=None,
       FichierNonSupporte=Exception)

chat = _exec_module(BACKEND / "routers" / "chat.py", "chat_double")
chat_src = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")

# ══════════════════════════════════════════════════════════════════════════
# 1. LA PERSISTANCE — nom, type, clé ; jamais les octets
# ══════════════════════════════════════════════════════════════════════════
print("── 1. Ce que l'historique garde")

PIECES_RECUES = [{"nom": "imagemaison.jpg", "mime": "image/jpeg", "b64": "QUFB"},
                 {"nom": "clients.xlsx", "mime": "application/vnd.ms-excel", "b64": "QkJC"},
                 {"nom": "apres-projet.jpg", "mime": "image/jpeg", "b64": "Q0ND"}]
PIECES_DU_TOUR = [{"nom": "imagemaison.jpg", "mime": "image/jpeg", "cle": "a" * 24},
                  {"nom": "apres-projet.jpg", "mime": "image/jpeg", "cle": "b" * 24}]

fusion = chat._pieces_persistables(PIECES_RECUES, PIECES_DU_TOUR)
verifier("chaque fichier reçu garde son nom et son type, dans l'ordre",
         [p["nom"] for p in fusion] == ["imagemaison.jpg", "clients.xlsx", "apres-projet.jpg"])
verifier("les photos reçoivent la clé sous laquelle le tour les a déposées (par le nom)",
         fusion[0]["cle"] == "a" * 24 and fusion[2]["cle"] == "b" * 24)
verifier("un fichier texte (Excel) n'a pas de clé, et n'est pas perdu pour autant",
         fusion[1]["cle"] is None and fusion[1]["nom"] == "clients.xlsx")
verifier("JAMAIS les octets : aucun `b64` ne traverse",
         all("b64" not in p for p in fusion))
verifier("sans retour du runtime (tour en échec), les noms restent",
         [p["cle"] for p in chat._pieces_persistables(PIECES_RECUES, None)] == [None, None, None])
verifier("sans pièce, une liste vide", chat._pieces_persistables([], PIECES_DU_TOUR) == [])

utilisateur = types.SimpleNamespace(id="u1", role="direction")
THREAD = "12345678-1234-5678-1234-567812345678"
asyncio.run(chat._persist_messages(utilisateur, THREAD, "dis moi la différence", "réponse", fusion))
verifier("l'échange est écrit en une seule salve", len(ECRITURES) == 1)
sql, lignes = ECRITURES[-1] if ECRITURES else ("", [])
verifier("l'INSERT porte la colonne metadata, castée en jsonb",
         "metadata" in sql and "$4::jsonb" in sql)
verifier("la question d'abord, la réponse ensuite — l'ordre du 01/09 est conservé",
         len(lignes) == 2 and lignes[0][1] == "user" and lignes[1][1] == "assistant")
meta = lignes[0][3] if lignes else None
verifier("les métadonnées sont SÉRIALISÉES en chaîne (asyncpg sans codec JSONB)",
         isinstance(meta, str))
try:
    lu = json.loads(meta or "{}")
except Exception:  # noqa: BLE001
    lu = None
verifier("…et se relisent : trois pièces, les clés des deux photos, rien pour l'Excel",
         isinstance(lu, dict) and [p["nom"] for p in lu.get("pieces", [])]
         == ["imagemaison.jpg", "clients.xlsx", "apres-projet.jpg"]
         and lu["pieces"][0]["cle"] == "a" * 24 and lu["pieces"][1]["cle"] is None)
verifier("la ligne de la réponse ne porte pas de métadonnées de pièces",
         len(lignes) == 2 and lignes[1][3] == "{}")

ECRITURES.clear()
asyncio.run(chat._persist_messages(utilisateur, THREAD, "bonjour", "salut"))
verifier("sans pièce, la question s'écrit avec des métadonnées vides — pas de `null`",
         ECRITURES and ECRITURES[-1][1][0][3] == "{}")

verifier("le POST passe les pièces à la persistance",
         "_pieces_persistables(pieces, result.get(\"pieces\"))" in chat_src)
verifier("le WebSocket capte les pièces sur `final` ET sur `pending_validation`",
         'if event.get("pieces"):' in chat_src
         and chat_src.count("_pieces_persistables(pieces, pieces_tour)") == 2)

# ══════════════════════════════════════════════════════════════════════════
# 2. LE RUNTIME — ce qu'il rend, sans les octets
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. Ce que le runtime rend")

import ast  # noqa: E402

runtime_src = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
arbre = ast.parse(runtime_src)
espace: dict = {}
for n in arbre.body:
    if isinstance(n, ast.FunctionDef) and n.name == "pieces_du_tour_persistables":
        exec(compile(ast.Module([n], []), "runtime.py", "exec"), espace)
fn = espace.get("pieces_du_tour_persistables")
verifier("la fonction existe dans le runtime", fn is not None)
if fn:
    etat = {"attachments": [
        {"nom": "a.jpg", "mime": "image/jpeg", "pages": ["BASE64…"], "cle": "c" * 24, "b64": "X"},
        {"nom": "casse.png", "erreur": "image illisible"},
        "pas un dict",
    ]}
    rendu = fn(etat)
    verifier("nom, type, clé — et rien d'autre (ni pages, ni b64)",
             rendu[0] == {"nom": "a.jpg", "mime": "image/jpeg", "cle": "c" * 24}
             and all(set(p) == {"nom", "mime", "cle"} for p in rendu))
    verifier("un fichier écarté par le prétraitement garde son nom, sans clé",
             rendu[1]["nom"] == "casse.png" and rendu[1]["cle"] is None)
    verifier("un état sans pièce rend une liste vide", fn({}) == [] and fn({"attachments": None}) == [])
verifier("les trois retours du runtime portent `pieces` (POST terminé / en attente, reprise, WS)",
         runtime_src.count('"pieces": pieces_du_tour_persistables(state)') >= 4)

# ══════════════════════════════════════════════════════════════════════════
# 3. L'ÉCRAN
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. L'écran")

composant = FRONTEND / "components" / "chat" / "PiecesJointes.tsx"
verifier("le composant PiecesJointes existe", composant.exists())
src_c = composant.read_text(encoding="utf-8") if composant.exists() else ""
verifier("une pièce se dessine depuis son CONTENU quand on vient de l'envoyer",
         "data:${piece.mime || \"image/jpeg\"};base64,${piece.b64}" in src_c)
verifier("…ou depuis sa CLÉ, lue avec le jeton de session (une <img> n'a pas d'en-tête)",
         "/api/visuels/${encodeURIComponent(piece.cle)}" in src_c
         and "Authorization: `Bearer ${backendToken}`" in src_c)
verifier("sans l'un ni l'autre, ou si le dépôt ne répond plus : une pastille nommée",
         "data-testid=\"piece-pastille\"" in src_c and "setAbsent(true)" in src_c
         and "extensionDe(piece.nom)" in src_c)
verifier("un PDF déposé (première page) se montre en vignette AVEC son extension par-dessus",
         "!estImage(piece) &&" in src_c)
verifier("l'URL d'objet est révoquée au démontage (pas de fuite mémoire par photo)",
         "URL.revokeObjectURL(objet)" in src_c)

liste = (FRONTEND / "components" / "chat" / "MessageList.tsx").read_text(encoding="utf-8")
verifier("la bulle de la personne montre ses pièces, AVANT le texte",
         "<PiecesJointes pieces={msg.pieces} apiUrl={apiUrl} backendToken={backendToken} />" in liste
         and liste.index("<PiecesJointes pieces={msg.pieces}") < liste.index("{msg.content}"))

chatwin = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("à l'envoi, la bulle reçoit le contenu des pièces (chat ET file d'attente)",
         chatwin.count("pieces: piecesAffichees(pieces)") == 2)
verifier("l'ancien en-tête « 📎 nom, nom » a disparu du code",
         "enTetePieces" not in chatwin)
verifier("au rechargement, les pièces sont relues dans `metadata`",
         "pieces: piecesDesMetadonnees(m.metadata)" in chatwin)
verifier("…que la colonne arrive en CHAÎNE ou en objet (asyncpg sans codec)",
         'typeof meta === "string" ? JSON.parse(meta) : meta' in chatwin)
verifier("un `metadata` abîmé ne casse pas le fil (try/catch, `undefined`)",
         "function piecesDesMetadonnees" in chatwin
         and chatwin[chatwin.index("function piecesDesMetadonnees"):].split("\n}\n")[0].count("catch") == 1)

barre = (FRONTEND / "components" / "chat" / "InputBar.tsx").read_text(encoding="utf-8")
verifier("la barre de saisie montre une vignette de l'image choisie, avant d'envoyer",
         'data-testid="piece-jointe-vignette"' in barre
         and 'f.mediaType?.startsWith("image/") && f.url?.startsWith("data:")' in barre)

# ══════════════════════════════════════════════════════════════════════════
# 4. L'EXPERT VISION NE REMONTRE PLUS LES PHOTOS — mais l'historique les garde
# ══════════════════════════════════════════════════════════════════════════
print("\n── 4. Pas de doublure sous la question")


class _GrapheDouble:
    def __init__(self, *a, **k):
        pass

    def add_node(self, *a, **k):
        pass

    def add_edge(self, *a, **k):
        pass

    def add_conditional_edges(self, *a, **k):
        pass

    def set_entry_point(self, *a, **k):
        pass

    def compile(self, *a, **k):
        return self


class _PorteDouble:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


_poser("langgraph")
_poser("langgraph.graph", StateGraph=_GrapheDouble, END="END")
_poser("langchain_core")
_poser("langchain_core.messages",
       SystemMessage=lambda content=None: types.SimpleNamespace(content=content),
       HumanMessage=lambda content=None: types.SimpleNamespace(content=content),
       AIMessage=lambda content=None: types.SimpleNamespace(content=content))
_poser("agents.state", AgentState=dict)
_poser("llm")
_poser("llm.concurrence", porte_llm=lambda: _PorteDouble())
_poser("llm.router", get_llm=lambda *a, **k: None,
       LLMTier=types.SimpleNamespace(STANDARD="standard", COMPLEX="complex"),
       get_vision_candidates=lambda: [])
_poser("PIL")
_poser("PIL.Image", open=lambda flux: None)
_poser("visuels")
_poser("visuels.depot", deposer_octets=lambda o, m: "cle")
_poser("security.anonymizer", anonymizer=types.SimpleNamespace(
    anonymize_chunks=lambda textes, carte: (list(textes), dict(carte or {}))))
SUITES_VUES: list = []
_poser("agents.suggestions",
       poser=lambda texte, suites: texte + ("\n\n[suites]" if suites else ""),
       suggestions_du_tour=lambda texte, *a, **k: SUITES_VUES.append(texte) or ["Retoucher"])

agent2 = _exec_module(BACKEND / "agents" / "agent2.py", "agent2_double")
DEUX = [{"nom": "imagemaison.jpg", "mime": "image/jpeg", "pages": ["AAA"], "cle": "a" * 24},
        {"nom": "apres-projet.jpg", "mime": "image/jpeg", "pages": ["BBB"], "cle": "b" * 24}]

for mode in ("releve", "reponse"):
    etat = {"query": "q", "attachments": DEUX, "vision_mode": mode,
            "vision_analysis": "Analyse.", "vision_reponse": "Réponse.", "vision_releve": None,
            "extracted_data": None, "raw_chunks": []}
    r = asyncio.run(agent2.prechiffrage_node(etat))
    ecran = r.get("final_response") or ""
    archive = (r.get("messages") or [None, types.SimpleNamespace(content="")])[1].content
    # En régime relevé, la phrase « les fichiers sont enregistrés : … » cite
    # encore les références en texte — c'est voulu. C'est le BLOC qui a quitté
    # l'écran.
    verifier(f"[{mode}] le bloc des photos reçues n'est plus À L'ÉCRAN",
             '"type": "visuel"' not in ecran
             and (mode == "releve" or ("a" * 24) not in ecran))
    verifier(f"[{mode}] …mais il est dans L'HISTORIQUE, avec les deux clés",
             '"type": "visuel"' in archive and ("a" * 24) in archive and ("b" * 24) in archive)
verifier("les suites se choisissent sur le tour ENTIER, bloc compris",
         SUITES_VUES and all('"type": "visuel"' in t for t in SUITES_VUES))
verifier("en régime relevé, la phrase « je peux produire une variante » reste à l'écran",
         "produire une variante" in (asyncio.run(agent2.prechiffrage_node(
             {"query": "analyse", "attachments": DEUX, "vision_mode": "releve",
              "vision_analysis": "Analyse.", "extracted_data": None, "raw_chunks": []}))
             .get("final_response") or ""))

# ══════════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
