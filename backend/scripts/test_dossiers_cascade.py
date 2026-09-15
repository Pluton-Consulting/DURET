"""
Banc des DOSSIERS DU MAIL EN CASCADE — Paramètres → Utilisateurs (15/09, Duret).

Demande de Noa : « quand il y en a beaucoup c'est horrible, fais des cascades en
fonction du degré du dossier : si un premier degré est coché, ça affiche ses
sous-dossiers, etc. »

CE QUE CE BANC PROUVE :
  · `arbreDossiers` EXÉCUTÉ par Node (TypeScript transpilé à la volée) sur une
    boîte Gmail de la forme réelle : « [Gmail]/… » ne fait pas un niveau, les
    chemins « A/B/C » donnent trois degrés, un niveau absent de la boîte devient
    un titre, les envoyés restent au premier degré, l'ordre est alphabétique ;
  · le contrat de l'écran : seuls les enfants d'un dossier COCHÉ s'affichent,
    décocher retire aussi les sous-dossiers cochés, la liste défile.
Tombe sur la version d'avant (`arbreDossiers` absent).

Usage : python backend/scripts/test_dossiers_cascade.py [backend]
"""
import json
import pathlib
import subprocess
import sys

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
front = racine.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


src = (front / "app" / "(app)" / "parametres" / "SettingsClient.tsx").read_text(encoding="utf-8")
print("1. L'arbre, exécuté")
if "export function arbreDossiers" not in src:
    verifier("SettingsClient porte `arbreDossiers`", False, "absent")
else:
    debut = src.index("interface NoeudDossier")
    fin = src.index("/** Tous les dossiers réels sous un nœud")
    extrait = "interface DossierBoite { nom: string; libelle: string }\n" + src[debut:fin]
    dossiers = [
        {"nom": "envoyes", "libelle": "Messages envoyés"},
        {"nom": "Clients", "libelle": "Clients"},
        {"nom": "Clients/Martin", "libelle": "Clients/Martin"},
        {"nom": "Clients/Martin/Devis", "libelle": "Clients/Martin/Devis"},
        {"nom": "Clients/Albert", "libelle": "Clients/Albert"},
        {"nom": "Fournisseurs/BTF", "libelle": "Fournisseurs/BTF"},
        {"nom": "Compta", "libelle": "Compta"},
        {"nom": "[Gmail]/Important2", "libelle": "Important2"},
    ]
    script = f"""
const ts = require({json.dumps(str(front / 'node_modules' / 'typescript'))});
const code = ts.transpileModule({json.dumps(extrait)}, {{ compilerOptions: {{ module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }} }}).outputText;
const m = {{ exports: {{}} }};
new Function("module", "exports", code)(m, m.exports);
const simple = (l) => l.map((n) => ({{ l: n.libelle, d: n.dossier ? n.dossier.nom : null, e: simple(n.enfants) }}));
console.log(JSON.stringify(simple(m.exports.arbreDossiers({json.dumps(dossiers)}))));
"""
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    if r.returncode != 0:
        verifier("Node exécute l'arbre", False, r.stderr[-400:])
    else:
        arbre = json.loads(r.stdout)
        premiers = [n["l"] for n in arbre]
        verifier("premier degré : les envoyés en tête, puis l'ordre alphabétique",
                 premiers == ["Messages envoyés", "Clients", "Compta", "Fournisseurs", "Important2"], premiers)
        clients = next(n for n in arbre if n["l"] == "Clients")
        verifier("« Clients » est un vrai dossier avec deux sous-dossiers, Albert puis Martin",
                 clients["d"] == "Clients" and [e["l"] for e in clients["e"]] == ["Albert", "Martin"], clients)
        martin = next(e for e in clients["e"] if e["l"] == "Martin")
        verifier("troisième degré : Clients/Martin/Devis sous Martin, libellé court",
                 [e["l"] for e in martin["e"]] == ["Devis"] and martin["e"][0]["d"] == "Clients/Martin/Devis", martin)
        fourn = next(n for n in arbre if n["l"] == "Fournisseurs")
        verifier("un niveau absent de la boîte devient un titre (pas de case)",
                 fourn["d"] is None and fourn["e"][0]["d"] == "Fournisseurs/BTF", fourn)
        imp = next(n for n in arbre if n["l"] == "Important2")
        verifier("« [Gmail]/… » ne fait pas un niveau", imp["d"] == "[Gmail]/Important2" and not imp["e"], imp)

print("2. Le contrat de l'écran")
cases = src[src.index("function CasesDossiers"):src.index("/* ---------- USERS TAB ---------- */")]
verifier("les sous-dossiers ne s'affichent que sous un dossier coché (ou un titre)",
         "const ouvert = !n.dossier || coche" in cases and "ouvert && n.enfants.length > 0" in cases)
verifier("décocher retire aussi les sous-dossiers cochés", "new Set(nomsSous(n))" in cases)
verifier("la liste défile au lieu de remplir l'écran", "maxHeight: 360" in cases and 'overflowY: "auto"' in cases)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
