"""
Banc « LA VISION RÉPOND À LA DEMANDE, PAS À L'IMAGE » — relevé du 07/09.

LE CAS (Noa, en prod, deux photos jointes) : « imagemaison.jpg,
apres-projet-b1be86d1.jpg — dis moi la différence entre ces deux images ».
Réponse : DEUX relevés de chiffrage complets (cartouche, inventaire zone par
zone, échelle, quantitatifs), la mention « pré-chiffrage indicatif », et
« je peux produire une variante de l'un d'eux » — jamais la différence.

Noa : « c'est pas parce qu'une image est présente dans un message qu'il doit
obligatoirement donner cette analyse et la liste des travaux qu'on peut faire ;
il doit juste donner la réponse à notre demande, de façon synthétique, pas de
blabla. Si pour une bonne qualité l'IA a besoin de faire cette analyse, elle
la fait, mais on n'a pas besoin de la voir. »

TROIS CAUSES, dans `agents/agent2.py` :
  · le préprompt du chiffrage était la SEULE consigne, quelle que soit la demande ;
  · un appel PAR FICHIER, chacun sommé d'« analyser CELUI-CI seulement » :
    comparer deux images était impossible par construction ;
  · `prechiffrage_node` habillait tout en pré-chiffrage.

CE QUE CE BANC PROUVE, le module livré EXÉCUTÉ contre un modèle doublé :
  · la demande décide du régime : un mot du relevé (« analyse », « chiffre »,
    « devis »…) ou rien du tout → RELEVÉ ; une question ou une consigne
    précise → RÉPONSE ;
  · en régime réponse, UN appel porte TOUTES les images, nommées dans l'ordre,
    et la consigne est de répondre à la demande, à elle seule ;
  · le brouillon [RELEVE]…[/RELEVE] est retiré de l'écran et gardé dans
    l'historique du fil ;
  · `prechiffrage_node` en régime réponse ne montre ni mention de
    pré-chiffrage, ni extraction, ni comparables, ni proposition de variante ;
    le bloc des photos reçues quitte l'écran (la bulle de la personne les
    montre) mais reste dans l'historique, où les filets le lisent ;
  · le régime relevé est INCHANGÉ (un appel par fichier, le préprompt du
    chiffrage, la mention) ;
  · le graphe saute l'extraction et les comparables en régime réponse.

CE QU'IL NE PROUVE PAS : aucun modèle de vision réel n'a été appelé — la
qualité de la réponse à « la différence » se juge en prod.

Tombe sur la version d'avant dès la première ligne (`demande_un_releve` absent).
"""
import asyncio
import json
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
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


print(f"\n═══ LA VISION RÉPOND À LA DEMANDE — {BACKEND.parent}\n")

# ══════════════════════════════════════════════════════════════════════════
# LES DOUBLURES — ce que le module importe, rien de plus.
# ══════════════════════════════════════════════════════════════════════════


class _GrapheDouble:
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
_poser("agents")
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
# Le masquage est doublé à l'identité : ce banc ne juge pas l'anonymiseur.
_poser("security")
_poser("security.anonymizer", anonymizer=types.SimpleNamespace(
    anonymize_chunks=lambda textes, carte: (list(textes), dict(carte or {}))))
_poser("agents.suggestions",
       poser=lambda texte, suites: texte + ("\n\n[suites]" if suites else ""),
       suggestions_du_tour=lambda *a, **k: ["Chiffrer ce projet"])
_poser("config", settings=types.SimpleNamespace(browser_enabled=False))

agent2 = _exec_module(BACKEND / "agents" / "agent2.py", "agent2_double")
# L'OFFRE VISUELLE EST SUPPOSÉE PRÉSENTE ICI (08/09) : la phrase « je peux
# produire une variante » ne se dit plus que là où `modifier_visuel` existe
# (le registre fait foi). Ce banc juge le régime de la vision, pas l'offre :
# on la déclare présente, et `test_images_selon_offre` juge l'autre cas.
agent2._retouche_disponible = lambda: True
src = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")


