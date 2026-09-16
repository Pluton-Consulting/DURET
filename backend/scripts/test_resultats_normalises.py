"""
Banc « UN ÉCHEC MÉTIER N'EST PAS UNE RÉUSSITE » — audit détaillé du 15/09, fiche D-05/S-05.

L'enveloppe d'exécution d'un skill natif rendait `ok=True` dès que la fonction
Python se terminait, même quand sa sortie annonçait l'échec (`{"ok": False}`,
`{"depose": False}`, `{"genere": False}`). Le journal, la console, les filets et
la reprise après accord comptaient alors un échec comme une réussite.

CE BANC PROUVE :
  · `skills/resultats.normaliser_resultat` lit les contrats connus : échec,
    refus, introuvable, partiel, en attente, et « non vérifié » pour une sortie
    libre (qui garde `ok` pour ne rien casser, sans être une preuve) ; l'état de
    l'effet suit l'effet déclaré ; les références rouvrables sont relevées ;
  · `execute_skill` EXÉCUTÉ sur un skill natif doublé : une sortie en échec rend
    `ok=False` et sa phrase d'erreur, tous les champs d'avant sont conservés, et
    le journal d'audit l'enregistre comme un échec ;
  · la boucle d'actions et la reprise après accord suivent `ok`.

Usage : python backend/scripts/test_resultats_normalises.py [backend]
"""
import asyncio
import importlib.util
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, BACKEND / chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


print(f"\n═══ RÉSULTATS NORMALISÉS — {BACKEND.parent}\n")
print("1. Les contrats connus")
r = charger("skills.resultats", "skills/resultats.py")
n = r.normaliser_resultat
verifier("{ok: False} → échec, ok False", n({"ok": False, "message": "trop court"})["outcome"] == "failed"
         and n({"ok": False})["ok"] is False)
verifier("{depose: False} → échec de l'effet", n({"depose": False}, "externe")["effect_status"] == "not_done")
verifier("brouillon déposé (depose True, envoye False) → réussite, effet fait",
         n({"depose": True, "envoye": False}, "ecriture_interne") == {**n({"depose": True, "envoye": False}, "ecriture_interne"),
                                                                     "outcome": "success", "effect_status": "done"})
verifier("{genere: False} → échec", n({"genere": False, "message": "quota"})["ok"] is False)
verifier("{refuse: True} → refus", n({"refuse": True})["outcome"] == "denied")
verifier("{trouve: False} → introuvable, SANS être une panne (ok reste vrai)",
         n({"trouve": False})["outcome"] == "not_found" and n({"trouve": False})["ok"] is True)
verifier("{complet: False} → partiel, avec un avertissement",
         n({"complet": False})["outcome"] == "partial" and n({"complet": False})["warnings"])
verifier("{statut: en_attente} → en attente", n({"statut": "en_attente"}, "externe")["effect_status"] == "pending")
verifier("{erreur: '…'} sans ok → échec", n({"erreur": "adresse absente"})["outcome"] == "failed")
libre = n({"message_final": "Voici la liste", "bloc_ui": {"type": "table"}}, "externe")
verifier("une sortie libre → « non vérifié » : ok conservé, effet externe NON affirmé",
         libre["outcome"] == "unverified" and libre["ok"] is True and libre["effect_status"] == "unknown"
         and libre["contrat_reconnu"] is False, libre)
verifier("une sortie qui n'est pas un objet → non vérifié", n("texte")["outcome"] == "unverified")
preuves = n({"ok": True, "url": "/api/documents/AbCdEf123456789012",
             "bloc_ui": [{"type": "visuel", "images": [{"cle": "a1b2c3d4e5f6a7b8c9d0e1f2"}]}]})["evidence_refs"]
verifier("les références rouvrables sont relevées (document, visuel)",
         "document:AbCdEf123456789012" in preuves and "visuel:a1b2c3d4e5f6a7b8c9d0e1f2" in preuves, preuves)
