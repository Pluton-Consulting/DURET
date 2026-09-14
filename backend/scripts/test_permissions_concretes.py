"""
Banc « DES PERMISSIONS CONCRÈTES » (14/09).

Demande de Noa : « change les permissions RBAC pour qu'il n'y ait que des
permissions concrètes et compréhensibles pour un profil terrain ».

Ce que l'onglet montrait : 17 colonnes au nom technique (« Agent 2 (vision) »,
« Dashboard global », « Valider skills »…), dont CINQ que le backend ne lisait
nulle part — on les cochait sans rien changer — et plusieurs qui ne pouvaient
jamais agir pour un profil métier, faute d'écran ouvert à ce rôle.

CE QUE CE BANC PROUVE :
  * chaque case affichée correspond à un contrôle RÉEL (`has_permission(…,
    "<case>")` hors de rbac.py) — la vérification qui compte ;
  * les cases mortes ne sont plus à l'écran, mais restent valides en base ;
  * chaque case a un libellé et une phrase, sans jargon (agent, skill, RBAC,
    dashboard, audit) ;
  * les cases d'administration ne se règlent que pour la direction, et la
    route le refuse pour un autre rôle ; une case retirée ne se règle plus ;
  * une permission cochée ouvre son onglet (Import) grâce à /mes-permissions.
Tombe sur la version d'avant.
"""
import ast
import asyncio
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ DES PERMISSIONS CONCRÈTES — {RACINE}\n")

src = (BACKEND / "security" / "rbac.py").read_text(encoding="utf-8")
rb = types.ModuleType("rbac_banc")
exec(compile("from __future__ import annotations\n" +
             src.replace("from fastapi import HTTPException, status", "HTTPException = Exception\nstatus = None"),
             "rbac", "exec"), rb.__dict__)

print("— La matrice montrée")
a_matrice = hasattr(rb, "MATRICE") and hasattr(rb, "FEATURES_MATRICE")
verifier("rbac.py porte la MATRICE groupée", a_matrice)
if a_matrice:
    montrees = rb.FEATURES_MATRICE
    # Tout le backend sauf rbac.py, les bancs et les migrations.
    code = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in BACKEND.rglob("*.py")
                     if "scripts" not in p.parts and "__pycache__" not in p.parts
                     and p.name != "rbac.py")
    for f in montrees:
        controle = re.search(r"""has_permission\([^\n]*["']%s["']""" % f, code) or \
            re.search(r"""FEATURE\s*=\s*["']%s["']""" % f, code)
        verifier(f"« {rb.FEATURE_LABELS[f]} » ({f}) est VRAIMENT vérifiée par le code", bool(controle))
    for mort in ("chat_agent2", "chat_agent3", "view_own_stats", "view_own_costs", "configure_agents"):
        verifier(f"la case morte {mort} n'est plus à l'écran", mort not in montrees)
        verifier(f"… mais reste valide en base ({mort})", mort in rb.ALL_FEATURES)
    for technique in ("manage_system", "run_browser_agent", "view_audit_log", "manage_mailboxes"):
        verifier(f"{technique} (réservée ou sans écran) n'est pas proposée", technique not in montrees)
    jargon = re.compile(r"\b(agent|skill|rbac|dashboard|audit|feature|backend)\b", re.I)
    for f in montrees:
        texte = rb.FEATURE_LABELS[f] + " " + rb.FEATURE_DESCRIPTIONS[f]
        verifier(f"« {rb.FEATURE_LABELS[f]} » : une phrase, sans jargon",
                 len(rb.FEATURE_DESCRIPTIONS[f]) > 30 and not jargon.search(texte), texte)
    admin = [x["feature"] for g in rb.MATRICE for x in g["permissions"] if tuple(x["roles"]) == ("direction",)]
    verifier("les cases d'administration ne se règlent que pour la direction",
             set(admin) == {"manage_users", "validate_skills", "manage_agent3", "view_costs_global"}, admin)
    verifier("« Utiliser l'assistant » et « Lire et envoyer les mails » se règlent pour le terrain",
             "terrain" in rb.ROLES_REGLABLES["chat_agent1"] and "terrain" in rb.ROLES_REGLABLES["access_mail"])

