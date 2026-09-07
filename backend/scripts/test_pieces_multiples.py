"""
Banc « PLUSIEURS PIÈCES JOINTES DANS UN MÊME MESSAGE » — relevé du 07/09.

LA DEMANDE (Noa, 07/09) : « on ne peut mettre qu'une seule pièce jointe à la
fois, alors qu'on devrait pouvoir en mettre plein et que ça les analyse toutes
correctement, une par une ».

CE QUE L'EXPORT LANGFUSE MONTRAIT (`1788787413385-lf-events-export-…json`) :
cinq photos envoyées à 10:02:23, 10:02:52, 10:03:05, 10:03:41 et 10:03:56 —
CINQ TOURS séparés, chacun titré « Analyse ce fichier : <nom> » par l'écran
lui-même. Puis, à 10:07 : « je veux que tu effectue ce photo montage sur toutes
les photos » → « Je réalise le photomontage sur la PREMIÈRE photo », un seul
`modifier_visuel`, et le tour s'arrête à la validation. Le lot n'a jamais
existé : il n'y avait que des tours successifs, chacun ignorant les autres.

CE QUE CE BANC PROUVE (sans base, sans réseau, sans navigateur) :
  · la réception accepte une LISTE de fichiers, et se replie sur les champs au
    singulier quand un client plus ancien n'en envoie qu'un ;
  · le plafond de dix est appliqué, et le surplus est DIT — jamais avalé ;
  · les textes sont concaténés SOUS LE NOM de leur fichier, et `@tableau` dit
    de quel tableau il porte les lignes quand il y en a plusieurs ;
  · le prétraitement prépare CHAQUE fichier, dépose CHAQUE photo, et un fichier
    illisible n'arrête pas les autres — il ressort avec sa raison ;
  · la vision fait UN APPEL PAR FICHIER, nomme le fichier dans sa consigne, et
    range chaque analyse sous son titre ;
  · UNE RÉPONSE VIDE EST UN ÉCHEC : le candidat suivant est essayé. C'est le
    défaut vu le 07/09 à 10:10 — `openrouter:google/gemini-2.5-pro` a rendu un
    contenu vide après 2 min 23 s sur `photo4.jpeg`, la cascade s'est arrêtée
    là, et la personne a lu « Aucune analyse disponible pour ce document ».
    La cascade TEXTE avait reçu ce correctif le 19/08 (`b553da9`) ; la cascade
    vision, jamais ;
  · un lot MIXTE (un tableau + des photos) part quand même à la vision ;
  · les références des photos du tour entrent TOUTES dans les images du fil ;
  · la file d'attente porte le lot, et sait relire une tâche mise en file AVANT
    ce déploiement (un seul fichier, ancienne forme sur le disque).

CE QU'IL NE PROUVE PAS : rien n'a été rendu dans un navigateur, aucun appel réel
n'a été fait à un modèle de vision, et Pillow est DOUBLÉ (il n'est pas installé
sur ce poste) — le décodage d'une vraie photo n'est donc pas exercé ici, seule
la mécanique qui l'entoure l'est.
"""
import asyncio
import json
import pathlib
import sys
import tempfile
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


print(f"\n═══ PLUSIEURS PIÈCES JOINTES — {BACKEND.parent}\n")

# ══════════════════════════════════════════════════════════════════════════
# LES DOUBLURES — tout ce que les deux modules importent, et rien de plus.
# ══════════════════════════════════════════════════════════════════════════

class SansSupport(Exception):
    pass


def _analyser(nom, brut):
    """Lecteur de fichiers doublé : le nom dit ce que le fichier contient."""
    if nom.endswith((".xlsx", ".csv")):
        return {"kind": "tabulaire",
                "columns": ["Nom", "E-mail"],
                "rows": [{"Nom": f"Client {i}", "E-mail": f"c{i}@ex.fr"} for i in range(3)]}
    if nom.endswith((".docx", ".txt")):
        return {"kind": "texte", "text": f"Contenu texte de {nom}. " * 40}
    raise SansSupport(nom)