class _ModeleDouble:
    """Note ce qu'on lui demande (texte ET nombre d'images), rend ce qu'on lui dit."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.appels = []

    async def ainvoke(self, messages, config=None):
        contenu = messages[0].content
        self.appels.append({"texte": contenu[0]["text"],
                            "images": len([c for c in contenu if c.get("type") == "image_url"])})
        r = self.reponses.pop(0) if self.reponses else ""
        if isinstance(r, Exception):
            raise r
        return types.SimpleNamespace(content=r, usage_metadata={"input_tokens": 5, "output_tokens": 7})


# ══════════════════════════════════════════════════════════════════════════
# 1. LA DEMANDE DÉCIDE DU RÉGIME
# ══════════════════════════════════════════════════════════════════════════
print("── 1. La demande décide du régime")

releve = agent2.demande_un_releve
verifier("sans un mot (fichier joint seul) → le relevé", releve("") and releve(None) and releve("   "))
verifier("le titre que l'écran pose lui-même → le relevé",
         releve("Analyse ce fichier : maison.jpg")
         and releve("Analyse ces 3 fichiers, un par un"))
verifier("« chiffre », « devis », « décris », « combien ça coûte » → le relevé",
         releve("chiffre-moi ce plan") and releve("prépare le devis à partir de ce plan")
         and releve("décris cette photo") and releve("combien ça coûte ?"))
# LE CAS DE PROD : une question qui met deux images en rapport.
verifier("« dis moi la différence entre ces deux images » → une RÉPONSE, pas un relevé",
         not releve("dis moi la différence entre ces deux images"))
verifier("une question précise → une réponse",
         not releve("c'est quoi cette plante ?")
         and not releve("combien de fenêtres sur la façade ?")
         and not releve("quelle est la surface de la pelouse ?"))
verifier("une consigne de retouche ou de suite → une réponse (l'assistant enchaîne)",
         not releve("ajoute une pergola à droite")
         and not releve("prépare le mail de réponse au client"))

# ══════════════════════════════════════════════════════════════════════════
# 2. LE BROUILLON SE SÉPARE DE LA RÉPONSE
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. Le brouillon [RELEVE] se sépare de la réponse")

sep = agent2._separer_releve
verifier("sans balise, tout est réponse", sep("La piscine est nouvelle.") == ("", "La piscine est nouvelle."))
verifier("le brouillon est retiré, la réponse gardée",
         sep("[RELEVE]inventaire long[/RELEVE]\n\nLa piscine est nouvelle.")
         == ("inventaire long", "La piscine est nouvelle."))
verifier("la balise accentuée est reconnue aussi",
         sep("[RELEVÉ]x[/RELEVÉ] réponse")[1] == "réponse")
verifier("une balise jamais fermée ne cache rien (la balise seule est retirée)",
         sep("[RELEVE]tout le texte") == ("", "tout le texte"))
verifier("tout dans le brouillon, rien après → le brouillon EST la réponse",
         sep("[RELEVE]seule chose écrite[/RELEVE]") == ("", "seule chose écrite"))

# ══════════════════════════════════════════════════════════════════════════
# 3. LE RÉGIME RÉPONSE — un appel, toutes les images, la demande pour consigne
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. Le régime réponse, sur le cas de prod")

DEUX = [{"nom": "imagemaison.jpg", "mime": "image/jpeg", "pages": ["AAA"], "cle": "a" * 24},
        {"nom": "apres-projet-b1be86d1.jpg", "mime": "image/jpeg", "pages": ["BBB"], "cle": "b" * 24}]
QUESTION = "dis moi la différence entre ces deux images"

modele = _ModeleDouble([
    "[RELEVE]Image 1 : pelouse, massif, allée gravier. Image 2 : idem plus piscine.[/RELEVE]\n\n"
    "La seconde image ajoute une piscine rectangulaire avec ses margelles claires à la place "
    "d'une partie de la pelouse ; tout le reste (maison, garage, massif, haie) est identique."])
sys.modules["llm.router"].get_vision_candidates = lambda: [(modele, "modele:test")]
res = asyncio.run(agent2.vision_node({"query": QUESTION, "attachments": DEUX}))

verifier("deux images + une question → UN SEUL appel", len(modele.appels) == 1, modele.appels)
verifier("cet appel porte les DEUX images", modele.appels and modele.appels[0]["images"] == 2)
texte = modele.appels[0]["texte"] if modele.appels else ""
verifier("les images sont nommées dans l'ordre",
         "image 1 = « imagemaison.jpg »" in texte and "image 2 = « apres-projet-b1be86d1.jpg »" in texte)
verifier("la consigne est de répondre à la demande, à elle seule",
         f"Demande de l'utilisateur : {QUESTION}" in texte and "à elle seule" in texte)
verifier("le préprompt du CHIFFRAGE n'est pas dans la consigne",
         "CARTOUCHE" not in texte and "INVENTAIRE EXHAUSTIF" not in texte
         and "Analyse CELUI-CI seulement" not in texte)
verifier("les images en rapport sont regardées ENSEMBLE", "ENSEMBLE" in texte)
verifier("le régime est dit dans l'état", res.get("vision_mode") == "reponse")
verifier("la réponse montrée est SANS le brouillon",
         res.get("vision_reponse", "").startswith("La seconde image ajoute une piscine")
         and "[RELEVE]" not in res["vision_reponse"] and "pelouse, massif" not in res["vision_reponse"])
verifier("le brouillon est gardé à part", res.get("vision_releve", "").startswith("Image 1 : pelouse"))
verifier("l'analyse complète (pour l'assistant) porte les deux",
         "piscine rectangulaire" in res["vision_analysis"] and "non montré à l'écran" in res["vision_analysis"]
         and "pelouse, massif" in res["vision_analysis"])
verifier("le texte que l'écran reçoit est la réponse", res.get("llm_response") == res.get("vision_reponse"))

# sans brouillon : tout est réponse
simple = _ModeleDouble(["Un érable du Japon (Acer palmatum), à feuillage pourpre."])
sys.modules["llm.router"].get_vision_candidates = lambda: [(simple, "m:test")]
res1 = asyncio.run(agent2.vision_node({"query": "c'est quoi cette plante ?",
                                       "attachments": [DEUX[0]]}))
verifier("une question sur UNE photo : un appel, la réponse telle quelle, pas de brouillon",
         len(simple.appels) == 1 and res1["vision_reponse"].startswith("Un érable")
         and res1.get("vision_releve") is None and res1["vision_analysis"] == res1["vision_reponse"])
verifier("avec une seule image, on ne numérote pas", "image 1 =" not in simple.appels[0]["texte"])

# un fichier illisible est DIT, au modèle et à la personne
avec_rate = _ModeleDouble(["réponse"])
sys.modules["llm.router"].get_vision_candidates = lambda: [(avec_rate, "m:test")]
res2 = asyncio.run(agent2.vision_node({"query": "quelle photo est la plus récente ?",
                                       "attachments": DEUX + [{"nom": "casse.png", "erreur": "image corrompue"}]}))
verifier("un fichier illisible est dit au modèle (il ne le voit pas) et à la personne",
         "casse.png" in avec_rate.appels[0]["texte"] and "casse.png" in res2["vision_reponse"]
         and avec_rate.appels[0]["images"] == 2)

# tous les candidats muets → un échec déclaré
muets = [(_ModeleDouble([""]), "a:vide"), (_ModeleDouble([RuntimeError("504")]), "b:mort")]
sys.modules["llm.router"].get_vision_candidates = lambda: muets
res3 = asyncio.run(agent2.vision_node({"query": QUESTION, "attachments": DEUX}))
verifier("tous les candidats en échec → vision_failed, les fichiers nommés",
         res3.get("error") == "vision_failed" and res3.get("vision_analysis") is None
         and "imagemaison.jpg" in res3["llm_response"])

# ══════════════════════════════════════════════════════════════════════════
# 4. LE RÉGIME RELEVÉ — inchangé
# ══════════════════════════════════════════════════════════════════════════
print("\n── 4. Le régime relevé, inchangé")

complet = _ModeleDouble(["relevé 1", "relevé 2"])
sys.modules["llm.router"].get_vision_candidates = lambda: [(complet, "m:test")]
res4 = asyncio.run(agent2.vision_node({"query": "analyse ces photos", "attachments": DEUX}))
verifier("« analyse » : un appel PAR fichier, une image chacun",
         len(complet.appels) == 2 and all(a["images"] == 1 for a in complet.appels))
verifier("avec le préprompt du chiffrage",
         all("CARTOUCHE" in a["texte"] for a in complet.appels))
verifier("le régime est dit : relevé", res4.get("vision_mode") == "releve"
         and res4.get("vision_reponse") is None)

# ══════════════════════════════════════════════════════════════════════════
# 5. L'ÉCRAN — prechiffrage_node dans les deux régimes
# ══════════════════════════════════════════════════════════════════════════
print("\n── 5. Ce que l'écran montre")

etat_reponse = {
    "query": QUESTION,
    "vision_mode": "reponse",
    "vision_reponse": "La seconde image ajoute une piscine rectangulaire.",
    "vision_releve": "RELEVE SECRET : pelouse 60 à 80 m².",
    "vision_analysis": "La seconde image ajoute une piscine rectangulaire.\n\n[Relevé…]\nRELEVE SECRET",
    "extracted_data": {"surfaces_m2": {"pelouse": 70}, "postes_travaux": ["dépose terrasse"]},
    "raw_chunks": ["Chantier Villa Pereire : piscine 8 × 4."],
    "attachments": DEUX,
}
r = asyncio.run(agent2.prechiffrage_node(dict(etat_reponse)))
ecran = r.get("final_response") or ""
verifier("la réponse est à l'écran", "ajoute une piscine rectangulaire" in ecran)
verifier("PAS de mention « pré-chiffrage indicatif »", "Pré-chiffrage indicatif" not in ecran)
verifier("PAS d'extraction, PAS de comparables",
         "dépose terrasse" not in ecran and "Villa Pereire" not in ecran and "70" not in ecran)
verifier("PAS le brouillon", "RELEVE SECRET" not in ecran)
verifier("PAS de « je peux produire une variante »",
         "produire une variante" not in ecran and "enregistrés" not in ecran)
# LE BLOC DES PHOTOS N'EST PLUS À L'ÉCRAN (07/09 soir) : la bulle de la personne
# montre déjà ce qu'elle a joint. Il reste dans l'historique, où les filets
# (`cles_images_du_fil`, `fichiers_du_fil`) le lisent — contrôlé plus bas.
verifier("le bloc des photos reçues n'est PLUS remontré à l'écran",
         '"type": "visuel"' not in ecran and "Les 2 fichiers reçus" not in ecran)
verifier("les suites proposées restent", "[suites]" in ecran)
archive = r.get("messages") or []
verifier("l'historique du fil porte la question ET la réponse",
         len(archive) == 2 and archive[0].content == QUESTION
         and "ajoute une piscine" in archive[1].content)
verifier("…ET le brouillon, marqué comme non montré",
         "RELEVE SECRET" in archive[1].content and "non montré à l'écran" in archive[1].content)
verifier("…ET le bloc des photos, avec leurs clés (c'est là que les filets le lisent)",
         '"type": "visuel"' in archive[1].content and ("a" * 24) in archive[1].content
         and ("b" * 24) in archive[1].content)
verifier("mais pas les suites (libellés d'écran)", "[suites]" not in archive[1].content)
verifier("aucune validation demandée", r.get("requires_validation") is False)

etat_releve = dict(etat_reponse, vision_mode="releve", vision_reponse=None, vision_releve=None,
                   vision_analysis="Analyse complète : pelouse 60 à 80 m².")
r2 = asyncio.run(agent2.prechiffrage_node(etat_releve))
ecran2 = r2.get("final_response") or ""
verifier("en régime relevé, la mention, l'extraction et les comparables sont là comme avant",
         "Pré-chiffrage indicatif" in ecran2 and "dépose terrasse" in ecran2 and "Villa Pereire" in ecran2)
verifier("…et la proposition de variante aussi", "produire une variante" in ecran2)

etat_ancien = {"vision_analysis": "Analyse d'avant.", "extracted_data": None, "raw_chunks": []}
r3 = asyncio.run(agent2.prechiffrage_node(etat_ancien))
verifier("un état sans régime (tour d'avant, file d'attente) est traité en relevé",
         "Pré-chiffrage indicatif" in (r3.get("final_response") or ""))

# ══════════════════════════════════════════════════════════════════════════
# 6. LE GRAPHE ET L'ÉTAT
# ══════════════════════════════════════════════════════════════════════════
print("\n── 6. Le graphe et l'état")

verifier("une réponse va droit à l'écran, un relevé passe par l'extraction",
         agent2.apres_vision({"vision_mode": "reponse"}) == "prechiffrage"
         and agent2.apres_vision({"vision_mode": "releve"}) == "extraction"
         and agent2.apres_vision({}) == "extraction")
verifier("l'arête « vision → extraction » est devenue conditionnelle",
         'graph.add_edge("vision", "extraction")' not in src
         and '"vision",\n        apres_vision' in src)
verifier("ses deux sorties sont des nœuds du graphe",
         'graph.add_node("extraction"' in src and 'graph.add_node("prechiffrage"' in src)
etat_src = (BACKEND / "agents" / "state.py").read_text(encoding="utf-8")
verifier("l'état déclare les trois champs du régime",
         all(f"{c}: Optional[str]" in etat_src for c in ("vision_mode", "vision_reponse", "vision_releve")))
runtime_src = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
verifier("le régime est remis à zéro à chaque tour (il ne file pas d'un tour à l'autre)",
         '"vision_mode": None' in runtime_src)
# Export du 07/09 : « affiche cette image » archivé sous « ajoute une piscine
# sur le devant » — la question masquée du tour d'AVANT, jamais remise à zéro,
# relue telle quelle par la vision (qui n'a pas de nœud d'anonymisation).
verifier("la question masquée du tour d'avant ne file pas dans l'archive de la vision",
         '"anonymized_query": None' in runtime_src)
verifier("la consigne de réponse existe et dit l'essentiel",
         "à elle seule" in agent2.REPONSE_PROMPT and "[RELEVE]" in agent2.REPONSE_PROMPT
         and "sans introduction" in agent2.REPONSE_PROMPT
         and "ne dis pas que tu ne peux pas" in agent2.REPONSE_PROMPT)

# ══════════════════════════════════════════════════════════════════════════
print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
