"""
Banc « À VALIDER : CHACUN LES SIENNES » (14/09, Duret).

Relevé de Noa : « Nouvelle compétence à valider : calculer_prix_total · ouvrir
Connaissances — ça part pas, et assure-toi que les à valider sont bien propres
à chaque utilisateur ». Décision de Noa, interrogé : chacun voit et approuve
SES accords, quel que soit son rôle.

Ce qui existait : le tableau de bord servait à la direction les accords de
TOUT le monde (périmètre global), `GET /api/validations/` rendait toute la
file à qui avait `validate_skills`, et `resolve` laissait un administrateur
trancher l'envoi d'un autre — pendant qu'un profil métier recevait un 403 sur
ses propres accords. Et la compétence n'avait aucune sortie : le lien menait
à la file des accords, où elle ne figure pas.

CE QUE CE BANC PROUVE (routes EXÉCUTÉES contre une base doublée) :
  * `peut_trancher` : le propriétaire oui, tout autre non (direction comprise),
    une ligne sans propriétaire pour qui administre seulement ;
  * la liste ne rend que les siennes ; le détail d'un autre est un 404 ;
  * `resolve` d'une demande d'autrui : 404, la ligne reste « pending », aucune
    reprise ; sa propre demande, par un profil MÉTIER : acceptée ;
  * le tableau de bord filtre les accords par personne, et la compétence se
    valide ou s'écarte depuis la carte.
Tombe sur la version d'avant.
"""
import ast
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel):
    return (RACINE / rel).read_text(encoding="utf-8")


print(f"\n═══ À VALIDER : CHACUN LES SIENNES — {RACINE}\n")

source = lire("backend/routers/validation.py")
NOMS = {"_peut_valider", "peut_trancher", "list_validations", "get_validation",
        "resolve_validation", "_with_payload"}
morceaux = []
for n in ast.parse(source).body:
    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in NOMS:
        n.decorator_list = []
        n.args.defaults = []
        n.returns = None
        for a in n.args.args:
            a.annotation = None
        morceaux.append(n)
trouves = {n.name for n in morceaux}
verifier("validation.py porte peut_trancher", "peut_trancher" in trouves, sorted(trouves))


class HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        self.status_code, self.detail = status_code, detail


ADMIN = {"super_admin", "direction"}
LIGNES = {
    "v-nat": {"id": "v-nat", "user_id": "nat", "status": "pending", "thread_id": "t-nat", "agent": "agent1"},
    "v-dir": {"id": "v-dir", "user_id": "dir", "status": "pending", "thread_id": "t-dir", "agent": "agent1"},
    "v-sys": {"id": "v-sys", "user_id": None, "status": "pending", "thread_id": "t-sys", "agent": "agent1"},
}
REPRISES = []


class _Conn:
    async def fetch(self, sql, *a):
        moi, admin = str(a[0]), a[1]
        return [dict(l, payload="{}", draft="", reason="", created_at=None,
                     requester_email="", requester_name="")
                for l in LIGNES.values() if l["status"] == "pending"
                and (l["user_id"] == moi or (l["user_id"] is None and admin))]

    async def fetchrow(self, sql, *a):
        if sql.lstrip().startswith("UPDATE"):
            decision, moi, vid, admin = a
            l = LIGNES.get(str(vid))
            if l and l["status"] == "pending" and (l["user_id"] == str(moi) or (l["user_id"] is None and admin)):
                l["status"] = decision
                return {"id": vid, "thread_id": l["thread_id"], "agent": l["agent"]}
            return None
        l = LIGNES.get(str(a[0]))
        return dict(l, payload="{}", draft="", reason="", created_at=None, resolved_at=None,
                    validated_by=None, requester_email="", requester_name="") if l else None

    async def fetchval(self, sql, *a):
        return None

    async def execute(self, sql, *a):
        return "UPDATE 1"


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *x):
        return False


async def _log(**kw):
    pass


async def _reprendre(**kw):
    REPRISES.append(kw)
    return {"status": "done", "response": "fait"}