_poser("ingestion")
_poser("ingestion.parsers", analyser=_analyser,
       ligne_en_texte=lambda l: json.dumps(l, ensure_ascii=False),
       famille=lambda nom: None if nom.endswith((".png", ".jpg", ".jpeg")) else "doc",
       FichierNonSupporte=SansSupport)


class _Champ:
    """Le strict nécessaire de pydantic : des attributs nommés, un model_dump."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def model_dump(self):
        return {k: v for k, v in self.__dict__.items()}


# ── routers/chat.py ───────────────────────────────────────────────────────
def _exec_module(chemin: pathlib.Path, nom: str):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    return mod


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
_poser("database.connection", get_db=None, get_rls_db=None)
_poser("security")
_poser("security.rbac", has_permission=lambda *a: True, SCHEDULE_EXEMPT_ROLES=())
_poser("security.audit", log_action=None)
_poser("agents")
_poser("agents.runtime", run_turn=None, stream_turn=None,
       FilOccupe=type("FilOccupe", (Exception,), {}))
_poser("config", settings=types.SimpleNamespace(max_body_mb=10))

chat = _exec_module(BACKEND / "routers" / "chat.py", "chat_double")
# La file d'attente lit le MÊME lecteur que le chat (`from routers.chat import
# _pieces_jointes`) : on lui donne celui qu'on vient d'exécuter, pas un autre.
_poser("routers")
sys.modules["routers.chat"] = chat

# ══════════════════════════════════════════════════════════════════════════
# 1. LA RÉCEPTION — une liste, un repli, un plafond qui se dit
# ══════════════════════════════════════════════════════════════════════════
print("── 1. La réception")

trois = [_Champ(nom="a.png", mime="image/png", b64="QQ=="),
         _Champ(nom="b.jpeg", mime="image/jpeg", b64="Qg=="),
         _Champ(nom="c.xlsx", mime="application/vnd.ms-excel", b64="Qw==")]
pieces, surplus = chat._normaliser_pieces(trois)
verifier("trois fichiers reçus font trois pièces, dans l'ordre",
         [p["nom"] for p in pieces] == ["a.png", "b.jpeg", "c.xlsx"] and surplus == 0)

pieces, _ = chat._normaliser_pieces(None, "seul.png", "image/png", "QQ==")
verifier("un client qui n'envoie que les champs au singulier marche encore",
         len(pieces) == 1 and pieces[0]["nom"] == "seul.png")

verifier("aucune pièce jointe → liste vide, pas d'exception",
         chat._normaliser_pieces(None) == ([], 0))

douze = [_Champ(nom=f"p{i}.png", mime="image/png", b64="QQ==") for i in range(12)]
pieces, surplus = chat._normaliser_pieces(douze)
verifier("le plafond de dix est appliqué, et le surplus est COMPTÉ",
         len(pieces) == chat.MAX_PIECES_JOINTES and surplus == 2)

verifier("un fichier sans contenu n'entre pas dans la liste",
         chat._normaliser_pieces([_Champ(nom="vide.png", mime="image/png", b64=None)]) == ([], 0))

# ── la lecture proprement dite ────────────────────────────────────────────
lot = [{"nom": "clients.xlsx", "mime": "x", "b64": "QQ=="},
       {"nom": "note.docx", "mime": "y", "b64": "Qg=="},
       {"nom": "jardin.png", "mime": "image/png", "b64": "Qw=="}]
texte, tableau, visuels = asyncio.run(chat._pieces_jointes(lot))

verifier("les fichiers visuels sont séparés des fichiers texte",
         [v["nom"] for v in visuels] == ["jardin.png"])
verifier("chaque texte est rangé SOUS LE NOM de son fichier",
         "=== Fichier joint : clients.xlsx ===" in texte
         and "=== Fichier joint : note.docx ===" in texte)
verifier("`@tableau` porte les lignes du tableau joint",
         tableau is not None and tableau["nom"] == "clients.xlsx" and len(tableau["lignes"]) == 3)

deux_tableaux = [{"nom": "un.xlsx", "mime": "x", "b64": "QQ=="},
                 {"nom": "deux.csv", "mime": "x", "b64": "Qg=="}]
texte2, tableau2, _ = asyncio.run(chat._pieces_jointes(deux_tableaux))
verifier("avec DEUX tableaux, le résultat dit lequel `@tableau` porte",
         "un.xlsx" in texte2 and "`@tableau` porte les lignes" in texte2
         and tableau2["nom"] == "un.xlsx")

texte3, _, _ = asyncio.run(chat._pieces_jointes(
    [{"nom": "note.docx", "mime": "y", "b64": "QQ=="}], surplus=3))
verifier("le surplus écarté est DIT à l'assistant, pas avalé",
         "3 fichier(s)" in texte3 and "n'ont PAS été lus" in texte3)

# LE COUPLE, PAS LA CHAÎNE SEULE — bug de production trouvé PAR CE BANC.
# Depuis le 03/09 (`83075d5`), `_piece_jointe` rendait un couple pour un tableau
# et une CHAÎNE NUE pour un Word / PDF texte / .txt. Le dépaquetage levait
# « too many values to unpack » : joindre un simple document au chat rendait
# « Une erreur est survenue ». Un Excel passait, un Word non.
texte_doc, tab_doc, vis_doc = asyncio.run(chat._pieces_jointes(
    [{"nom": "note.docx", "mime": "y", "b64": "QQ=="}]))
verifier("un document TEXTE seul est lu sans lever (Word, PDF texte, .txt)",
         isinstance(texte_doc, str) and "note.docx" in texte_doc and tab_doc is None)

verifier("un seul fichier ne porte pas d'en-tête inutile",
         "=== Fichier joint" not in (asyncio.run(chat._pieces_jointes(
             [{"nom": "note.docx", "mime": "y", "b64": "QQ=="}]))[0] or ""))

# ══════════════════════════════════════════════════════════════════════════
# 2. LE PRÉTRAITEMENT — chaque fichier, et un raté n'arrête pas les autres
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. Le prétraitement")


class _ImageDouble:
    """Pillow doublé : ni décodage réel, ni dépendance. Un octet 'X' est illisible."""

    def __init__(self, donnees):
        if b"X" in donnees:
            raise ValueError("image corrompue")
        self.width = 3000
        self.height = 2000

    def convert(self, mode):
        return self

    def resize(self, taille):
        self.width, self.height = taille
        return self

    def save(self, sortie, format=None, quality=None):
        sortie.write(b"JPEG-" + str(self.width).encode())


_poser("PIL")
_poser("PIL.Image", open=lambda flux: _ImageDouble(flux.getvalue()))

_deposees = []


def _deposer_octets(octets, mime):
    _deposees.append(octets)
    return f"cle{len(_deposees)}"


_poser("visuels")
_poser("visuels.depot", deposer_octets=_deposer_octets)


class _PorteDouble:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


_poser("llm")
_poser("llm.concurrence", porte_llm=lambda: _PorteDouble())
_poser("llm.router", get_llm=lambda *a, **k: None,
       LLMTier=types.SimpleNamespace(STANDARD="standard", COMPLEX="complex"),
       get_vision_candidates=lambda: [])
_poser("langchain_core")
_poser("langchain_core.messages",
       SystemMessage=lambda content=None: types.SimpleNamespace(content=content),
       HumanMessage=lambda content=None: types.SimpleNamespace(content=content),
       AIMessage=lambda content=None: types.SimpleNamespace(content=content))
class _GrapheDouble:
    """LangGraph n'est pas installé sur ce poste : on lui substitue un carnet.

    Le module construit son graphe À L'IMPORT — sans cette doublure, on ne
    pourrait pas exécuter une seule de ses fonctions ici.
    """

    def __init__(self, *a, **k):
        self.noeuds, self.aretes = {}, []

    def add_node(self, nom, fn=None):
        self.noeuds[nom] = fn

    def add_edge(self, a, b):
        self.aretes.append((a, b))

    def add_conditional_edges(self, *a, **k):
        self.aretes.append(a)

    def set_entry_point(self, nom):
        self.entree = nom

    def compile(self, *a, **k):
        return self


_poser("langgraph")
_poser("langgraph.graph", StateGraph=_GrapheDouble, END="END")
_poser("agents.state", AgentState=dict)

agent2 = _exec_module(BACKEND / "agents" / "agent2.py", "agent2_double")

import base64 as _b64

BON = _b64.b64encode(b"photo").decode()
CASSE = _b64.b64encode(b"X").decode()

verifier("un envoi d'un seul fichier devient une liste d'un élément",
         len(agent2.pieces_du_tour({"attachment_b64": BON, "attachment_name": "seul.png"})) == 1)
verifier("la liste du tour prime sur les champs au singulier",
         [p["nom"] for p in agent2.pieces_du_tour(
             {"attachments": [{"nom": "x.png", "b64": BON}], "attachment_b64": BON,
              "attachment_name": "vieux.png"})] == ["x.png"])
verifier("le prétraitement ne prend jamais plus de dix fichiers",
         len(agent2.pieces_du_tour({"attachments": [
             {"nom": f"{i}.png", "b64": BON} for i in range(15)]})) == agent2.MAX_PIECES)

fiche = agent2._preparer_piece({"nom": "jardin.png", "mime": "image/png", "b64": BON})
verifier("un fichier préparé rend ses pages et sa référence de dépôt",
         fiche.get("pages") and fiche.get("cle") and "erreur" not in fiche)

rate = agent2._preparer_piece({"nom": "casse.png", "mime": "image/png", "b64": CASSE})
verifier("un fichier illisible rend une RAISON, il ne lève pas",
         "erreur" in rate and rate["nom"] == "casse.png" and not rate.get("pages"))
verifier("un base64 invalide se dit aussi",
         "erreur" in agent2._preparer_piece({"nom": "x.png", "b64": "pas du base64 !!"}))

etat = asyncio.run(agent2.preprocess_attachment_node({"attachments": [
    {"nom": "a.png", "mime": "image/png", "b64": BON},
    {"nom": "casse.png", "mime": "image/png", "b64": CASSE},
    {"nom": "b.png", "mime": "image/png", "b64": BON},
]}))
verifier("les fichiers lisibles sont retenus, l'illisible est gardé de côté",
         [p["nom"] for p in etat["attachments"] if p.get("pages")] == ["a.png", "b.png"]
         and [p["nom"] for p in etat["attachments"] if not p.get("pages")] == ["casse.png"])
verifier("chaque photo retenue a SA référence de dépôt",
         len(etat["attachment_visuel_cles"]) == 2
         and len(set(etat["attachment_visuel_cles"])) == 2)
verifier("les champs au singulier désignent le PREMIER fichier (chemins hérités)",
         etat["attachment_name"] == "a.png"
         and etat["attachment_visuel_cle"] == etat["attachment_visuel_cles"][0])
verifier("aucun fichier lisible → on le dit, avec la raison, sans planter",
         "erreur" in str(asyncio.run(agent2.preprocess_attachment_node(
             {"attachments": [{"nom": "casse.png", "b64": CASSE}]})).get("llm_response", "")).lower()
         or "n'a pu être lu" in asyncio.run(agent2.preprocess_attachment_node(
             {"attachments": [{"nom": "casse.png", "b64": CASSE}]})).get("llm_response", ""))

# ══════════════════════════════════════════════════════════════════════════
# 3. LA VISION — un appel par fichier, et une réponse vide est un ÉCHEC
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. La vision, un fichier à la fois")


class _ModeleDouble:
    """Note ce qu'on lui demande, et rend ce qu'on lui a dit de rendre."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []

    async def ainvoke(self, messages, config=None):
        texte = messages[0].content[0]["text"]
        self.appels.append(texte)
        r = self.reponses.pop(0) if self.reponses else ""
        if isinstance(r, Exception):
            raise r
        return types.SimpleNamespace(content=r, usage_metadata={"input_tokens": 5, "output_tokens": 7})


