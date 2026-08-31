"""
Banc de la recherche dans les mails — « lire_mails sait chercher et remonter le temps ».

POURQUOI. Le 31/08, Noa demande « analyse mes mails pour trouver des demandes de
travaux », puis « cherche sur tous les mails 25 par 25 ». L'assistant répond,
honnêtement : « le système ne permet que de lire les 25 plus récents d'une
période, sans possibilité de paginer ». C'était vrai : `lire_mails` n'avait ni
mots-clés ni page suivante — Graph et Gmail savent pourtant faire les deux.

CE QUE CE BANC PROUVE, sans réseau : les deux constructeurs de requête
(fonctions PURES extraites de `mail/lecture.py`) produisent, pour Outlook, les
deux régimes que Graph impose — filtre/tri/compte SANS recherche, `$search`
KQL seul AVEC recherche, les dates dans la requête — et, pour Gmail, la
requête `q` composée ; que `avant` borne bien vers le passé ; et que le skill,
le catalogue et le résultat (`plus_ancien`, `pour_continuer`) portent la page
suivante jusqu'au modèle.
"""
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Optional

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


src = (BACKEND / "mail" / "lecture.py").read_text(encoding="utf-8")
debut = src.index("def _kql_echapper(")
fin = src.index("async def _lire_outlook(")
espace = {"Optional": Optional, "datetime": datetime}
exec(src[debut:fin], espace)  # noqa: S102 — code du dépôt
_params_outlook = espace["_params_outlook"]
_requete_gmail = espace["_requete_gmail"]

D1 = datetime(2026, 8, 15, tzinfo=timezone.utc)
D2 = datetime(2026, 8, 22, tzinfo=timezone.utc)

print(f"\n═══ RECHERCHE DANS LES MAILS — {BACKEND.parent}\n")

print("1. Outlook SANS recherche : filtre, tri, compte exact (comme avant)")
p = _params_outlook(25, D1)
verifier("$count=true (le total exact, c'est le contrat de « combien »)", p.get("$count") == "true")
verifier("$orderby du plus récent", p.get("$orderby") == "receivedDateTime desc")
verifier("$filter ge sur la période", p.get("$filter") == "receivedDateTime ge 2026-08-15T00:00:00Z")
verifier("pas de $search", "$search" not in p)
p = _params_outlook(25, None)
verifier("sans période : aucun $filter", "$filter" not in p and p.get("$top") == 25)

print("\n2. Outlook AVEC recherche : $search seul, dates en KQL")
p = _params_outlook(25, D1, "terrasse bois", D2)
verifier("$search présent, entre guillemets", str(p.get("$search", "")).startswith('"') and p["$search"].endswith('"'))
verifier("les mots y sont", "terrasse bois" in p["$search"])
verifier("la période DANS la requête KQL (received>=)", "received>=2026-08-15" in p["$search"])
verifier("la borne « avant » DANS la requête KQL (received<)", "received<2026-08-22" in p["$search"])
verifier("Graph interdit $filter/$orderby/$count avec $search : absents",
         all(k not in p for k in ("$filter", "$orderby", "$count")))
verifier("$select conservé (on ne rapatrie pas les corps entiers)", "bodyPreview" in p.get("$select", ""))
p = _params_outlook(25, None, 'devis "piscine"')
verifier("un guillemet dans les mots ne casse pas la chaîne $search", p["$search"].count('"') == 2)
p = _params_outlook(25, D1, "   ")
verifier("une recherche vide = pas de recherche (régime filtre)", "$search" not in p and "$filter" in p)

print("\n3. Outlook : « avant » sans recherche = filtre lt (la page précédente)")
p = _params_outlook(25, D1, None, D2)
verifier("ge ET lt combinés par « and »",
         p.get("$filter") == "receivedDateTime ge 2026-08-15T00:00:00Z and receivedDateTime lt 2026-08-22T00:00:00Z")
p = _params_outlook(25, None, None, D2)
verifier("avant seul : lt seul", p.get("$filter") == "receivedDateTime lt 2026-08-22T00:00:00Z")

print("\n4. Gmail : la requête q")
verifier("rien → None (les plus récents, comme avant)", _requete_gmail(None) is None)
verifier("période seule → after:", _requete_gmail(D1) == "after:2026/08/15")
verifier("mots + période + avant", _requete_gmail(D1, "terrasse  bois", D2) == "terrasse bois after:2026/08/15 before:2026/08/22")
verifier("mots seuls", _requete_gmail(None, "piscine") == "piscine")

print("\n5. Le skill, le catalogue et le résultat portent la page suivante")
skills = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("le skill transmet recherche et avant à lire_boite", "recherche=recherche, avant=avant" in skills)
verifier("alias acceptés (mots, contient, mots_cles, query)",
         all(f'data.get("{a}")' in skills for a in ("mots", "contient", "mots_cles", "query")))
verifier("limite 25 d'office dès qu'on cherche ou qu'on pagine", "25 if (_periode or recherche or avant) else 10" in skills)
proto = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue déclare recherche et avant en optionnels",
         '["mailbox", "dossier", "limite", "depuis", "recherche", "avant"]' in proto)
verifier("le catalogue explique la page suivante (plus_ancien → avant)",
         "plus_ancien" in proto and "`avant`" in proto)
verifier("lire_boite calcule plus_ancien depuis date_iso", 'plus_ancien = min((m.get("date_iso")' in src)
verifier("pour_continuer dit au modèle quoi rappeler", '"pour_continuer"' in src and "avant={plus_ancien}" in src)
verifier("Gmail : date_iso vient d'internalDate (le seul champ garanti lisible)", 'm["internalDate"]' in src)
verifier("Outlook : date_iso vient de receivedDateTime", '"date_iso": (m.get("receivedDateTime") or "")[:10]' in src)
verifier("le compte dit quand le total n'est pas connu (recherche Outlook)",
         "le total des correspondances n'est pas connu du fournisseur" in src)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
