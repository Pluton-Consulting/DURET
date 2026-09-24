"""
Banc « TOUS LES MAILS SIGNIFIE TOUS LES MAILS » — 17/09 Symbiose, porté chez Duret le 18/09 (IMAP).
Chez Duret : « mets-moi dans un Excel tous les mails de la semaine » = sept `check_mails` enchaînés
par le modèle puis 171 lignes recopiées DEUX fois à la main (10 000 jetons chacune) ; « ajoute une
colonne priorité et surligne les 3 plus urgents » = dix minutes et un classeur reproduit à l'identique.
« Liste TOUS les mails des 7 derniers jours, aucune troncature » : 97 annoncés, 25 lus,
« la lecture a été interrompue ». Le modèle a rappelé SEPT fois `lire_mails depuis 7j,
exhaustif: true` sans jamais prendre la page suivante ; la garde du rejeu a coupé.
`exhaustif` ne changeait qu'une phrase d'aide, et le parcours complet de `check_mails`
suit un CURSEUR que seule la voie IMAP rendait — Outlook n'avait jamais de page 2.

Sans réseau : fonctions extraites du code livré, boîte doublée de 97 messages.
"""
import ast
import asyncio
import pathlib
import sys
from datetime import datetime
from typing import Optional

BACKEND = pathlib.Path(__file__).resolve().parents[1]
echecs = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def fonctions(src, noms):
    return "\n\n".join(ast.get_source_segment(src, n) for n in ast.parse(src).body
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms)


print("\n═══ INVENTAIRE DES MAILS —", BACKEND.parent)
# ── le skill, EXÉCUTÉ sur une boîte doublée de 97 messages ───────────────────
sk = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
BOITE = [{"ref": f"r{i:03d}", "objet": f"Message {i}", "de": "client@exemple.fr", "date": "2026-09-1%d" % (i % 7)} for i in range(97)]
appels = []


async def lire_boite(boite, dossier="recus", limite=10, depuis=None, recherche=None, avant=None,
                     apercu=None, curseur=None, exhaustif=False, autorises=None, non_lus=False):
    debut = int(str(curseur)[5:]) if str(curseur or "").startswith("saut:") else 0
    appels.append((debut, limite, apercu))
    page = [dict(m) for m in BOITE[debut:debut + limite]]
    suite = f"saut:{debut + len(page)}" if debut + len(page) < len(BOITE) else None
    return {"boite": boite, "messages": page, "nombre": len(page), "total_periode": len(BOITE),
            "curseur_suivant": suite, "tronque": bool(suite), "compte": "…", "pour_continuer": "…"}


class _Erreur(Exception):
    pass


async def _acces(user, boite): return boite or "moi@exemple-sols.fr"
async def _defaut(user): return "moi@exemple-sols.fr"
async def _visibles(user): return []
async def _a_lire(data, user): return data.get("mailbox") or "moi@exemple-sols.fr"

import types, logging
def depuis_quand(v):
    from datetime import datetime, timedelta
    if not v: return None
    v = str(v)
    if v.endswith("j"): return datetime.utcnow() - timedelta(days=int(v[:-1]))
    try: return datetime.fromisoformat(v)
    except ValueError: return None
class DossierInterdit(Exception):
    pass
async def dossiers_autorises(user): return None
sys.modules["mail.lecture"] = types.SimpleNamespace(lire_boite=lire_boite, depuis_quand=depuis_quand, DossierInterdit=DossierInterdit)
sys.modules["mail.authorization"] = types.SimpleNamespace(dossiers_autorises=dossiers_autorises)
sys.modules.setdefault("mail", types.ModuleType("mail"))
async def _livrer(inventaire, user, cle=None, **k):
    # La livraison (tableau garanti) est doublée : ici on juge la LECTURE ; elle retient l'inventaire comme la vraie.
    if cle is not None and "_retenir_inventaire" in esp2:
        esp2["_retenir_inventaire"](cle, inventaire, ())
    return inventaire
esp2 = {"_boite_a_lire": _a_lire, "_livrer_inventaire": _livrer, "verifier_acces": _acces, "boite_par_defaut": _defaut, "boites_visibles": _visibles,
        "MailSkillError": _Erreur, "logger": logging.getLogger("banc"), "MAX_INVENTAIRE_MAILS": 1000, "PAGE_INVENTAIRE": 50, "APERCU_INVENTAIRE": 200,
        "RANG_EXTRAIT_COURT": 250, "APERCU_INVENTAIRE_COURT": 110}