print("— Les routes")
settings_src = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
noms = {"get_permissions", "update_permission", "mes_permissions"}
fonctions = []
for n in ast.parse(settings_src).body:
    if isinstance(n, ast.AsyncFunctionDef) and n.name in noms:
        n.decorator_list = []
        n.args.defaults = []
        for a in n.args.args:
            a.annotation = None
        fonctions.append(n)
verifier("settings.py porte /permissions (lire, régler) et /mes-permissions",
         {f.name for f in fonctions} == noms, [f.name for f in fonctions])


class HTTPException(Exception):
    def __init__(self, status_code, detail=""):
        self.status_code, self.detail = status_code, detail


ECRITS = []


class _Conn:
    async def execute(self, sql, *a):
        ECRITS.append(a)


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *x):
        return False


async def _rien(**k):
    pass


if a_matrice and {f.name for f in fonctions} == noms:
    rb.reload_permissions = lambda: _rien()
    sys.modules["security"] = types.SimpleNamespace(rbac=rb)
    sys.modules["security.rbac"] = rb
    espace = {"has_permission": lambda role, f: role in ("super_admin",) or
              (role == "direction" and f == "manage_users"),
              "HTTPException": HTTPException, "get_db": lambda: _Db(), "log_action": _rien,
              "status": types.SimpleNamespace(HTTP_403_FORBIDDEN=403, HTTP_400_BAD_REQUEST=400,
                                              HTTP_422_UNPROCESSABLE_ENTITY=422)}
    exec(compile(ast.Module(body=fonctions, type_ignores=[]), "settings", "exec"), espace)
    qui = lambda role: types.SimpleNamespace(id="u", role=role)  # noqa: E731
    corps = lambda role, f: types.SimpleNamespace(role=role, feature=f, allowed=True)  # noqa: E731

    def appel(c):
        try:
            return asyncio.run(c)
        except HTTPException as e:
            return e

    r = appel(espace["get_permissions"](qui("direction")))
    verifier("EXÉCUTÉ — la lecture rend les groupes, les phrases et les rôles réglables",
             isinstance(r, dict) and r["features"] == rb.FEATURES_MATRICE and r["groupes"]
             and set(r["descriptions"]) == set(rb.FEATURES_MATRICE) and "roles_reglables" in r, r)
    r = appel(espace["update_permission"](corps("terrain", "manage_users"), qui("super_admin")))
    verifier("régler « Gérer les utilisateurs » pour le terrain : refusé (422)",
             isinstance(r, HTTPException) and r.status_code == 422, r)
    r = appel(espace["update_permission"](corps("terrain", "configure_agents"), qui("super_admin")))
    verifier("régler une case retirée : refusé (422)", isinstance(r, HTTPException) and r.status_code == 422, r)
    ECRITS.clear()
    r = appel(espace["update_permission"](corps("terrain", "import_documents"), qui("super_admin")))
    verifier("ouvrir « Importer des fichiers » au terrain : accepté et écrit",
             isinstance(r, dict) and ECRITS == [("terrain", "import_documents", True)], (r, ECRITS))
    r = appel(espace["mes_permissions"](qui("super_admin")))
    verifier("/mes-permissions rend les permissions du rôle connecté",
             isinstance(r, dict) and "import_documents" in r["permissions"], r)

print("— L'écran")
ecran = (RACINE / "frontend/app/(app)/parametres/SettingsClient.tsx").read_text(encoding="utf-8")
verifier("l'onglet s'appelle « Permissions », plus « Permissions RBAC »",
         'label: "Permissions", roles' in ecran and "Permissions RBAC" not in ecran)
verifier("une ligne par permission, avec sa phrase", "data.descriptions?.[f]" in ecran and "data.groupes" in ecran)
verifier("une case non réglable pour un rôle s'affiche « — » (réservé à la direction)",
         "data.roles_reglables" in ecran and "Réservé à la direction" in ecran)
verifier("une permission cochée ouvre son onglet (Import)",
         'permission: "import_documents"' in ecran and "/api/settings/mes-permissions" in ecran)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
