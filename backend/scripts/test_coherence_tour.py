"""
Banc de la cohérence d'un tour — ce que Noa a relevé le 31/08 au soir.

« Les mails de la semaine », un lundi : ceux du jour, sous un titre « 7 derniers
jours ». « Affiche le mail complet et dis-moi combien j'en ai reçu » : le compte,
pas le corps. « Es-tu sûr ? » : une réponse à un message quatre échanges plus
haut. Quatre causes dans le code, toutes mécaniques :
  * la date du jour n'était NULLE PART dans ce que lit le modèle ;
  * `depuis_quand` ne lisait ni « les 7 derniers jours » ni « lundi », et une
    période illisible était élargie EN SILENCE (les plus récents, sans le dire) ;
  * `lire_mail` sans référence ni objet refusait, alors que « le mail complet »
    désigne le dernier reçu ;
  * une question courte sans objet était vectorisée et rappelait des échanges
    anciens au hasard, que le modèle prenait pour le sujet.
Ce banc lit les fonctions PURES (extraction du source, sans base) et le câblage.
"""
import ast
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin: pathlib.Path, noms: set, espace: dict) -> None:
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    for noeud in arbre.body:
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)) and noeud.name in noms:
            exec(compile(ast.Module([noeud], []), str(chemin), "exec"), espace)  # noqa: S102
        if isinstance(noeud, ast.Assign) and any(isinstance(c, ast.Name) and c.id in noms for c in noeud.targets):
            exec(compile(ast.Module([noeud], []), str(chemin), "exec"), espace)  # noqa: S102


print(f"\n═══ COHÉRENCE D'UN TOUR — {BACKEND.parent}\n")

print("1. La période, dans les mots où on la demande (mail/lecture.py)")
esp = {"Optional": Optional, "datetime": datetime, "timedelta": timedelta, "timezone": timezone, "re": __import__("re")}
try:
    extraire(BACKEND / "mail/lecture.py", {"_MOTS_PERIODE", "_JOURS_SEMAINE", "_HABILLAGE", "_RE_JOURS", "_depouiller", "depuis_quand"}, esp)
    dq = esp["depuis_quand"]
    auj = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    jours = lambda v: (auj - dq(v)).days if dq(v) else None  # noqa: E731
    verifier("« semaine », « cette semaine », « 7j », « les 7 derniers jours » → 7 jours",
             [jours(v) for v in ("semaine", "cette semaine", "7j", "les 7 derniers jours", "depuis 7 jours")] == [7] * 5,
             str([jours(v) for v in ("semaine", "cette semaine", "7j", "les 7 derniers jours", "depuis 7 jours")]))
    verifier("« ce mois », « 30 derniers jours », « trimestre » → 30, 30, 90", [jours("ce mois"), jours("les 30 derniers jours"), jours("trimestre")] == [30, 30, 90])
    verifier("« aujourd'hui », « ce matin », « hier » → 0, 0, 1", [jours("aujourd'hui"), jours("ce matin"), jours("hier")] == [0, 0, 1])
    wd = datetime.now(timezone.utc).weekday()
    verifier("« lundi » = le dernier lundi (aujourd'hui si on est lundi)", jours("depuis lundi") == wd % 7, str(jours("depuis lundi")))
    verifier("« semaine dernière » remonte 14 jours", jours("la semaine dernière") == 14)
    verifier("une date ISO reste une date", dq("2026-08-15").date().isoformat() == "2026-08-15")
    verifier("l'illisible rend None (et lire_boite le DIT, cf. 2)", dq("bientôt") is None and dq("") is None)
except Exception as e:  # noqa: BLE001
    verifier("depuis_quand s'extrait et s'exécute", False, repr(e))

print("\n2. Une période illisible se dit, elle n'élargit plus en silence")
lecture = (BACKEND / "mail/lecture.py").read_text(encoding="utf-8")
verifier("lire_boite signale la période non comprise dans le COMPTE et dans un champ",
         "periode_non_comprise" in lecture and "n'a pas été comprise" in lecture)
verifier("lire_message ouvre le DERNIER message par défaut (`rang`)",
         "rang" in lecture[lecture.find("async def lire_message("):] and "le plus récent" in lecture[lecture.find("async def lire_message("):])
skills = (BACKEND / "mail/skills.py").read_text(encoding="utf-8")
verifier("le skill lire_mail transmet rang / dernier", 'data.get("rang")' in skills and 'data.get("dernier")' in skills)
protocole = (BACKEND / "skills/protocol.py").read_text(encoding="utf-8")
verifier("catalogue : sans rien, lire_mail ouvre le dernier reçu ; `depuis` est une DURÉE, pas une date calculée",
         "DERNIER message reçu" in protocole and "jamais une date que tu calcules" in protocole)

print("\n3. « Es-tu sûr ? » porte sur le dernier échange (agents/memoire_conversation.py)")
esp2: dict = {}
try:
    extraire(BACKEND / "agents/memoire_conversation.py", {"_META", "question_meta"}, esp2)
    qm = esp2["question_meta"]
    verifier("questions courtes sans objet → méta", all(qm(q) for q in ("es-tu sûr ?", "vraiment ?", "t'es sûr de toi ?", "oui", "et alors ?", "tu es certain de ça ?")))
    verifier("une vraie question n'est PAS méta",
             not any(qm(q) for q in ("montre-moi les mails de la semaine", "que sais-tu du client Pereire ?", "combien de devis terrasse bois en 2025")))
    mem = (BACKEND / "agents/memoire_conversation.py").read_text(encoding="utf-8")
    corps = mem[mem.find("async def rappeler_echanges("):mem.find("def bloc_memoire(")]
    verifier("rappeler_echanges ne vectorise pas une question méta", "question_meta(question)" in corps)
    verifier("le bloc mémoire dit que les rappels sont ANCIENS et que la question vise le dernier échange",
             "ANCIENS" in mem and "DERNIER échange" in mem)
except Exception as e:  # noqa: BLE001
    verifier("question_meta s'extrait et s'exécute", False, repr(e))

print("\n4. Le modèle sait quel jour on est, et traite toutes les demandes")
agent1 = (BACKEND / "agents/agent1.py").read_text(encoding="utf-8")
verifier("la date et l'heure du jour précèdent la question (Europe/Paris, en français)",
         "def _maintenant(" in agent1 and 'ZoneInfo("Europe/Paris")' in agent1 and "Date et heure actuelles : {_maintenant()}" in agent1)
verifier("règle : PLUSIEURS DEMANDES dans un message → toutes traitées", "PLUSIEURS DEMANDES DANS UN MESSAGE" in agent1)
verifier("règle : une question courte sans objet porte sur la DERNIÈRE réponse", "UNE QUESTION COURTE SANS OBJET" in agent1)
verifier("règle : une période se demande en DURÉE, pas en date calculée", "se demande en DURÉE" in agent1)
try:
    esp3: dict = {}
    extraire(BACKEND / "agents/agent1.py", {"_JOURS_FR", "_MOIS_FR", "_maintenant"}, esp3)
    m = esp3["_maintenant"]()
    verifier("_maintenant() rend « lundi 31 août 2026, 21:40 » (jour et mois en français)",
             re.fullmatch(r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche) \d{1,2}(er)? [a-zéû]+ \d{4}, \d{2}:\d{2}", m) is not None, m)
except Exception as e:  # noqa: BLE001
    verifier("_maintenant s'exécute", False, repr(e))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
