"""
Banc de LA REVUE DE LA BOÎTE REPRISE, PAS REFAITE (22/09, Duret, prompts 5 puis 6 de la recette).

Prompt 5 : la revue de la semaine — 141 mails lus, classés, un Excel. Prompt 6, huit minutes
plus tard : « rédige un brouillon pour chaque mail de la revue qui appelle une réponse ».
`check_mails` a RELU toute la boîte (140 cette fois), et le temps du tour s'est épuisé après
un seul brouillon. Deux causes : `check_mails` ne reprenait jamais la liste gardée par
`lire_mails` (30 min) ; et la liste était rangée sous la période ÉCRITE (« 7j »), qu'un
« les 7 derniers jours » ne retrouvait pas.

CE QUE CE BANC PROUVE (fonctions EXÉCUTÉES : `_cle_inventaire` et `depuis_quand` des vrais
modules, `check_mails` du vrai skills/routines.py, messagerie doublée) :
  · « 7j », « 7 derniers jours », « semaine » rangent la liste sous le même jour de début ;
  · une revue gardée est reprise par `check_mails` : AUCUNE lecture de la boîte, les 141
    mails, leurs résumés et catégories ; les droits sont revérifiés ;
  · `rafraichir: true` relit ; une reprise impossible retombe sur la lecture.
Tombe sur la version d'avant (`check_mails` relit toujours).

Usage : python backend/scripts/test_revue_reprise.py [backend]
"""
import ast
import asyncio
import importlib.util
import pathlib
import sys
import time
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


# ── La vraie `depuis_quand` : mail/lecture.py exécuté avec sa configuration doublée ──
sys.modules["config"] = types.SimpleNamespace(settings=types.SimpleNamespace())
sys.modules["mail"] = types.ModuleType("mail")
sys.modules["mail.collecte"] = types.SimpleNamespace(fournisseur=lambda *a, **k: "imap")
lecture = types.ModuleType("mail.lecture")
exec(compile((racine / "mail" / "lecture.py").read_text(encoding="utf-8"), "mail/lecture.py", "exec"),
     lecture.__dict__)
sys.modules["mail.lecture"] = lecture

# ── La vraie `_cle_inventaire`, extraite de mail/skills.py ──
source_skills = (racine / "mail" / "skills.py").read_text(encoding="utf-8")
fonctions = {n.name: ast.get_source_segment(source_skills, n) for n in ast.parse(source_skills).body
             if isinstance(n, ast.FunctionDef)}
espace = {}
exec(fonctions["_cle_inventaire"], espace)
_cle_inventaire = espace["_cle_inventaire"]

UTILISATEUR = types.SimpleNamespace(id="u1", role="super_admin")
print("1. La période se range sous son jour de début")
cles = {d: _cle_inventaire(UTILISATEUR, "Boite@Exemple.fr", "recus", d) for d in ("7j", "7 derniers jours", "semaine")}
verifier("« 7j », « 7 derniers jours », « semaine » : la même liste", len(set(cles.values())) == 1, cles)
verifier("la boîte est comparée sans la casse", cles["7j"][1] == "boite@exemple.fr", cles["7j"])

# ── check_mails, sur une messagerie doublée ──
MESSAGES = [{"ref": f"r{i}", "de": f"Client {i}", "objet": f"Objet {i}", "date": "2026-09-21",
             "apercu": "…", "lu": i % 3 == 0, "resume": f"Demande {i}.",
             "categorie": "chantier" if i % 2 else "administratif"} for i in range(141)]
GARDE = {}
lectures = []


async def _boite_a_lire(data, user):
    if GARDE.get("panne"):
        raise RuntimeError("messagerie indisponible")
    return "boite@exemple.fr"


async def verifier_acces(user, cible, envoi=False):
    GARDE["verifications"] = GARDE.get("verifications", 0) + 1
    return cible


def _inventaire_retenu(cle):
    return GARDE.get(cle)


async def lire_mails(data, user):
    lectures.append(dict(data))
    return {"messages": MESSAGES[:25], "total_periode": 140, "boite": "boite@exemple.fr",
            "curseur_suivant": None, "compte": "140 message(s) sur la période."}


sys.modules["mail.skills"] = types.SimpleNamespace(
    lire_mails=lire_mails, _boite_a_lire=_boite_a_lire, verifier_acces=verifier_acces,
    _cle_inventaire=_cle_inventaire, _inventaire_retenu=_inventaire_retenu)
sys.modules["skills.registre"] = types.SimpleNamespace(Declaration=lambda *a, **k: None)
sys.modules["skills.erreurs"] = types.SimpleNamespace(SkillError=RuntimeError)
_spec = importlib.util.spec_from_file_location("routines_banc", racine / "skills" / "routines.py")
routines = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(routines)

GARDE[_cle_inventaire(UTILISATEUR, "boite@exemple.fr", "recus", "7j")] = {
    "a": time.time() - 480,
    "inventaire": {"messages": MESSAGES, "nombre": 141, "total_periode": 141,
                   "boite": "boite@exemple.fr", "compte": "141 message(s) sur la période."}}

print("2. check_mails reprend la revue gardée")
r = asyncio.run(routines.check_mails({"mailbox": "boite@exemple.fr", "depuis": "les 7 derniers jours"}, UTILISATEUR))
verifier("AUCUNE lecture de la boîte", lectures == [], lectures[:1])
verifier("les 141 mails de la revue, pas 140", r.get("nombre") == 141 and r.get("total_periode") == 141,
         (r.get("nombre"), r.get("total_periode")))
liste = r.get("messages") or r.get("releve") or []
verifier("chaque mail garde son résumé et sa catégorie",
         liste and all(m.get("resume") and m.get("categorie") for m in liste), liste[:1])
verifier("les droits sont revérifiés avant la reprise", GARDE.get("verifications", 0) >= 1)

print("3. Relire quand on le demande, lire quand la reprise échoue")
lectures.clear()
asyncio.run(routines.check_mails({"mailbox": "boite@exemple.fr", "depuis": "7j", "rafraichir": True}, UTILISATEUR))
verifier("`rafraichir: true` relit la boîte", len(lectures) >= 1)
lectures.clear()
GARDE["panne"] = True
r = asyncio.run(routines.check_mails({"mailbox": "boite@exemple.fr", "depuis": "7j"}, UTILISATEUR))
verifier("reprise impossible → la boîte se lit, le point ne casse pas", len(lectures) >= 1 and r.get("nombre"),
         r.get("nombre"))

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
