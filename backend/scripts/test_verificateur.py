"""
Banc du VÉRIFICATEUR — la relecture par le modèle avant l'écran (15/09).

Demande de Noa : « c'est trop déterministe ce que tu as fait, il y a plein de
cas qu'on n'a pas traités ». Les filets de `annonce.py` reconnaissent chacun
UNE formulation d'UN défaut ; le vérificateur confie le jugement au modèle
puissant : la réponse affirme-t-elle ce que le tour ne prouve pas ?

CE QUE CE BANC PROUVE (sans réseau, avec un relecteur doublé) :
  · le module pur : quand relire (un geste, ou une affirmation d'acte — jamais
    un « bonjour », jamais deux fois, jamais une carte d'accord) ; lire le
    verdict (un « a_corriger » sans motif ne réécrit rien, un texte illisible
    vaut indisponible) ; la suite (forcer le geste manquant s'il existe et que
    le budget le permet, sinon rédiger) ;
  · `verifier_node` EXÉCUTÉ sur les tours du 15/09 : « la signature a bien été
    apprise » sur un résultat qui montre la signature d'une cliente → rédaction
    reprise, avec ce que le relecteur a vu et la réponse relue ; « le brouillon
    est dans votre boîte » sans aucun geste → le geste manquant est forcé ; la
    seconde arrivée laisse passer ; un relecteur en panne laisse passer ;
  · le câblage du graphe, de la rédaction reprise, du forceur, du réglage.
Tombe sur la version d'avant (module absent).

Usage : python backend/scripts/test_verificateur.py [backend]
"""
import ast
import asyncio
import json
import logging
import pathlib
import re
import sys
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    for n in arbre.body:
        cibles = n.targets if isinstance(n, ast.Assign) else []
        if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms) or any(
                isinstance(c, ast.Name) and c.id in noms for c in cibles):
            exec(compile(ast.Module(body=[n], type_ignores=[]), str(chemin), "exec"), espace)
    return [x for x in noms if x not in espace]


print("1. Le module pur")
try:
    import importlib
    V = importlib.import_module("agents.verificateur")
except Exception as e:  # noqa: BLE001
    V = None
    verifier("agents/verificateur.py existe", False, e)

if V:
    verifier("« Bonjour, que puis-je faire ? » sans geste : rien à relire",
             not V.a_verifier("Bonjour, que puis-je faire pour vous ?", False, False, False))
    verifier("une affirmation d'acte sans geste se relit",
             V.a_verifier("Le brouillon a bien été créé dans votre boîte mail.", False, False, False))
    verifier("un tour qui a agi se relit", V.a_verifier("Voilà.", True, False, False))
    verifier("jamais deux fois, jamais sur une carte d'accord",
             not V.a_verifier("C'est envoyé.", True, True, False)
             and not V.a_verifier("C'est envoyé.", True, False, True))
    verifier("un verdict ok se lit", V.lire_verdict('{"verdict": "ok", "problemes": []}')["statut"] == "ok")
    v = V.lire_verdict('Voici : {"verdict": "a_corriger", "problemes": [{"affirmation": "a", "raison": "b"}], '
                       '"action_manquante": "deposer_brouillon", "consigne": "dis-le"}')
    verifier("un verdict à corriger se lit, entouré de texte", v["statut"] == "a_corriger"
             and v["action_manquante"] == "deposer_brouillon" and v["problemes"])
    verifier("« a_corriger » sans motif ne réécrit rien",
             V.lire_verdict('{"verdict": "a_corriger", "problemes": []}')["statut"] == "ok")
    verifier("un texte illisible : None", V.lire_verdict("je ne sais pas") is None)
    connus = {"deposer_brouillon", "apprendre_signature"}
    verifier("geste manquant connu, budget disponible → forcer",
             V.suite(v, connus, 0, 2, False) == "forcer")
    verifier("geste manquant inconnu → rédiger",
             V.suite({**v, "action_manquante": "geste_invente"}, connus, 0, 2, False) == "rediger")
    verifier("budget de forçage épuisé → rédiger", V.suite(v, connus, 2, 2, False) == "rediger")
    verifier("verdict ok → afficher", V.suite({"statut": "ok"}, connus, 0, 2, False) == "rehydrate")
    txt = V.pour_la_redaction(v)
    verifier("la rédaction reprise reçoit ce que le relecteur a vu", "RELECTEUR" in txt and "a" in txt and "dis-le" in txt)
    c = V.consigne("apprends ma signature", "1. apprendre_signature() → ok", "- apprendre_signature : …",
                   "La signature a bien été apprise.", ["keyvalue · Signature"], lecons="- Quand …")
    verifier("la consigne borne le relecteur (pas le style, dans le doute ok) et porte les leçons",
             "Ne relève PAS : le style" in c and "Dans le doute, le verdict est « ok »" in c and "LEÇONS" in c)

