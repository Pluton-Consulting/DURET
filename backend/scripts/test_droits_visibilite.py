"""
Banc « droits et visibilité » — les règles de Noa du 01/09.

  · la colonne « Gérer les boîtes » quitte la matrice de permissions (la
    permission survit pour les délégations, elle ne s'édite plus là) ;
  · le DÉFAUT mail de tout le monde, super_admin et direction compris, est SA
    boîte + ses délégations ; une AUTRE boîte ne s'ouvre que NOMMÉE, et
    seulement pour super_admin et direction (journalisé) ;
  · la direction ne voit pas les super_admin dans la liste des utilisateurs
    (filtre SERVEUR) et ne peut pas agir sur eux ;
  · onglets Paramètres : super_admin garde tout ; Utilisateurs et Plages
    horaires = direction (et lui) ; États des agents, Quotas, Services,
    Synchronisations, Clés API = super_admin seul.
"""
import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = (BACKEND.resolve().parent / "frontend")
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
        elif (isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
              and n.target.id in noms and n.value is not None):
            # L'annotation (`List[str]`…) s'évaluerait ici sans ses imports :
            # on garde l'affectation nue, la valeur seule compte au banc.
            gardes.append(ast.copy_location(
                ast.Assign(targets=[n.target], value=n.value), n))
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ DROITS ET VISIBILITÉ — {BACKEND.resolve().parent}\n")

# ── 1. La matrice : plus de colonne « Gérer les boîtes » ─────────────────
rb = extraire(BACKEND / "security" / "rbac.py",
              {"ALL_FEATURES", "FEATURE_LABELS", "ROLE_PERMISSIONS"}, {})
verifier("« Gérer les boîtes » a quitté la matrice de l'onglet Permissions",
         "manage_mailboxes" not in rb["ALL_FEATURES"])
verifier("la permission SURVIT (délégations) pour super_admin et direction",
         "manage_mailboxes" in rb["ROLE_PERMISSIONS"]["super_admin"]
         and "manage_mailboxes" in rb["ROLE_PERMISSIONS"]["direction"])
verifier("les autres colonnes restent (stats, coûts, audit, skills, configurer, importer)",
         all(f in rb["ALL_FEATURES"] for f in
             ("view_own_stats", "view_own_costs", "view_audit_log",
              "validate_skills", "configure_agents", "import_documents")))

# ── 2. Les boîtes mail : le défaut est la sienne, l'élargi se demande ────
az = extraire(BACKEND / "mail" / "authorization.py",
              {"acces_total", "ROLES_ACCES_SUR_DEMANDE", "ROLE_ACCES_TOTAL"}, {})
verifier("l'accès sur demande vaut pour super_admin ET direction",
         az["acces_total"]("super_admin") and az["acces_total"]("direction"))
verifier("un rôle métier reste soumis aux délégations",
         not az["acces_total"]("commercial") and not az["acces_total"]("terrain"))
src_az = (BACKEND / "mail" / "authorization.py").read_text(encoding="utf-8")
verifier("le DÉFAUT (recherche, rien de nommé) est SA boîte, même pour l'administrateur",
         "LE DÉFAUT EST SA BOÎTE, POUR TOUT LE MONDE" in src_az
         and not re.search(r'if ligne and acces_total\(ligne\["role"\]\):\s*\n\s*return \[TOUTES_LES_BOITES\]',
                           src_az))
verifier("l'accès à une boîte NOMMÉE reste journalisé", "logger.info(\"Accès administrateur" in src_az
         or "Accès administrateur à la boîte" in src_az)

# ── 2bis. Le NOMMAGE d'une boîte suit le RÔLE, pas le défaut de lecture ──
skills_mail = (BACKEND / "mail" / "skills.py").read_text(encoding="utf-8")
verifier("boites_visibles laisse super_admin/direction NOMMER toutes les boîtes connues",
         "acces_total(getattr(user, \"role\", None))" in skills_mail
         and skills_mail.count("acces_total") >= 2)
verifier("boites_mail (geste explicite) lit encore l'annuaire du domaine pour ces rôles",
         "_acces_total(getattr(user, \"role\", None))" in skills_mail)
droits_py = (BACKEND / "skills" / "droits.py").read_text(encoding="utf-8")
verifier("mes_droits DIT la capacité réelle (toutes les boîtes sur demande)",
         "acces_total(role)" in droits_py)
rag_py = (BACKEND / "vectorstore" / "rag.py").read_text(encoding="utf-8")
verifier("le filtrage RAG (le DÉFAUT) reste restreint : il ne teste que le jeton reçu",
         'if "*" in autorisees' in rag_py and "acces_total" not in rag_py)

# ── 3. La direction ne voit pas les super_admin ──────────────────────────
users = (BACKEND / "routers" / "users.py").read_text(encoding="utf-8")
verifier("la liste des utilisateurs filtre les super_admin CÔTÉ SERVEUR pour la direction",
         "u.role <> 'super_admin'" in users
         and 'current_user.role == "super_admin",' in users)
verifier("la direction ne peut pas agir sur un super_admin (désactivation, plages)",
         users.count("DIRECTION_CREATABLE_ROLES") >= 3)

# ── 4. Les onglets Paramètres ────────────────────────────────────────────
sc = (FRONTEND / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
verifier("Utilisateurs et Plages horaires : direction (et super_admin) seulement",
         re.search(r'"utilisateurs", label: "Utilisateurs", roles: \["super_admin", "direction"\]', sc)
         and re.search(r'"plages", label: "Plages horaires", roles: \["super_admin", "direction"\]', sc))
verifier("États des agents, Quotas, Services, Synchronisations, Clés API : super_admin seul",
         all(re.search(rf'"{k}", label: "[^"]+", roles: \["super_admin"\]', sc)
             for k in ("agents", "quotas", "services", "synchro", "cles")))
verifier("l'onglet actif par défaut est le premier VISIBLE du rôle",
         "subTabs[0]?.key" in sc)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
