"""
Banc « défaire une tâche » — 01/09 nuit.

Demande de Noa : « une tâche créée par erreur doit pouvoir se supprimer en le
demandant au chat aussi ».

CE QU'IL N'Y AVAIT PAS. Le catalogue portait UN seul geste sur les tâches :
`creer_tache_agent`. Ni écran ni chat ne permettait de lister, suspendre ou
supprimer. Une tâche créée par mégarde en « toutes les 5 minutes » se réveillait
indéfiniment, consommait du quota de modèle à chaque fois, et seul un accès
direct à la base pouvait l'arrêter. Créer sans pouvoir défaire n'est pas une
fonctionnalité, c'est un piège.

LE CHOIX QUI MÉRITE D'ÊTRE DÉFENDU : effet `ecriture_interne`, pas `externe`.
Supprimer une tâche ne produit rien hors du système, et la règle du projet
réserve l'accord humain aux effets qui SORTENT — envoi, dépôt, tirage. Exiger
une validation ici irait contre « une lecture se fait, on ne demande pas », et
contre la demande explicite de Noa de cesser de multiplier les confirmations.

LE GARDE-FOU EST DONC AILLEURS, ET IL EST PLUS SÛR QU'UNE CONFIRMATION : ON NE
DEVINE JAMAIS. Une désignation qui vise plusieurs tâches ne supprime RIEN — elle
les liste et redemande. C'est ce qui empêche « supprime la tâche des mails »
d'effacer les trois qui parlent de mails, là où un « oui » aurait tout emporté.

Base doublée : aucune connexion, aucun réseau.
"""
import ast
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ DÉFAIRE UNE TÂCHE — {BACKEND.resolve().parent}\n")

# ── La base doublée ──────────────────────────────────────────────────────
TACHES = [
    {"id": "11111111-1111-1111-1111-111111111111", "title": "Tri des mails du matin",
     "enabled": True, "schedule_kind": "daily", "next_run_at": None},
    {"id": "22222222-2222-2222-2222-222222222222", "title": "Relances mails impayés",
     "enabled": True, "schedule_kind": "weekly", "next_run_at": None},
    {"id": "33333333-3333-3333-3333-333333333333", "title": "Point chantiers",
     "enabled": False, "schedule_kind": "interval", "next_run_at": None},
]
EXECUTE: list = []


class _Conn:
    async def fetch(self, sql, *a):
        if "ORDER BY enabled DESC" in sql:
            return TACHES
        if "title ILIKE" in sql:
            motif = a[1].strip("%").lower()
            return [t for t in TACHES if motif in t["title"].lower()]
        return []

    async def fetchrow(self, sql, *a):
        if "WHERE id = $1::uuid" in sql:
            return next((t for t in TACHES if t["id"] == a[0]), None)
        if "SELECT schedule_kind" in sql:
            return {"schedule_kind": "daily", "interval_minutes": None,
                    "time_of_day": None, "days_of_week": None}
        return None

    async def execute(self, sql, *a):
        EXECUTE.append((" ".join(sql.split()), a))


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *x):
        return False


faux_db = types.ModuleType("database.connection")
faux_db.get_db = lambda: _Db()
paquet = types.ModuleType("database")
paquet.__path__ = []
sys.modules.setdefault("database", paquet)
sys.modules["database.connection"] = faux_db

faux_sched = types.ModuleType("tasks.scheduler")
faux_sched.heure_du_jour = lambda x: x
faux_sched.prochaine_echeance = lambda t, apres=None: None
faux_sched.valider_planification = lambda d: None
paquet_t = types.ModuleType("tasks")
paquet_t.__path__ = []
sys.modules.setdefault("tasks", paquet_t)
sys.modules["tasks.scheduler"] = faux_sched

# FastAPI n'est pas installé hors du conteneur : `TacheInvalide` en hérite pour
# rendre un 422 propre à l'API, ce qui n'a pas d'importance ici — seul compte
# qu'elle LÈVE, avec son message.
faux_fastapi = types.ModuleType("fastapi")


class _Http(Exception):
    def __init__(self, status_code=400, detail=""):
        self.status_code, self.detail = status_code, detail
        super().__init__(detail)