print("2. verifier_node exécuté")
APPELS = []


class _Rep:
    def __init__(self, content):
        self.content = content


class _LLM:
    verdict = '{"verdict": "ok", "problemes": []}'
    panne = False

    async def ainvoke(self, messages, config=None):
        APPELS.append(messages[0].content)
        if _LLM.panne:
            raise RuntimeError("fournisseur indisponible")
        return _Rep(_LLM.verdict)


class _Journal:
    def info(self, *a, **k):
        pass
    warning = debug = info


sys.modules["config"] = types.SimpleNamespace(settings=types.SimpleNamespace(
    verifier_reponses=True, verificateur_delai_s=5))
module_skills_protocol = types.ModuleType("skills.protocol")
module_skills_protocol.catalogue = lambda role=None: {"deposer_brouillon": ("", [], []),
                                                      "apprendre_signature": ("", [], [])}
sys.modules["skills.protocol"] = module_skills_protocol
esp = {"logger": _Journal(), "get_llm": lambda tier: _LLM(), "LLMTier": types.SimpleNamespace(COMPLEX="complex"),
       "HumanMessage": lambda content: types.SimpleNamespace(content=content),
       "_tracer_filet": lambda *a, **k: None, "MAX_FORCAGES_PAR_TOUR": 2,
       "_re_livrables": re, "AgentState": dict}
manque = extraire(racine / "agents" / "agent1.py",
                  {"verifier_node", "route_apres_verifier", "_BLOC_UI_RE", "_blocs_de"}, esp)
# Le texte visible et la compaction des résultats ont leurs propres bancs : ici,
# on juge la relecture, pas eux.
esp["_texte_visible"] = lambda t: t
esp["_essentiel"] = lambda t, budget=8000: str(t)[:budget]
verifier("agent1 porte verifier_node et route_apres_verifier",
         "verifier_node" in esp and "route_apres_verifier" in esp, manque)