verifier("la phrase d'échec est celle de la sortie", r.message_d_echec({"ok": False, "message": "Consigne trop courte"})
         == "Consigne trop courte")

print("2. execute_skill, exécuté sur un skill natif doublé")
if sys.version_info < (3, 10):
    # `skills/executor.py` s'écrit en Python 3.10+ (`str | None` évalué au
    # chargement) : le conteneur tourne en 3.12. Sous 3.9 la section se DIT sautée.
    print("  (SAUTÉ : Python < 3.10 ne charge pas executor.py — rejouer ce banc en 3.12)")
AUDIT = []


async def _log_action(**k):
    AUDIT.append(k)


class _Conn:
    async def fetchrow(self, *a):
        return None

    async def execute(self, *a):
        return None


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


async def _retenir_echoue(data, user):
    return {"ok": False, "message": "Consigne trop courte pour être utile."}


async def _lister_ok(data, user):
    return {"message_final": "3 dossiers", "bloc_ui": {"type": "table", "rows": []}}

for nom, attrs in {
    "skills": {"resultats": r},
    "database": {}, "database.connection": {"get_db": lambda: _Db()},
    "sandbox": {}, "sandbox.daytona_client": {"sandbox_client": object()},
    "security": {}, "security.audit": {"log_action": _log_action},
    "security.lecteur": {"au_nom_de": lambda u: __import__("contextlib").nullcontext()},
    "mail": {}, "mail.skills": {"SKILLS_NATIFS": {"retenir": _retenir_echoue, "lister": _lister_ok},
                                "EFFETS_NATIFS": {"retenir": "ecriture_interne", "lister": "lecture"}},
    "skills.registre": {"fonction": lambda n: None, "effet": lambda n: None, "expert": lambda n: None},
    "skills.erreurs": {"SkillError": type("SkillError", (Exception,), {})},
}.items():
    m = sys.modules.get(nom) if nom == "skills.resultats" else types.ModuleType(nom)
    m.__dict__.update(attrs)
    m.__path__ = []
    sys.modules[nom] = m
sys.modules["skills.resultats"] = r
if sys.version_info >= (3, 10):
    ex = charger("skills.executor", "skills/executor.py")
    utilisateur = types.SimpleNamespace(id="u1")
    brut = asyncio.run(ex.execute_skill("retenir", {"texte": "x"}, user=utilisateur))
    verifier("une sortie en échec rend ok=False, avec sa phrase d'erreur",
             brut["ok"] is False and brut["outcome"] == "failed"
             and brut["error"] == "Consigne trop courte pour être utile.", brut)
    verifier("les champs d'avant sont TOUS là (output, status, sandbox_type…)",
             brut["output"] == {"ok": False, "message": "Consigne trop courte pour être utile."}
             and brut["status"] == "native" and brut["sandbox_type"] == "natif" and "execution_time_ms" in brut)
    verifier("le journal d'audit l'enregistre comme un ÉCHEC", AUDIT and AUDIT[-1]["success"] is False
             and AUDIT[-1]["metadata"]["outcome"] == "failed", AUDIT[-1:])
    brut2 = asyncio.run(ex.execute_skill("lister", {}, user=utilisateur))
    verifier("une lecture au compte rendu libre reste ok, marquée non vérifiée",
             brut2["ok"] is True and brut2["outcome"] == "unverified" and brut2["error"] is None, brut2)

print("3. La boucle d'actions et la reprise après accord suivent `ok`")
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
routeur = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
verifier("tools_node : ok vient du résultat métier, l'issue entre dans le résultat du geste",
         'ok = bool(brut.get("ok", True))' in agent1 and "entree.update(issue)" in agent1)
verifier("reprise après accord : une sortie en échec devient l'erreur du compte rendu",
         'resultat.get("ok") is False' in routeur and "erreur = str(resultat.get(\"error\")" in routeur)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
