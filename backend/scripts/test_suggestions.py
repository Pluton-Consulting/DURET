"""
Banc « une suite proposée à la fin de CHAQUE réponse » — 01/09.

Noa : « il faut des suggestions à la fin de chaque message ». Ce qui existait :
une phrase du prompt (que le modèle suivait rarement) et un convertisseur étroit
qui n'agit que sur une question à choix numérotée. Les trois chemins mécaniques
— rendu de secours, vision, reprise après validation — n'en portaient JAMAIS,
c'est-à-dire précisément aux moments où une suite est la plus évidente.

Ce banc exerce le module VRAIMENT (il est pur : ni base, ni réseau), vérifie le
câblage des quatre points d'entrée sur le SOURCE LIVRÉ, et fait respecter les
trois règles d'écriture de la table — impératif, jamais une question, jamais une
donnée du tour. C'est cette dernière série qui protège la règle de Noa : une
suggestion est un raccourci d'entrée, pas une phrase de l'assistant.
"""
import importlib.util
import json
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def ui(bloc):
    return "```ui\n" + json.dumps(bloc, ensure_ascii=False) + "\n```"


print(f"\n═══ SUGGESTIONS DE SUITE — {BACKEND.resolve().parent}\n")

# ── Chargement du module livré, sans le paquet `agents` complet ──────────
paquet = types.ModuleType("agents")
paquet.__path__ = [str(BACKEND / "agents")]
sys.modules.setdefault("agents", paquet)


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, BACKEND / "agents" / fichier)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    spec.loader.exec_module(mod)
    return mod


metier = charger("agents.suggestions_metier", "suggestions_metier.py")
sug = charger("agents.suggestions", "suggestions.py")
du_tour, poser = sug.suggestions_du_tour, sug.poser

# ── 1. Le choix, du plus précis au plus général ──────────────────────────
verifier("le skill qui a réussi dicte la suite",
         "Ouvre le premier document" in du_tour(
             "Voici les 12 documents.", [{"skill": "rechercher_documents", "ok": True}]))
verifier("c'est le DERNIER geste réussi qui fait foi, pas le premier",
         du_tour("fait.", [{"skill": "rechercher_documents", "ok": True},
                           {"skill": "produire_document", "ok": True}])
         == metier.PAR_SKILL["produire_document"][:3])
verifier("un skill en ÉCHEC ne choisit pas sa ligne",
         du_tour("raté.", [{"skill": "rechercher_documents", "ok": False}])
         == metier.ERREUR[:3])
verifier("un skill inconnu de la table retombe plus bas, il ne casse rien",
         len(du_tour("fait.", [{"skill": "un_skill_qui_nexiste_pas", "ok": True}])) >= 2)
verifier("un échec, puis un succès : c'est le succès qui parle",
         "Ouvre le premier message" in du_tour(
             "fait.", [{"skill": "inconnu", "ok": False},
                       {"skill": "lire_mails", "ok": True}]))

verifier("sans skill connu, le bloc à l'écran décide",
         du_tour("Voici l'image." + ui({"type": "visuel", "images": []}), [])
         == metier.PAR_BLOC["visuel"][:3])
verifier("l'ordre des blocs : un visuel prime sur un tableau",
         du_tour(ui({"type": "table", "colonnes": []}) + ui({"type": "visuel", "images": []}), [])
         == metier.PAR_BLOC["visuel"][:3])
verifier("l'expert vient après les blocs, avant le défaut",
         du_tour("Analyse du plan.", [], expert="agent2") == metier.PAR_EXPERT["agent2"][:3])
verifier("rien du tout → le socle, au moins deux options",
         du_tour("Bonjour.") == metier.DEFAUT[:3] and len(metier.DEFAUT) >= 2)

# ── 2. Quand on se TAIT ──────────────────────────────────────────────────
verifier("une validation en cours : une seule décision à la fois",
         du_tour("Je dois valider.", [{"skill": "lire_mails", "ok": True}], pending=True) == [])
verifier("un texte vide n'a rien à compléter", du_tour("") == [] and du_tour("   ") == [])
for t in ("quick_replies", "plan", "reponses_mail"):
    verifier(f"un bloc « {t} » porte déjà son interaction",
             du_tour("Voilà." + ui({"type": t, "options": ["a"]}), []) == [])
verifier("un bloc ILLISIBLE ne bloque pas le filet (le JSON cassé est ignoré)",
         len(du_tour("```ui\n{cassé,,}\n```\nVoilà.", [])) >= 2)

# ── 3. Les bornes d'écran ────────────────────────────────────────────────
tailler = sug._tailler
verifier("jamais plus de trois pastilles",
         len(tailler(["a" * 5, "b" * 5, "c" * 5, "d" * 5, "e" * 5])) == 3)
verifier("un libellé trop long est écarté, pas coupé",
         tailler(["Court", "x" * 60, "Autre"]) == ["Court", "Autre"])
verifier("les doublons ne se répètent pas", tailler(["Oui", "oui", "Non"]) == ["Oui", "Non"])
verifier("une seule option n'est pas un choix : rien ne s'affiche",
         tailler(["Seule"]) == [] and tailler([]) == [])
verifier("MAX_LONGUEUR tient dans la rangée qui ne se replie pas",
         sug.MAX_LONGUEUR <= 48 and sug.MAX_OPTIONS <= 3)

