"""
Banc « LES PIÈCES JOINTES NE DISPARAISSENT PLUS DU FIL » (08/09).

Export Symbiose du 08/09, fil « M. et Mme Camp » (cinq photos jointes et une
grosse demande, 06:36 → 06:54). Trois défauts, tous lus dans les traces :

  1. 06:46 — plan approuvé → « La demande n'a pas pu être traitée : aucune
     action n'a abouti ». La reprise repartait avec l'état du tour qui avait
     PROPOSÉ le plan (`tools_finished` levé, `tour_debut` de dix minutes) ;
     le prompt disait « plan approuvé, enchaîne » ET « phase terminée, aucun
     bloc d'action » ; l'action émise (`produire_document`) a été jetée.
  2. 06:50 — « qu'est-ce qui t'empêche… » → « aucun fichier n'a été joint à
     la conversation ». Le message de la vision (3 718 car.) était taillé à
     1 400 (tête + queue) et le bloc `visuel` des cinq photos — clés ET noms —
     tombait au milieu, omis. La consigne système ne donnait que des clés.
  3. la question de la personne entrait TROIS fois dans l'historique (vision,
     assistant après `passer_la_main`, reprise du plan).

CE QUE CE BANC PROUVE (les fonctions livrées sont EXÉCUTÉES, sans base ni
réseau) : la coupe épargne les blocs de référence ; la vision met le bloc en
queue ; un plan approuvé rouvre le tour à neuf ; la question n'entre qu'une
fois ; la consigne nomme les images et dit qu'elles SONT les pièces jointes.
Tombe sur la version d'avant dès la première ligne.
"""
import ast
import json
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def fonctions(chemin, noms, espace):
    """Exécute les fonctions nommées d'un module livré dans `espace`, sans importer le module."""
    src = chemin.read_text(encoding="utf-8")
    arbre = ast.parse(src)
    morceaux = []
    for n in arbre.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            morceaux.append(ast.get_source_segment(src, n))
    manquantes = [n for n in noms if not any(m.startswith(("def " + n, "async def " + n)) for m in morceaux)]
    if manquantes:
        return manquantes
    exec(compile("from __future__ import annotations\n" + "\n\n".join(morceaux), str(chemin), "exec"), espace)
    return []


class Msg:
    def __init__(self, type_, content):
        self.type, self.content = type_, content


print(f"\n═══ LES PIÈCES JOINTES NE DISPARAISSENT PLUS DU FIL — {BACKEND.parent}\n")

# ── 1. La coupe des messages épargne les blocs de référence ──
print("— la mémoire : un message long garde ses références")
sys.modules["config"] = types.ModuleType("config")
sys.modules["config"].settings = types.SimpleNamespace()
src_mem = BACKEND / "agents" / "memoire_conversation.py"
mem = types.ModuleType("memoire_double")
mem.__dict__["__file__"] = str(src_mem)
exec(compile(src_mem.read_text(encoding="utf-8"), str(src_mem), "exec"), mem.__dict__)

CLES = ["dd566702accb8815844deb3b", "69755b23ce4a866cb4d28c2b", "62bc123ad610b153a31e8f28",
        "86fc33852b6c05f1295d76db", "380143805afe2f91ddec91a2"]
NOMS = ["maison vue de face.jpeg", "plan avec mesures.jpeg", "terrain piscine.jpeg",
        "vue depuis la terrasse.jpeg", "vue jardin.jpeg"]
bloc = {"type": "visuel", "titre": "Les 5 fichiers reçus",
        "images": [{"cle": c, "legende": n} for c, n in zip(CLES, NOMS)]}
analyse = "Déroulé de chantier :\n\n" + "\n".join(f"- Phase {i} : décapage du sol végétal sur 115 m², "
                                                   "coffrage, ferraillage et coulage de la dalle." for i in range(1, 12))
releve = "[Relevé technique fait pendant ce tour, non montré à l'écran]\n" + "\n".join(
    f"- Image {i} ({n}) : vue axiale de la piscine avec margelles claires, clôture en fond." for i, n in enumerate(NOMS, 1))