def _etat_trois():
    return {"query": "analyse ces photos",
            "attachments": [
                {"nom": "photo3.jpeg", "mime": "image/jpeg", "pages": ["AAA"]},
                {"nom": "photo5.jpeg", "mime": "image/jpeg", "pages": ["BBB"]},
                {"nom": "MOLENE.png", "mime": "image/jpeg", "pages": ["CCC"]},
            ]}


bon = _ModeleDouble(["analyse 1", "analyse 2", "analyse 3"])
sys.modules["llm.router"].get_vision_candidates = lambda: [(bon, "modele:test")]
res = asyncio.run(agent2.vision_node(_etat_trois()))
verifier("trois fichiers = TROIS appels au modèle, pas un seul", len(bon.appels) == 3)
verifier("chaque appel NOMME son fichier et dit son rang",
         all(f"fichier {i + 1} sur 3" in a for i, a in enumerate(bon.appels))
         and "photo3.jpeg" in bon.appels[0] and "MOLENE.png" in bon.appels[2])
verifier("chaque appel dit d'analyser CELUI-CI seulement",
         all("Analyse CELUI-CI seulement" in a for a in bon.appels))
verifier("chaque analyse est rangée sous le titre de son fichier",
         "## photo3.jpeg" in res["vision_analysis"]
         and "## MOLENE.png" in res["vision_analysis"]
         and "analyse 2" in res["vision_analysis"])