# ── 4. La pose : on n'écrase jamais ce qui précède ───────────────────────
pose = poser("Ma réponse.", ["Un", "Deux"])
verifier("le texte d'origine survit intact", pose.startswith("Ma réponse."))
verifier("le bloc est un quick_replies bien formé, à la fin",
         json.loads(re.findall(r"```ui\s*(\{.*?\})\s*```", pose, re.S)[-1])
         == {"type": "quick_replies", "options": ["Un", "Deux"]})
verifier("sans option, rien n'est ajouté", poser("Ma réponse.", []) == "Ma réponse.")
verifier("les suites d'échec sont exposées proprement (pas un `_` importé ailleurs)",
         sug.suites_d_echec() == metier.ERREUR[:3])

# ── 5. LA DISCIPLINE DE LA TABLE — le contrôle qui protège la règle ──────
# Pendant de `test_messages_humains.py` : une suggestion est un raccourci
# d'ENTRÉE. Dès qu'elle pose une question, parle à la première personne ou cite
# une donnée, elle redevient une phrase de l'assistant écrite en dur.
tous = []
for table in (metier.PAR_SKILL, metier.PAR_BLOC, metier.PAR_EXPERT):
    for options in table.values():
        tous.extend(options)
tous.extend(metier.ERREUR)
tous.extend(metier.DEFAUT)

_INTERDITS = re.compile(r"^(je |j'|nous |voulez-vous|souhaitez-vous|puis-je|dois-je"
                        r"|préférez-vous|que préférez)", re.I)
fautifs = [o for o in tous if "?" in o]
verifier("aucune suggestion n'est une question", not fautifs, str(fautifs[:3]))
fautifs = [o for o in tous if _INTERDITS.match(o)]
verifier("aucune ne parle à la place de l'assistant", not fautifs, str(fautifs[:3]))
fautifs = [o for o in tous if re.search(r"\d{4}|\d+\s?(€|euros)", o)]
verifier("aucune ne cite une donnée du tour (année, montant)", not fautifs, str(fautifs[:3]))
fautifs = [o for o in tous if len(o) > sug.MAX_LONGUEUR]
verifier("aucune ne dépasse la borne d'écran", not fautifs, str(fautifs[:3]))
fautifs = [o for o in tous if o != o.strip() or not o[:1].isupper()]
verifier("toutes commencent par une majuscule, sans espace parasite", not fautifs, str(fautifs[:3]))
courtes = [(k, v) for k, v in metier.PAR_SKILL.items() if len(sug._tailler(v)) < 2]
verifier("chaque entrée de la table rend au moins deux pastilles utilisables",
         not courtes, str(courtes[:3]))

# ── 6. LE CÂBLAGE, lu dans le source livré ───────────────────────────────
def avant(texte, a, b):
    """« a » apparaît-il avant « b » ? Faux si l'un des deux manque — un banc
    qui doit TOMBER sur la version d'avant ne doit pas s'interrompre en route :
    il doit dire tout ce qui manque, d'un coup."""
    ia, ib = texte.find(a), texte.find(b)
    return ia >= 0 and ib >= 0 and ia < ib


a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("agent1 : le filet est dans la branche `else` d'options_proposees "
         "(la question du modèle reste prioritaire)",
         re.search(r"_options = options_proposees\(.*?\n    if _options:.*?\n    else:"
                   r".*?from agents\.suggestions import suggestions_du_tour", a1, re.S))
verifier("agent1 : posé AVANT l'écriture de l'historique",
         avant(a1, "from agents.suggestions import suggestions_du_tour",
               'sortie["messages"] = ['))
verifier("agent1 : l'historique reste construit sur le texte MASQUÉ, jamais sur "
         "la réponse d'écran",
         re.search(r'sortie\["messages"\] = \[\s*\n\s*HumanMessage\(content=question_masquee\)'
                   r',\s*\n\s*AIMessage\(content=text\),', a1))
verifier("agent1 : le cul-de-sac rouvre trois portes au lieu de s'arrêter",
         "suites_d_echec" in (a1.split("Reformulez la demande") + [""])[1][:600])
verifier("agent1 : deux rangées de pastilles ne survivent pas dans un message",
         re.search(r'if str\(bloc\.get\("type"\)\) == "quick_replies":\s*\n\s*'
                   r'if "quick_replies" in vus:\s*\n\s*return ""', a1))
verifier("agent1 : le prompt ne s'annule plus lui-même (« demande close » retiré)",
         "Pas de suggestions quand la demande est close" not in a1
         and "une suite générique est ajoutée toute seule" in a1)

rt = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
verifier("router : les pastilles sont posées après un accord",
         "from agents.suggestions import suggestions_du_tour" in rt)
verifier("router : posées AVANT le cas du plan, qui les efface d'office",
         avant(rt, "from agents.suggestions import suggestions_du_tour",
               'if action["skill"] == "proposer_plan"'))
verifier("router : une suggestion ne peut jamais casser une reprise",
         "noqa: BLE001 — une suggestion ne casse jamais une reprise" in rt)

a2 = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
verifier("agent2 : les DEUX retours de la vision portent la version d'écran",
         a2.count('"final_response": summary_ecran') == 2
         and '"final_response": summary,' not in a2)
verifier("agent2 : l'historique de la vision garde le résumé MASQUÉ et nu",
         "AIMessage(content=resume_masque)" in a2)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