# La forme EXACTE de prod : analyse, bloc, relevé (le bloc au milieu).
message_prod = analyse + "\n\n```ui\n" + json.dumps(bloc, ensure_ascii=False) + "\n```\n\n" + releve
verifier("le message d'essai a la forme de celui de prod (> 1400 car., bloc au milieu)",
         len(message_prod) > 1400 and 200 < message_prod.find("```ui") < len(message_prod) - 400)
taille = mem._tailler(message_prod, 1400)
verifier("taillé à 1400, les CINQ clés survivent", all(c in taille for c in CLES),
         f"{sum(c in taille for c in CLES)}/5")
verifier("…et les cinq NOMS de fichiers aussi", all(n in taille for n in NOMS))
verifier("le bloc est intact (JSON lisible, type visuel, 5 images)",
         (lambda m: bool(m) and json.loads(m.group(1)).get("type") == "visuel"
          and len(json.loads(m.group(1))["images"]) == 5)(re.search(r"```ui\n(\{.*?\})\n```", taille, re.S)))
verifier("la prose autour est bien coupée (tête + queue, omission dite)",
         "caractères omis" in taille and len(taille) < len(message_prod))
verifier("le bloc est en QUEUE du message taillé", taille.rstrip().endswith("```"))
court = "Bonjour, voici la photo.\n\n```ui\n" + json.dumps({"type": "visuel", "images": [{"cle": CLES[0]}]}) + "\n```"
verifier("un message court n'est pas touché", mem._tailler(court, 1400) == court)
sans_bloc = "x" * 3000
t2 = mem._tailler(sans_bloc, 1400)
verifier("sans bloc de référence, la coupe d'avant (tête + queue) est inchangée",
         "caractères omis" in t2 and len(t2) < 1600)
tableau = "Voici :\n\n```ui\n" + json.dumps({"type": "table", "rows": [["a"] * 30] * 40}) + "\n```" + "y" * 2000
t3 = mem._tailler(tableau, 1400)
verifier("un bloc SANS référence (tableau) n'est pas épargné : il se coupe comme de la prose",
         "caractères omis" in t3 and len(t3) < 1700)
gros = analyse + "".join("\n\n```ui\n" + json.dumps({"type": "visuel", "images": [{"cle": f"{i:024x}", "legende": "p"}] * 12}) + "\n```" for i in range(8))
t4 = mem._tailler(gros, 1400)
verifier("huit blocs de douze images : les premiers sont gardés, le surplus est DIT",
         "bloc(s) de référence omis" in t4 and len(t4) < 1400 + mem.BLOCS_EPARGNES_MAX_CHARS + 400)

# ── 2. La vision met le bloc des photos en queue ──
print("— la vision : le bloc des photos reçues ferme le message")
ag2 = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
i_bloc, i_releve = ag2.find("    summary += bloc_visuel"), ag2.find('summary += ("\\n\\n[Relevé technique fait pendant ce tour')
verifier("`summary += bloc_visuel` vient APRÈS l'ajout du relevé caché",
         i_bloc > 0 and i_releve > 0 and i_bloc > i_releve)
verifier("les suites se choisissent toujours bloc compris",
         "suggestions_du_tour(summary + bloc_visuel, [], expert=\"agent2\")" in ag2)

# ── 3. Un plan approuvé rouvre le tour ──
print("— la reprise après accord du plan")
rt = BACKEND / "agents" / "router.py"
esp = {}
manque = fonctions(rt, ["_reouverture_du_tour"], esp)
verifier("`_reouverture_du_tour` existe dans router.py", not manque, manque)
if not manque:
    neuf = esp["_reouverture_du_tour"]()
    verifier("elle rabaisse `tools_finished` (le prompt ne dira plus « phase terminée »)",
             neuf.get("tools_finished") is False)
    verifier("elle rabaisse `redaction_forcee`, `relance_annonce`, `note_sortie`, `pending_action`",
             neuf.get("redaction_forcee") is False and neuf.get("relance_annonce") is False
             and neuf.get("note_sortie") is None and neuf.get("pending_action") is None)
    verifier("elle remet la boucle à zéro (itérations, résultats, forçages, réparations)",
             neuf.get("tool_iterations") == 0 and neuf.get("tool_results") == []
             and neuf.get("forcages") == 0 and neuf.get("tool_repair_used") is False)
    import time as _t
    verifier("elle repart l'horloge du tour (les 8 minutes recommencent)",
             abs(float(neuf.get("tour_debut") or 0) - _t.time()) < 5)