verifier("les jetons des trois appels sont additionnés",
         res["tokens_in"] == 15 and res["tokens_out"] == 21)

# ── LE DÉFAUT DU 07/09 : le contenu vide pris pour une analyse ────────────
vide = _ModeleDouble([""])
secours = _ModeleDouble(["la vraie analyse"])
sys.modules["llm.router"].get_vision_candidates = lambda: [(vide, "premier:vide"),
                                                          (secours, "second:bon")]
res = asyncio.run(agent2.vision_node({
    "query": "réalise le photo montage sur cette photo",
    "attachments": [{"nom": "photo4.jpeg", "mime": "image/jpeg", "pages": ["AAA"]}]}))
verifier("UNE RÉPONSE VIDE EST UN ÉCHEC : le candidat suivant est essayé",
         len(secours.appels) == 1)
verifier("et c'est bien l'analyse du second qui sort",
         res["vision_analysis"] == "la vraie analyse" and res["model_used"] == "second:bon")
verifier("« Aucune analyse disponible » n'a plus de raison d'être ici",
         res.get("error") is None)

tous_vides = [(_ModeleDouble([""]), "a:vide"), (_ModeleDouble([""]), "b:vide")]
sys.modules["llm.router"].get_vision_candidates = lambda: tous_vides
res = asyncio.run(agent2.vision_node({
    "query": "q", "attachments": [{"nom": "photo4.jpeg", "pages": ["AAA"]}]}))