exec(fonctions(sk, {"lire_mails"}), esp2)
# La mémoire de l'inventaire et les priorités vivent à côté du skill.
esp2.update({"re": __import__("re")})
exec("\n".join(ast.get_source_segment(sk, n) for n in ast.parse(sk).body
               if (isinstance(n, (ast.Assign, ast.AnnAssign)) and getattr(getattr(n, "targets", [getattr(n, "target", None)])[0], "id", "")
                   in ("DUREE_INVENTAIRE_S", "_INVENTAIRES"))
               or (isinstance(n, ast.FunctionDef) and n.name in ("_cle_inventaire", "_inventaire_retenu", "_retenir_inventaire",
                                                                 "_sans_accents", "_lettres", "_mettre_en_tete", "_expediteur_lisible", "_comptes_par_expediteur"))), esp2)
lire_mails = esp2["lire_mails"]
user = types.SimpleNamespace(id="u", role="direction")

r = asyncio.run(lire_mails({"depuis": "7j", "exhaustif": True}, user))     # les arguments EXACTS de prod
verifier("les arguments EXACTS de prod rendent les 97 messages en UN geste", r["nombre"] == 97 and len(r["messages"]) == 97, str(r.get("nombre")))
verifier("aucun doublon, aucun trou, l'ordre est tenu", [m["ref"] for m in r["messages"]] == [m["ref"] for m in BOITE])
verifier("le résultat dit que c'est TOUT, et de ne pas rappeler le geste",
         r["tronque"] is False and r["curseur_suivant"] is None and "TOUS" in r["compte"] and "Ne rappelle pas" in (r.get("a_faire") or ""))
verifier("il se déclare inventaire (c'est ce qui lui ouvre le grand plafond de résultat)", r.get("inventaire") is True)
verifier("deux pages de 50 ont été lues côté serveur, avec l'extrait court de l'inventaire",
         [a[0] for a in appels] == [0, 50] and all(a[2] == 200 for a in appels), str(appels))

verifier("les comptes PAR EXPÉDITEUR sont calculés par le serveur (« qui m'a écrit le plus »)",
         r["par_expediteur"][0]["nombre"] == 97 and r["par_expediteur"][0]["expediteur"] == "client@exemple.fr" and len(r["par_expediteur"][0]["objets"]) == 3
         and "par_expediteur" in r["a_faire"], str(r.get("par_expediteur"))[:120])
appels.clear()
r2 = asyncio.run(lire_mails({"depuis": "7j", "rafraichir": True}, user))   # rafraichir : la liste gardée 30 min ne compte pas ici
# UNE PÉRIODE SE LIT EN ENTIER (24/09) : sans nombre demandé, `depuis` vaut inventaire complet.
verifier("une PÉRIODE sans nombre demandé = inventaire complet (97, deux pages)", len(appels) == 2 and r2["nombre"] == 97 and r2.get("inventaire"))
appels.clear()
r2 = asyncio.run(lire_mails({"depuis": "7j", "limite": 25}, user))
verifier("avec un NOMBRE demandé, une seule page comme avant (rapide)", len(appels) == 1 and r2["nombre"] == 25 and not r2.get("inventaire"))
BOITE.extend({"ref": f"x{i}", "objet": "x", "de": "a@b.fr", "date": "2026-09-10"} for i in range(1000))
appels.clear()
r3 = asyncio.run(lire_mails({"depuis": "30j", "tous": True}, user))
verifier("au plafond, la consigne dit sur combien on répond et interdit `rafraichir`", "NE relis PAS" in r3["a_faire"] and "1000 plus récents" in r3["a_faire"], r3["a_faire"][:120])
verifier("le parcours est BORNÉ (1 000), et au-delà la suite est DITE, jamais tue",
         r3["nombre"] == 1000 and r3["tronque"] is True and r3["curseur_suivant"] == "saut:1000" and "curseur=saut:1000" in (r3.get("pour_continuer") or ""))
verifier("au-delà du 250ᵉ message, l'extrait se resserre pour que tout tienne dans UN résultat",
         {a[2] for a in appels if a[0] < 250} == {200} and {a[2] for a in appels if a[0] >= 250} == {110}, str(sorted({(a[0] >= 250, a[2]) for a in appels})))

# ── LE TABLEAU COMPLET ET L'EXCEL SE FABRIQUENT, ILS NE SE RECOPIENT PAS ─────
# 17/09 15:36 → 15:45 : 98 mails lus, VINGT lignes à l'écran, puis QUATRE dans l'Excel.
print("\n── le livrable de l'inventaire")
import json as _json, re as _re
del BOITE[97:]
produits = []


async def _appeler(prompt, tier="standard"):
    # Un modèle doublé : classe chaque ligne du lot, invente UNE catégorie hors liste.
    rangs = [int(x) for x in _re.findall(r"^(\d+)\. De :", prompt, _re.M)]
    return "Voici : " + _json.dumps([{"n": n, "resume": f"résumé {n}", "categorie": ("fournisseur" if n % 2 else "PUBLICITÉ")} for n in rangs])


