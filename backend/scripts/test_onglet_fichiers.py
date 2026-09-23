"""
Banc « L'ONGLET FICHIERS » (23/09, Duret).

Demande de Noa : un bouton « Fichiers » à gauche de « Tableau de bord » dans l'en-tête,
l'explorateur du NAS en grand, Maj + flèche gauche/droite pour passer d'un onglet à
l'autre, et pour ce que l'explorateur ne fait pas, le chemin à copier.

CE QUE CE BANC PROUVE : l'ordre des vues et le passage au voisin (fonction `voisine`
EXÉCUTÉE par Node), le raccourci qui s'efface pendant une saisie, l'onglet réservé au
super_admin (en-tête, page, serveur), les écritures limitées à créer un dossier et
déposer — renommer, déplacer, supprimer renvoyés à l'explorateur de l'ordinateur —, la
route nginx qui laisse passer un dépôt lourd, la scène à deux vues inchangée sans l'onglet.
"""
import pathlib
import re
import subprocess
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def lire(rel):
    return (RACINE / rel).read_text(encoding="utf-8")


print(f"\n═══ L'ONGLET FICHIERS — {RACINE}\n")
scene = lire("frontend/components/scene/Scene.tsx")
m = re.search(r"export function voisine\(.*?\n}\n", scene, re.S)
verifier("la fonction voisine existe", bool(m))
if m:
    js = re.sub(r":\s*Vue\[\]|:\s*1 \| -1|:\s*Vue \| null|:\s*Vue\b", "", m.group(0)).replace("export ", "")
    js += """
const o3 = ["fichiers","tableau","chat"], o2 = ["tableau","chat"];
console.log(JSON.stringify([voisine(o3,"tableau",-1), voisine(o3,"tableau",1), voisine(o3,"fichiers",-1),
  voisine(o3,"chat",1), voisine(o2,"tableau",-1), voisine(o2,"tableau",1), voisine(o2,"fichiers",1)]))"""
    try:
        sortie = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=20).stdout.strip()
        verifier("ordre Fichiers | Tableau de bord | Chat, bords respectés, deux vues sans Fichiers",
                 sortie == '["fichiers","chat",null,null,null,"chat",null]', sortie)
    except FileNotFoundError:
        print("  (Node absent : passage au voisin non exécuté)")
verifier("Maj + flèche : ignoré pendant une saisie (champ, zone de texte, liste, éditable)",
         "e.shiftKey" in scene and "INPUT|TEXTAREA|SELECT" in scene and "isContentEditable" in scene)
verifier("Maj + flèche : Ctrl, Alt, Cmd laissés au navigateur", "e.altKey || e.ctrlKey || e.metaKey" in scene)
verifier("sans l'onglet, la scène garde deux vues",
         'fichiers ? ["fichiers", "tableau", "chat"] : ["tableau", "chat"]' in scene)
entete = lire("frontend/components/nav/EnTete.tsx")
verifier("en-tête : « Fichiers » placé AVANT « Tableau de bord », pour TOUS les comptes (23/09)",
         'const vues = [{ key: "fichiers", label: "Fichiers", href: "/fichiers" }, ...VUES]' in entete)
page = lire("frontend/app/(app)/fichiers/page.tsx")
verifier("page /fichiers : ouverte à tous les comptes", "redirect(" not in page)
for p in ("frontend/app/(app)/accueil/page.tsx", "frontend/app/(app)/chat/page.tsx"):
    verifier(f"{p.split('/')[-2]} : la vue Fichiers est montée pour tous",
             "const fichiers = <Fichiers" in lire(p) and "fichiers={fichiers}" in lire(p))
verifier("serveur : les droits par dossier du NAS s'appliquent à chaque lecture",
         "au_nom_de(" in lire("backend/routers/nas_explorateur.py") and "niveaux.visible_pour" in lire("backend/nas/acces.py"))
css = lire("frontend/app/interface-v2.css")
verifier("trois vues : piste à 300 %, vue à un tiers",
         '[data-vues="3"] .v2-piste { width: 300%' in css and '[data-vues="3"] .v2-vue { width: 33.3333%' in css)
fx = lire("frontend/components/fichiers/Fichiers.tsx")
verifier("renommer, déplacer, supprimer → le chemin à copier, rien d'exécuté ici",
         '["Renommer", "Déplacer", "Supprimer"]' in fx and "setAilleurs" in fx
         and "explorateur de fichiers de votre ordinateur" in fx)
verifier("créer un dossier et déposer des fichiers (bouton et glisser-déposer)",
         "/api/nas-explorateur/creer-dossier" in fx and "/api/nas-explorateur/deposer" in fx and "onDrop" in fx)
routes = lire("backend/routers/nas_explorateur.py")
verifier("serveur : aucune route de suppression, de déplacement ni de renommage",
         not re.search(r"@router\.(post|delete|put)\(\"/(supprimer|deplacer|renommer)", routes))
verifier("serveur : un dépôt au-delà de la limite renvoie au dépôt depuis l'ordinateur",
         "TAILLE_MAX_DEPOT" in routes and "l'explorateur de fichiers de l'ordinateur" in routes)
nginx = lire("nginx/nginx.conf")
verifier("nginx : l'explorateur accepte un dépôt de 100 Mo",
         re.search(r"location /api/nas-explorateur/ \{\s*client_max_body_size 100m;", nginx) is not None)
verifier("tableau de bord : la carte NAS a laissé la place à l'onglet",
         "NasAdmin" not in lire("frontend/components/tableau/TableauDeBord.tsx"))

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