verifier("tous les candidats muets → un ÉCHEC déclaré, pas une analyse vide",
         res["error"] == "vision_failed" and res["vision_analysis"] is None
         and "photo4.jpeg" in res["llm_response"])

# ── un fichier réussit, un autre non : on ne tait pas le second ───────────
melange = _ModeleDouble(["ça marche", RuntimeError("504")])
sys.modules["llm.router"].get_vision_candidates = lambda: [(melange, "m:test")]
# « analyse » : le régime RELEVÉ, un appel par fichier — c'est lui qu'on
# éprouve ici. Une question précise partirait en UN appel (test_vision_reponse).
res = asyncio.run(agent2.vision_node({
    "query": "analyse ces deux photos",
    "attachments": [{"nom": "ok.jpeg", "pages": ["A"]}, {"nom": "ko.jpeg", "pages": ["B"]}]}))
verifier("un fichier qui échoue est NOMMÉ dans la réponse, pas passé sous silence",
         "Fichiers non analysés" in res["vision_analysis"] and "ko.jpeg" in res["vision_analysis"])
verifier("celui qui a réussi est quand même rendu",
         "## ok.jpeg" in res["vision_analysis"] and "ça marche" in res["vision_analysis"])

# ── les pages d'UN document restent ensemble ─────────────────────────────
pages = _ModeleDouble(["analyse du dossier"])
sys.modules["llm.router"].get_vision_candidates = lambda: [(pages, "p:test")]
asyncio.run(agent2.vision_node({
    "query": "q",
    "attachments": [{"nom": "dossier.pdf", "pages": ["A", "B", "C"],
                     "pages_totales": 9, "pages_ignorees": 6}]}))