faux_fastapi.HTTPException = _Http
faux_fastapi.status = type("s", (), {"HTTP_422_UNPROCESSABLE_ENTITY": 422})
sys.modules["fastapi"] = faux_fastapi

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("taches_banc", BACKEND / "tasks" / "skills.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class _Moi:
    id = "u-1"


# ── 1. LISTER ────────────────────────────────────────────────────────────
r = asyncio.run(mod.mes_taches({}, _Moi()))
verifier("les tâches se listent", r["nombre"] == 3 and r["actives"] == 2, str(r.get("nombre")))
verifier("le tableau s'affiche MÉCANIQUEMENT (bloc garanti)",
         r.get("bloc_garanti") and r["bloc_ui"]["type"] == "table")
verifier("il montre l'état, pour qu'on sache ce qui tourne encore",
         any("suspendue" in l for l in r["bloc_ui"]["lignes"]))
verifier("et il dit au modèle de ne PAS recopier le tableau",
         "n'écris aucun bloc" in r["a_faire"])

# ── 2. SUPPRIMER : LE CAS DE NOA ─────────────────────────────────────────
EXECUTE.clear()
r = asyncio.run(mod.supprimer_tache({"tache": "Point chantiers"}, _Moi()))
verifier("LE CAS DE NOA — une tâche désignée par son titre est supprimée",
         r.get("supprimee") and r["titre"] == "Point chantiers", str(r))
supp = [e for e in EXECUTE if e[0].startswith("DELETE")]
verifier("un DELETE part, et un seul", len(supp) == 1)
verifier("il est borné à la personne : un identifiant deviné ne suffit pas",
         supp and "user_id = $2::uuid" in supp[0][0])
verifier("le compte rendu dit ce qui ne se produira plus",
         "ne se réveillera plus" in r["message_final"])

# ── 3. ON NE DEVINE JAMAIS ───────────────────────────────────────────────
EXECUTE.clear()
r = asyncio.run(mod.supprimer_tache({"tache": "mails"}, _Moi()))
verifier("DEUX tâches parlent de « mails » : RIEN n'est supprimé",
         r.get("ambigu") and not EXECUTE, str(EXECUTE))
verifier("les candidates sont rendues, pour qu'on puisse choisir",
         len(r["candidates"]) == 2)
verifier("et le modèle a INTERDICTION de trancher à la place de la personne",
         "Ne choisis PAS à sa place" in r["a_faire"])

# ── 4. Une désignation vide ou inconnue refuse, elle ne détruit pas ──────
for essai in ("", "une tâche qui n'existe pas"):
    EXECUTE.clear()
    try:
        asyncio.run(mod.supprimer_tache({"tache": essai}, _Moi()))
        leve = False
    except Exception as e:  # noqa: BLE001
        leve = "Aucune tâche" in str(getattr(e, "detail", e))
    verifier(f"« {essai or '(vide)'} » : refus explicite, aucune suppression",
             leve and not EXECUTE)

# ── 5. SUSPENDRE — le geste à préférer quand on hésite ───────────────────
EXECUTE.clear()
r = asyncio.run(mod.suspendre_tache({"tache": "Tri des mails du matin"}, _Moi()))
verifier("suspendre marche, et ne supprime rien",
         r["active"] is False and not any(e[0].startswith("DELETE") for e in EXECUTE))
verifier("le compte rendu rassure : rien n'est perdu",
         "rien n'est perdu" in r["message_final"])
r = asyncio.run(mod.suspendre_tache({"tache": "Tri des mails du matin",
                                     "active": "oui"}, _Moi()))
verifier("et la reprise se demande explicitement", r["active"] is True)
src = (BACKEND / "tasks" / "skills.py").read_text(encoding="utf-8")
verifier("à la reprise, l'échéance est RECALCULÉE — celle d'origine est passée",
         "prochaine_echeance(dict(complete))" in src)

# ── 6. Les déclarations, aux quatre endroits ─────────────────────────────
ms = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
for nom, effet in (("mes_taches", "lecture"),
                   ("supprimer_tache", "ecriture_interne"),
                   ("suspendre_tache", "ecriture_interne")):
    verifier(f"« {nom} » est enregistré et son effet déclaré ({effet})",
             f'SKILLS_NATIFS["{nom}"] = {nom}' in ms and f'"{nom}": "{effet}"' in ms)
proto = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue les décrit tous les trois",
         all(f'"{n}": (' in proto for n in
             ("mes_taches", "supprimer_tache", "suspendre_tache")))
verifier("il dit que rien n'est supprimé quand la désignation est ambiguë",
         "RIEN n'est supprime" in proto)
verifier("et il pousse vers la SUSPENSION quand on hésite",
         "A PREFERER a la suppression" in proto)
journal = (BACKEND / "agents" / "journal.py").read_text(encoding="utf-8")
verifier("le journal a un libellé pour chacun",
         all(f'"{n}":' in journal for n in
             ("mes_taches", "supprimer_tache", "suspendre_tache")))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