if "verifier_node" in esp:
    RESULTAT_SIGNATURE = {"skill": "apprendre_signature", "ok": True, "args": {"ref": "ref-recu"},
                          "resultat_masque": json.dumps({"boite": "contact@exemple-paysage.fr", "signature": {
                              "texte": "RSE - FORMATION\ncliente.exemple@gmail.com", "source": "message RE: Relance"}})}
    etat = {"query": "oui", "llm_response": ("La signature a bien été apprise depuis votre dernier message "
                                             "envoyé. Elle sera apposée à chaque envoi."),
            "tool_results": [RESULTAT_SIGNATURE], "user_role": "administratif", "forcages": 0}
    _LLM.verdict = json.dumps({"verdict": "a_corriger", "problemes": [
        {"affirmation": "la signature de la boîte est apprise",
         "raison": "le résultat porte l'adresse d'une cliente : ce n'est pas la signature de la boîte"}],
        "action_manquante": "", "consigne": "Dis que la signature apprise est celle d'une cliente."})
    r = asyncio.run(esp["verifier_node"](etat))
    verifier("« la signature a bien été apprise » sur la signature d'une cliente : à corriger",
             (r.get("verification") or {}).get("statut") == "a_corriger" and APPELS, r)
    verifier("le relecteur a reçu la demande, le journal et le résultat",
             APPELS and "apprendre_signature" in APPELS[-1] and "cliente.exemple@gmail.com" in APPELS[-1])
    etat2 = {**etat, **r}
    verifier("→ la rédaction est reprise", esp["route_apres_verifier"](etat2) == "rediger")
    verifier("… avec la réponse relue gardée pour la réécriture",
             "bien été apprise" in (r["verification"].get("reponse_relue") or ""))
    r2 = asyncio.run(esp["verifier_node"](etat2))
    verifier("la seconde arrivée laisse passer (une relecture par tour)",
             r2["verification"]["statut"] == "deja_verifiee" and esp["route_apres_verifier"]({**etat2, **r2}) == "rehydrate")

    APPELS.clear()
    _LLM.verdict = json.dumps({"verdict": "a_corriger", "problemes": [
        {"affirmation": "le brouillon est dans la boîte", "raison": "aucun geste n'a déposé de brouillon"}],
        "action_manquante": "deposer_brouillon", "consigne": ""})
    etat3 = {"query": "mets-le dans mes brouillons", "tool_results": [], "forcages": 0,
             "llm_response": "C'est fait : le brouillon est enregistré dans vos brouillons Outlook."}
    r3 = asyncio.run(esp["verifier_node"](etat3))
    verifier("« c'est fait, dans vos brouillons » sans geste : le geste manquant est forcé",
             esp["route_apres_verifier"]({**etat3, **r3}) == "forcer", r3)

    APPELS.clear()
    r4 = asyncio.run(esp["verifier_node"]({"query": "bonjour", "llm_response": "Bonjour ! Que puis-je faire ?",
                                           "tool_results": []}))
    verifier("« bonjour » : aucun appel au relecteur", r4 == {} and not APPELS)
    r5 = asyncio.run(esp["verifier_node"]({"query": "envoie", "llm_response": "Voici le message prêt à partir.",
                                           "tool_results": [RESULTAT_SIGNATURE],
                                           "pending_action": {"skill": "envoyer_email"}}))
    verifier("une carte d'accord ne se relit pas", r5 == {} and not APPELS)

    # 15/09, Duret 16:07 : la carte du Word produit est posée par le serveur
    # APRÈS la relecture ; le relecteur lisait « composants : aucun » et
    # contestait une affirmation vraie.
    APPELS.clear()
    _LLM.verdict = '{"verdict": "ok", "problemes": []}'
    produit = {"skill": "produire_document", "ok": True, "args": {},
               "resultat_masque": json.dumps({"message_final": "Word produit", "bloc_ui": {
                   "type": "fichier", "url": "/api/documents/x", "nom": "MEMOIRE TECHNIQUE.docx"}})}
    asyncio.run(esp["verifier_node"]({"query": "fais le mémoire en word", "tool_results": [produit],
                                       "llm_response": "Le mémoire est prêt, sa carte s'affiche sous cette réponse."}))
    verifier("le relecteur voit les cartes que le serveur posera",
             APPELS and "MEMOIRE TECHNIQUE.docx" in APPELS[-1] and "posé par le serveur" in APPELS[-1])
    _LLM.panne = True
    r6 = asyncio.run(esp["verifier_node"](etat))
    _LLM.panne = False
    verifier("un relecteur en panne laisse passer la réponse",
             r6["verification"]["statut"] == "indisponible" and esp["route_apres_verifier"]({**etat, **r6}) == "rehydrate")

print("3. Le câblage")
src = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le graphe envoie au vérificateur ce qui partait à l'écran (llm et tools)",
         '"rehydrate": "verifier"}' in src and '{"llm": "llm", "rehydrate": "verifier"}' in src
         and 'graph.add_node("verifier", verifier_node)' in src)
verifier("la rédaction reprise porte le relevé", "pour_la_redaction(state.get(\"verification\"))" in src)
_i = src.index("pour_la_redaction(state.get(\"verification\"))")
verifier("le relevé vient À LA FIN du message, pas en queue du système (16:07 : même texte réécrit)",
         "human_content += (" in src[_i:_i + 600] and "NE PAS RECOPIER" in src[_i:_i + 900])
verifier("une carte posée par construction n'est plus tracée comme un échec du modèle",
         '"livrable_restitue", "absent_de_la_redaction"' not in src and '"bloc_garanti_absent"' not in src)
verifier("le forceur reçoit le geste manquant", '_verif.get("action_manquante")' in src)
etat_src = (racine / "agents" / "state.py").read_text(encoding="utf-8")
verifier("`verification` est déclarée dans l'état", "verification: Optional[dict]" in etat_src)
conf = (racine / "config.py").read_text(encoding="utf-8")
verifier("la relecture se coupe par réglage", "verifier_reponses: bool = True" in conf)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