verifier("les pages d'un même document partent dans UN SEUL appel",
         len(pages.appels) == 1)
verifier("le modèle sait combien de pages il voit, et combien lui manquent",
         "9 page(s)" in pages.appels[0] and "6 page(s) n'ont PAS été analysées" in pages.appels[0])

# ── le chemin hérité (file d'attente, tâche planifiée) ────────────────────
seul = _ModeleDouble(["analyse héritée"])
sys.modules["llm.router"].get_vision_candidates = lambda: [(seul, "h:test")]
res = asyncio.run(agent2.vision_node({"query": "q", "attachment_b64": "AAA",
                                      "attachment_name": "vieux.png"}))
verifier("un tour qui ne pose que les champs au singulier est analysé comme avant",
         res["vision_analysis"] == "analyse héritée" and len(seul.appels) == 1)
verifier("et un fichier seul ne porte pas de titre « ## » inutile",
         "##" not in res["vision_analysis"])

# ══════════════════════════════════════════════════════════════════════════
# 4. LE PRÉ-CHIFFRAGE — toutes les références, nommées
# ══════════════════════════════════════════════════════════════════════════
print("\n── 4. Les références rendues à l'écran")

agent2_src = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
verifier("le bloc d'écran porte TOUTES les photos du lot, avec leur légende",
         '"images": [{"cle": c, "legende": n} for n, c in photos]' in agent2_src)
verifier("les références sont nommées une à une quand il y en a plusieurs",
         '" ; ".join(f"{n} → `{c}`" for n, c in photos)' in agent2_src)
verifier("une seule photo garde exactement la phrase d'avant",
         "Photo enregistrée sous la référence" in agent2_src)

# ══════════════════════════════════════════════════════════════════════════
# 5. LE ROUTAGE ET LES IMAGES DU FIL
# ══════════════════════════════════════════════════════════════════════════
print("\n── 5. Le routage et les images du fil")

router_src = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
verifier("un lot MIXTE (un tableau + des photos) part quand même à la vision",
         'if state.get("attachments") or (has_attachment and not state.get("attachment_text")):'
         in router_src)

agent1_src = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
debut = agent1_src.index("_CLE_IMAGE_RE = ")
fin = agent1_src.index("def _apercu_avant_accord")
espace = {"re": __import__("re"), "_re_images": __import__("re"),
          "AgentState": dict, "__name__": "images_du_fil"}
exec(compile(agent1_src[debut:fin], "agent1.py", "exec"), espace)
cles_du_fil = espace["cles_images_du_fil"]

vues = cles_du_fil({"messages": [], "tool_results": [],
                    "attachment_visuel_cles": ["a" * 24, "b" * 24, "c" * 24]})
verifier("les TROIS photos du tour entrent dans les images du fil",
         vues == ["a" * 24, "b" * 24, "c" * 24])
verifier("le chemin hérité (une seule référence) marche toujours",
         cles_du_fil({"messages": [], "tool_results": [],
                      "attachment_visuel_cle": "d" * 24}) == ["d" * 24])
beaucoup = cles_du_fil({"messages": [], "tool_results": [],
                        "attachment_visuel_cles": [f"{i:024d}" for i in range(15)]})
verifier("la fenêtre garde douze références (dix photos + ce qui précède)",
         len(beaucoup) == 12 and beaucoup[-1] == f"{14:024d}")

# ══════════════════════════════════════════════════════════════════════════
# 6. LA FILE D'ATTENTE — le lot, et l'ancienne forme relue
# ══════════════════════════════════════════════════════════════════════════
print("\n── 6. La file d'attente")