async def _protege(t): return t, {}
class _Atelier:
    @staticmethod
    def ouvrir(entete, proprio): return "jeton123"
    @staticmethod
    def ajouter(jeton, elements, proprio): produits.append(elements); return len(elements)
    @staticmethod
    def terminer(jeton, proprio): return {"octets": 4242}
sys.modules["bureautique"] = types.ModuleType("bureautique")
sys.modules["bureautique.atelier"] = _Atelier
# UN SEUL espace de noms : le livrable appelle la mémoire de l'inventaire, qui vit avec le skill.
esp2.update({"re": _re, "_appeler": _appeler, "_protege": _protege, "_rehydrater": lambda v, c: v})
esp3 = esp2
exec("\n".join(ast.get_source_segment(sk, n) for n in ast.parse(sk).body
               if (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ("CATEGORIES_MAILS", "LOT_CLASSEMENT"))
               or (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name in ("_categories_voulues", "_lire_classement", "_classer_les_mails", "_jour_lisible", "_expediteur_lisible", "_comptes_par_expediteur", "_livrer_inventaire"))), esp3)
r4 = asyncio.run(lire_mails({"depuis": "7j", "classer": True, "fichier": True}, user))
blocs = r4["bloc_ui"]
table = next(b for b in blocs if b["type"] == "table")
verifier("`classer` + `fichier` sans `exhaustif` : l'inventaire complet est fait quand même (97 lignes)", len(table["rows"]) == 97, str(len(table["rows"])))
verifier("le tableau porte date, expéditeur, objet, résumé, catégorie — pour CHAQUE mail",
         table["columns"] == ["Date", "Expéditeur", "Objet", "Résumé", "Catégorie"] and all(len(l) == 5 for l in table["rows"]))
verifier("une catégorie HORS liste n'est pas recopiée : la ligne reste « à classer », rien n'est inventé",
         {l[4] for l in table["rows"]} == {"fournisseur", "à classer"})
verifier("le bloc est GARANTI (le modèle n'a rien à recopier) et le fichier est au-dessus du tableau",
         r4["bloc_garanti"] is True and blocs[0]["type"] == "fichier" and blocs[0]["url"] == "/api/documents/jeton123")
verifier("l'Excel porte les 97 lignes et un second onglet « Par catégorie »",
         len(produits[-1]) == 2 and produits[-1][0]["type"] == "feuille" and len(produits[-1][0]["lignes"]) == 97
         and produits[-1][1]["nom"] == "Par catégorie")
verifier("la consigne interdit de recopier et demande ce qu'on veut EN PLUS (les priorités)",
         "ne recopie AUCUNE ligne" in r4["a_faire"] and "priorité" in r4["a_faire"] and "Ne rappelle pas" in r4["a_faire"])
async def _panne(prompt, tier="standard"): raise RuntimeError("cascade à terre")
esp2["_appeler"] = _panne
r5 = asyncio.run(lire_mails({"depuis": "7j", "classer": True, "rafraichir": True}, user))
verifier("un modèle en panne ne fait pas tomber l'inventaire : 97 lignes « à classer », et c'est dit",
         len(r5["bloc_ui"][0]["rows"]) == 97 and r5["classes"] == 0 and {l[4] for l in r5["bloc_ui"][0]["rows"]} == {"à classer"})
# ── CE QUI VIENT D'ÊTRE LU N'EST PAS RELU (17/09, 16:02) ─────────────────────
print("\n── la suite d'une demande")
esp2["_appeler"] = _appeler
esp2["_INVENTAIRES"].clear()
appels.clear(); modele = []
_vrai = esp2["_appeler"]
async def _compte(prompt, tier="standard"):
    modele.append(1); return await _vrai(prompt, tier)
esp2["_appeler"] = _compte
ra = asyncio.run(lire_mails({"depuis": "7j", "classer": True}, user))
lectures, classements = len(appels), len(modele)
rb = asyncio.run(lire_mails({"depuis": "7j", "fichier": True, "priorites": ["message 42", "Message 7", "introuvable xyz"],
                             "surlignage": "orange"}, user))      # « mets les priorités en premier, surligne en orange »
verifier("la suite d'une demande ne RELIT pas la boîte et ne RECLASSE rien",
         len(appels) == lectures and len(modele) == classements, f"lectures {lectures}→{len(appels)}, modèle {classements}→{len(modele)}")
