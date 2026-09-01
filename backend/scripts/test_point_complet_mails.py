"""
Banc « le point sur les mails couvre TOUT, réponses comprises » — 01/09.

Relevé en prod : « Fais le point sur tous mes mails des 7 derniers jours :
une synthèse message par message, et propose une réponse pour chacun de ceux
qui en appellent une. » → 25 messages détaillés sur 63, et AUCUNE proposition
de réponse. Deux causes : `check_mails` ne transmettait même pas `avant` (le
détail de 25 n'était pas ENCHAÎNABLE, et son a_faire disait « propose de
cibler ») ; et rien ne vérifiait que la moitié « propose une réponse » de la
demande était honorée.

Ce banc prouve : check_mails passe `avant`, rend `plus_ancien` et un
`pour_continuer` qui ordonne d'enchaîner jusqu'au total ; l'a_faire dit
ENCHAÎNE ; le prédicat `demande_des_reponses_mail` reconnaît la demande
EXACTE de prod ; `_reponses_mail_manquantes` détecte la synthèse sans cartes ;
et la rédaction est reprise UNE fois avec le manque nommé.
"""
import ast
import asyncio
import importlib.util
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


def extraire(chemin, noms, espace):
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = []
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            gardes.append(n)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id in noms for c in n.targets):
            gardes.append(n)
        elif isinstance(n, ast.Import) and any(
                (a.asname or a.name) in noms for a in n.names):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ POINT COMPLET SUR LES MAILS — {BACKEND.resolve().parent}\n")

DEMANDE_PROD = ("Fais le point sur tous mes mails des 7 derniers jours : une synthèse "
                "message par message, et propose une réponse pour chacun de ceux qui "
                "en appellent une.")

# ── 1. Le prédicat ───────────────────────────────────────────────────────
spec = importlib.util.spec_from_file_location("annonce_banc", BACKEND / "agents" / "annonce.py")
annonce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(annonce)
p = annonce.demande_des_reponses_mail
verifier("la demande EXACTE de prod est reconnue", p(DEMANDE_PROD))
verifier("« propose des réponses » est reconnu", p("Synthèse des mails et propose des réponses."))
verifier("« réponds à ce mail de Martin » n'est PAS visé (une seule rédaction suffit)",
         not p("Réponds à ce mail de Martin sur le devis."))
verifier("vide → faux", not p("") and not p(None))

# ── 2. Le filet : synthèse sans cartes → rédaction reprise ───────────────
paquet = types.ModuleType("agents"); paquet.__path__ = []
sys.modules.setdefault("agents", paquet)
sys.modules["agents.annonce"] = annonce
espace = {"AgentState": dict}
extraire(BACKEND / "agents" / "agent1.py", {"_reponses_mail_manquantes"}, espace)
manque = espace["_reponses_mail_manquantes"]
etat = {"query": DEMANDE_PROD,
        "tool_results": [{"skill": "check_mails", "ok": True}]}
verifier("synthèse SANS bloc reponses_mail → le manque est détecté",
         manque(etat, "Voici la synthèse des 63 messages reçus depuis le 25/08/2026."))
verifier("avec le bloc reponses_mail → rien à reprendre",
         not manque(etat, 'Synthèse…\n```ui\n{"type": "reponses_mail", "reponses": []}\n```'))
verifier("sans lecture de mails au tour → rien à reprendre",
         not manque({"query": DEMANDE_PROD, "tool_results": []}, "Synthèse…"))
verifier("sans cette demande → rien à reprendre",
         not manque({"query": "fais le point sur mes mails",
                     "tool_results": [{"skill": "check_mails", "ok": True}]}, "Synthèse…"))

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le routeur reprend la rédaction (rediger) quand les cartes manquent",
         re.search(r'_reponses_mail_manquantes\(state, visible\).*?return "rediger"', agent1, re.S)
         and "reponses_mail_manquantes" in agent1)
verifier("la consigne de reprise NOMME le manque (bloc reponses_mail, une carte par message)",
         "PROPOSITION DE RÉPONSE" in agent1 and "ref, de, objet, synthese, reponse" in agent1)
verifier("la dernière passe vérifie aussi le manque",
         re.search(r"or not _texte_visible\(texte\)\s*\n\s*or _reponses_mail_manquantes\(state, texte\)\):",
                   agent1))

# ── 3. check_mails : la page suivante existe, et s'ordonne ───────────────
appels = []


async def _faux_lire_mails(data, user):
    appels.append(data)
    return {"messages": [{"ref": f"r{i}", "de": f"x{i}@y.fr", "objet": f"Objet {i}",
                          "date": "2026-08-31", "apercu": "Bonjour, pouvez-vous…", "lu": i % 2 == 0}
                         for i in range(25)],
            "boite": "noa@symbiose.fr", "total_periode": 63, "tronque": True,
            "plus_ancien": "2026-08-27T08:00:00", "compte": "63 messages reçus depuis le 25/08/2026."}

faux_mail = types.ModuleType("mail.skills"); faux_mail.lire_mails = _faux_lire_mails
paquet_mail = types.ModuleType("mail"); paquet_mail.__path__ = []
faux_err = types.ModuleType("skills.erreurs")


class _Err(Exception):
    pass


faux_err.SkillError = _Err
paquet_sk = types.ModuleType("skills"); paquet_sk.__path__ = []
sys.modules.update({"mail": paquet_mail, "mail.skills": faux_mail,
                    "skills": paquet_sk, "skills.erreurs": faux_err})
espace_r = {}
extraire(BACKEND / "skills" / "routines.py", {"check_mails", "re"}, espace_r)
r = asyncio.run(espace_r["check_mails"]({"depuis": "7j", "avant": "2026-08-29T00:00:00"}, None))
verifier("`avant` traverse jusqu'à lire_mails (la page se demande)",
         appels[-1].get("avant") == "2026-08-29T00:00:00")
verifier("le résultat rend plus_ancien et un pour_continuer qui ordonne d'enchaîner",
         r.get("plus_ancien") == "2026-08-27T08:00:00"
         and "avant=2026-08-27T08:00:00" in str(r.get("pour_continuer"))
         and "couvrir le total AVANT de rédiger" in str(r.get("pour_continuer")))
verifier("l'a_faire dit ENCHAÎNE, plus jamais « propose de cibler »",
         "ENCHAÎNE" in r["a_faire"] and "propose de cibler" not in r["a_faire"]
         and "UNE SEULE synthèse" in r["a_faire"])
routines = (BACKEND / "skills" / "routines.py").read_text(encoding="utf-8")
verifier("le catalogue de check_mails porte `avant` et l'ordre d'enchaîner",
         '"avant"],' in routines and "ENCHAINE avec `avant`" in routines)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