src_rt = rt.read_text(encoding="utf-8")
branche = src_rt[src_rt.find('if action["skill"] == "proposer_plan" and isinstance(resultat, dict):'):][:900]
verifier("la branche du plan approuvé appelle la réouverture",
         "sortie.update(_reouverture_du_tour())" in branche)
verifier("…après avoir posé `plan_valide` et effacé la réponse d'accusé",
         'sortie["plan_valide"] = list(etapes)' in branche and 'sortie["llm_response"] = None' in branche)

# ── 4. L'assistant : la question une fois, les images nommées ──
print("— l'assistant : la question n'entre qu'une fois")
ag1 = BACKEND / "agents" / "agent1.py"
esp1 = {"_re_images": re, "_CLE_IMAGE_RE": re.compile(r'"cle"\s*:\s*"([0-9a-f]{16,64})"'),
        "AgentState": dict, "_retouche_disponible": lambda: True}
manque = fonctions(ag1, ["_question_deja_au_fil", "images_du_fil_nommees", "cles_images_du_fil",
                         "_consigne_images"], esp1)
verifier("les quatre fonctions existent dans agent1.py", not manque, manque)
if not manque:
    deja = esp1["_question_deja_au_fil"]
    q = "donc Voici nouveau prospect à transformer en client, Mr et Mme Camp…"
    fil = [Msg("human", "nouveau dossier"), Msg("ai", "…"), Msg("human", q), Msg("ai", "Déroulé de chantier…")]
    verifier("après `passer_la_main`, la question est le dernier message humain : on ne la rajoute pas",
             deja(fil, q) is True)
    verifier("une question identique posée PLUS TÔT (une réponse entre) n'est pas ce cas",
             deja([Msg("human", q), Msg("ai", "x"), Msg("human", "autre"), Msg("ai", "y")], q) is False)
    verifier("fil vide ou question vide : rien n'est « déjà là »", deja([], q) is False and deja(fil, "") is False)
    src1 = ag1.read_text(encoding="utf-8")
    zone = src1[src1.find('question_masquee = state.get("anonymized_query") or state.get("query", "")'):][:900]
    verifier("`rehydrate_node` s'en sert avant d'écrire l'historique",
             "_question_deja_au_fil(state.get(\"messages\"), question_masquee)" in zone
             and "AIMessage(content=text)" in zone)

    print("— l'assistant : les images ont un nom et SONT les pièces jointes")
    etat = {"messages": [Msg("human", q), Msg("ai", message_prod)], "tool_results": []}
    nommees = esp1["images_du_fil_nommees"](etat)
    verifier("les cinq images du fil sont rendues avec leur nom, dans l'ordre",
             nommees == list(zip(CLES, NOMS)), nommees)
    etat2 = {"messages": [], "attachments": [{"nom": "facade.jpg", "cle": "a" * 24}],
             "attachment_visuel_cles": ["a" * 24]}
    verifier("une photo jointe à CE tour est nommée par son fichier",
             esp1["images_du_fil_nommees"](etat2) == [("a" * 24, "facade.jpg")])
    consigne = esp1["_consigne_images"](etat)
    verifier("la consigne cite « clé (nom) » pour le plan",
             f"{CLES[1]} (plan avec mesures.jpeg)" in consigne)
    verifier("…dit que ce sont les fichiers REÇUS, les pièces jointes dont on parle",
             "fichiers REÇUS" in consigne and "pièces jointes" in consigne)
    verifier("…interdit « aucun fichier n'a été joint » et la chasse dans les mails",
             "ne dis jamais qu'aucun fichier n'a été joint" in consigne and "mails" in consigne)
    verifier("…garde la règle de retouche quand le moteur existe", "`modifier_visuel`" in consigne)
    esp1["_retouche_disponible"] = lambda: False
    consigne2 = esp1["_consigne_images"](etat)
    verifier("sans moteur d'images, même phrase sur les pièces jointes, sans retouche promise",
             "fichiers REÇUS" in consigne2 and "modifier_visuel" not in consigne2)
    verifier("sans image, aucune consigne", esp1["_consigne_images"]({"messages": []}) == "")

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