espace = {
    "get_db": lambda: _Db(), "HTTPException": HTTPException, "log_action": _log,
    "has_permission": lambda role, f: role in ADMIN,
    "json": __import__("json"), "logging": __import__("logging"),
    "runtime": types.SimpleNamespace(resume_turn=_reprendre),
    "status": types.SimpleNamespace(HTTP_403_FORBIDDEN=403, HTTP_404_NOT_FOUND=404,
                                    HTTP_409_CONFLICT=409, HTTP_502_BAD_GATEWAY=502),
}
if NOMS - {"_with_payload"} <= trouves | {"_with_payload"} and "peut_trancher" in trouves:
    exec(compile(ast.Module(body=morceaux, type_ignores=[]), "validation", "exec"), espace)
    pt = espace["peut_trancher"]
    verifier("EXÉCUTÉ — le propriétaire tranche sa demande, même profil métier", pt("nat", "commercial", "nat"))
    verifier("la direction ne tranche pas la demande d'un autre", not pt("dir", "direction", "nat"))
    verifier("le super_admin non plus", not pt("sa", "super_admin", "nat"))
    verifier("une demande sans propriétaire reste à qui administre",
             pt("dir", "direction", None) and not pt("nat", "commercial", None))

    qui = lambda uid, role: types.SimpleNamespace(id=uid, role=role)  # noqa: E731

    def appel(coro):
        try:
            return asyncio.run(coro)
        except HTTPException as e:
            return e

    r = appel(espace["list_validations"](qui("dir", "direction")))
    verifier("EXÉCUTÉ — la liste de la direction : les siennes + sans propriétaire, pas celles de Nathalie",
             sorted(x["id"] for x in r) == ["v-dir", "v-sys"], r)
    r = appel(espace["list_validations"](qui("nat", "commercial")))
    verifier("un profil métier a SA liste (plus de 403)", [x["id"] for x in r] == ["v-nat"], r)
    r = appel(espace["get_validation"]("v-nat", qui("dir", "direction")))
    verifier("le détail de la demande d'un autre : 404", isinstance(r, HTTPException) and r.status_code == 404)

    corps = lambda ok: types.SimpleNamespace(approved=ok)  # noqa: E731
    r = appel(espace["resolve_validation"]("v-nat", corps(True), qui("dir", "direction")))
    verifier("EXÉCUTÉ — la direction ne peut pas approuver l'envoi de Nathalie (404)",
             isinstance(r, HTTPException) and r.status_code == 404, r)
    verifier("la ligne reste « pending » et rien ne reprend",
             LIGNES["v-nat"]["status"] == "pending" and not REPRISES, (LIGNES["v-nat"], REPRISES))
    r = appel(espace["resolve_validation"]("v-nat", corps(True), qui("nat", "commercial")))
    verifier("EXÉCUTÉ — Nathalie (commercial) approuve SA demande, la reprise part",
             isinstance(r, dict) and LIGNES["v-nat"]["status"] == "approved" and len(REPRISES) == 1, r)
    r = appel(espace["resolve_validation"]("v-nat", corps(True), qui("nat", "commercial")))
    verifier("une seconde fois : 409 (déjà résolue)", isinstance(r, HTTPException) and r.status_code == 409, r)

print("— Le tableau de bord et les écrans")
tableau = lire("backend/routers/tableau.py")
bloc = tableau[tableau.index("accords = await _sur("):tableau.index("# ── Tâches (arrière-plan)")]
verifier("les accords du tableau de bord sont ceux de la personne (plus le périmètre global)",
         "perso.format(col='v.user_id')" in bloc and "perim.format(col='v.user_id')" not in bloc)
verifier("les compétences s'affichent à qui peut les valider",
         'has_permission(current_user.role, "validate_skills")' in bloc)
dash = lire("backend/routers/dashboard.py")
verifier("/dashboard/pending-validations : les siennes seulement", "AND (v.user_id = $1 OR v.user_id IS NULL)" in dash)
fa = lire("backend/routers/file_attente.py")
verifier("la file d'attente dit à chacun qu'il tranche les siens", "peut = True" in fa)
ecran = lire("frontend/components/tableau/TableauDeBord.tsx")
verifier("la compétence se valide ET s'active depuis la carte",
         '"/validate", { status: "validated" }' in ecran and '"/enabled", { enabled: true }' in ecran)
verifier("elle s'écarte (deprecated, rien d'effacé)", '"/validate", { status: "deprecated" }' in ecran)
verifier("le lien mort « ouvrir Connaissances » a disparu de la carte", "ouvrir Connaissances</a>" not in ecran)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