file_src = (BACKEND / "routers" / "file_attente.py").read_text(encoding="utf-8")
debut = file_src.index("def _ranger_pieces(")
fin = file_src.index("async def requalifier_interrompues")
dossier = pathlib.Path(tempfile.mkdtemp())
espace = {"Optional": type(None), "logger": types.SimpleNamespace(
    warning=lambda *a, **k: None, info=lambda *a, **k: None),
    "_dossier_pieces": lambda: dossier, "__name__": "file_double"}
exec(compile(file_src[debut:fin], "file_attente.py", "exec"), espace)

body = _Champ(attachments=[{"nom": "a.png", "mime": "image/png", "b64": BON},
                           {"nom": "b.png", "mime": "image/png", "b64": BON}],
              attachment_name=None, attachment_mime=None, attachment_b64=None)
fiches = espace["_ranger_pieces"]("t1", body)
verifier("deux fichiers mis en file sont rangés sur le disque",
         len(fiches) == 2 and (dossier / "t1-0.bin").exists() and (dossier / "t1-1.bin").exists())
relues = espace["_reprendre_pieces"]("t1")
verifier("ils sont relus dans l'ordre, avec leur nom et leur contenu",
         [p["nom"] for p in relues] == ["a.png", "b.png"] and relues[0]["b64"] == BON)

# L'ANCIENNE FORME : une tâche mise en file AVANT ce déploiement.
(dossier / "t2.bin").write_bytes(b"photo")
(dossier / "t2.json").write_text(json.dumps({"nom": "vieux.png", "mime": "image/png"}),
                                 encoding="utf-8")
anciennes = espace["_reprendre_pieces"]("t2")
verifier("une tâche mise en file AVANT le déploiement s'exécute quand même",
         len(anciennes) == 1 and anciennes[0]["nom"] == "vieux.png" and anciennes[0]["b64"] == BON)

espace["_oublier_piece"]("t1")
verifier("les fichiers d'une tâche finie ne dorment pas sur le disque",
         not list(dossier.glob("t1*")))

verifier("le tour de la file reçoit la LISTE des visuels",
         "attachments=visuels or None):" in file_src)

# ══════════════════════════════════════════════════════════════════════════
# 7. L'ÉCRAN
# ══════════════════════════════════════════════════════════════════════════
print("\n── 7. L'écran")

inputbar = (FRONTEND / "components" / "chat" / "InputBar.tsx").read_text(encoding="utf-8")
chatwin = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
ws = (FRONTEND / "lib" / "ws.ts").read_text(encoding="utf-8")

verifier("le champ accepte plusieurs fichiers, avec la MÊME borne que le serveur",
         "multiple\n" in inputbar.replace("multiple={false}", "@@")
         and "maxFiles={MAX_FICHIERS}" in inputbar and "const MAX_FICHIERS = 10" in inputbar)
verifier("« Un seul fichier à la fois » a disparu de l'écran",
         "Un seul fichier à la fois" not in inputbar)
verifier("tous les fichiers déposés partent, pas seulement le premier",
         "message.files ?? []" in inputbar and "for (const f of fichiersJoints)" in inputbar)
verifier("un fichier illisible est NOMMÉ, et le lot ne part pas amputé",
         "n'a pas pu être lu" in inputbar and "f.filename" in inputbar)
verifier("sans question, l'intention par défaut dit COMBIEN et LESQUELS",
         "Analyse ces ${pieces.length} fichiers, un par un" in inputbar)
verifier("la bulle de la personne nomme les fichiers joints",
         "pieces.map((p) => p.name).join(\", \")" in chatwin)
verifier("le corps HTTP porte la liste ET les champs au singulier (déploiement décalé)",
         "attachments: pieces.map((p) => ({ nom: p.name, mime: p.mime, b64: p.b64 }))" in chatwin
         and "attachment_b64: pieces[0].b64" in chatwin)
verifier("la voie WebSocket transporte la liste elle aussi",
         "attachments?: { nom: string; mime: string; b64: string }[]" in ws)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