ta, tb = ra["bloc_ui"][0], next(b for b in rb["bloc_ui"] if b["type"] == "table")
cat = lambda t: {l[t["columns"].index("Objet")]: l[t["columns"].index("Catégorie")] for l in t["rows"]}
verifier("les catégories sont EXACTEMENT celles que la personne a lues", cat(ta) == cat(tb) and len(tb["rows"]) == 97)
verifier("les mails désignés passent EN TÊTE, dans l'ordre demandé, avec leur rang",
         tb["columns"][0] == "Priorité" and [l[3] for l in tb["rows"][:2]] == ["Message 42", "Message 7"] and [l[0] for l in tb["rows"][:3]] == [1, 2, ""])
verifier("l'Excel surligne ces lignes-là, en orange", produits[-1][0]["surlignees"] == [0, 1] and produits[-1][0]["surlignage"] == "orange")
verifier("une priorité introuvable est DITE, jamais inventée", "2 priorité(s) retrouvée(s) sur 3" in (rb.get("priorites_introuvables") or ""))
verifier("la réponse dit que la liste est reprise, et comment forcer la relecture", "aucune relecture" in (rb.get("repris") or "") and "rafraichir" in rb["repris"])
asyncio.run(lire_mails({"depuis": "7j", "classer": True, "rafraichir": True}, user))
verifier("`rafraichir: true` relit bien la boîte", len(appels) > lectures)
autre = types.SimpleNamespace(id="autre", role="direction")
avant_autre = len(appels)
asyncio.run(lire_mails({"depuis": "7j", "exhaustif": True}, autre))
verifier("la mémoire est PAR PERSONNE : un autre compte relit la boîte", len(appels) > avant_autre)
met = esp2["_mettre_en_tete"]
lot = [{"objet": "RE: RELANCE FACTURES IMPAYÉES", "de": "cbp@exemple.fr"}, {"objet": "place Thiers", "de": "mairie@exemple.fr"}, {"objet": "Pub", "de": "x@y.fr"}]
lot2 = [{"objet": "TR: 249 AREAS - visite d'année parfait achèvement (APA) - PV pour signature", "de": "p@unaa.eu"}, {"objet": "autre", "de": "x@y.fr"}]
verifier("la ponctuation ne compte pas : « APA - PV pour signature » retrouve « …(APA) - PV pour signature » (18/09)",
         met(lot2, ["APA - PV pour signature"]) == 1 and lot2[0].get("priorite") == 1)
verifier("un mail se désigne par un fragment d'objet (accents, casse, « RE: » indifférents), par l'expéditeur ou par son rang",
         met(lot, ["re: relance factures impayees", "MAIRIE", 3]) == 3 and [m["objet"] for m in lot][0].startswith("RE: RELANCE"))

lc = esp3["_lire_classement"]
verifier("la lecture du classement est tolérante et bornée (rang hors lot, JSON cassé, prose autour)",
         lc('blabla [{"n": 1, "resume": "x", "categorie": "Fournisseur"}, {"n": 9, "resume": "y", "categorie": "fournisseur"}] fin', 3, ["fournisseur"]) == {1: ("x", "fournisseur")}
         and lc("pas de json", 3, ["a"]) == {} and lc("[{", 3, ["a"]) == {})
verifier("`categories` en texte ou en liste, sinon celles de la maison",
         esp3["_categories_voulues"]("Devis, SAV ; Compta") == ["devis", "sav", "compta"] and esp3["_categories_voulues"](None)[0] == "demande de devis")
proto = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue annonce `classer`, `categories`, `fichier` et dit de NE PAS passer par produire_document",
         '"classer", "categories", "fichier"' in proto and "n'utilise PAS `produire_document`" in proto)

a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le résultat d'un inventaire n'est pas recoupé après avoir été parcouru en entier",
         "action['skill']=='lire_mails' and isinstance(sortie,dict) and sortie.get('inventaire'):plafond=190000" in a1)

jour = esp3["_jour_lisible"]
verifier("la date se lit en ISO comme en RFC 2822 (voie IMAP de Duret : « Se/18/Fri, 2026 » avant)",
         jour({"date": "2026-09-18T08:32:14"}) == "18/09/2026 08:32" and jour({"date": "Fri, 18 Sep 2026 08:32:14 +0000"}) == "18/09/2026 10:32"
         and jour({"date": "n'importe quoi", "date_iso": "2026-09-18"}) == "18/09/2026" and jour({}) == "", str([jour({"date": "Fri, 18 Sep 2026 08:32:14 +0000"})]))
nomme = esp3["_expediteur_lisible"]
verifier("l'expéditeur se dit « Prénom Nom (adresse) » quand la messagerie donne le nom (18/09)",
         nomme({"de": "d.j@europiscine.fr", "de_nom": "David J."}) == "David J. (d.j@europiscine.fr)"
         and nomme({"de": "facture@sfr.fr", "de_nom": "facture@sfr.fr"}) == "facture@sfr.fr"
         and nomme({"de": "x@y.fr"}) == "x@y.fr")

print("\n" + "═" * 70)
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec\n")
