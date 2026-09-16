"""
Banc « UN VISUEL A UN PROPRIÉTAIRE, ET LE JETON NE SORT PAS » — audit du 15/09, fiche D-03/S-03.

Deux défauts relevés par l'audit :
  · la route `/api/visuels/{clé}` vérifiait la CONNEXION, pas le propriétaire :
    toute clé connue d'un compte ouvrait la photo d'un autre ; joindre ou insérer
    un visuel dans un document passait par le même dépôt, sans contrôle ;
  · l'aperçu d'un document et le bouton « Télécharger » envoyaient
    `Authorization: Bearer <jeton>` à l'URL reçue, y compris une URL ABSOLUE d'un
    site tiers.

CE BANC PROUVE (dépôt réel dans un dossier temporaire, deux comptes) :
  · un dépôt fait pendant un geste note son propriétaire (contexte du lecteur) ;
    l'autre compte ne peut ni le lire ni le joindre ; le super-administrateur si ;
    le même contenu déposé par deux personnes leur appartient à toutes deux ;
  · un visuel d'avant le correctif (aucun propriétaire noté) reste lisible ;
  · la route et `mail/attaches._du_depot` appliquent la règle ;
  · `lib/origineBackend.ts` (exécuté par Node) ne pose le jeton que pour le
    backend de l'application, et les deux composants s'en servent.

Usage : python backend/scripts/test_visuels_proprietaire.py [backend]
"""
import asyncio
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
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


print(f"\n═══ VISUELS : PROPRIÉTAIRE ET JETON — {BACKEND.parent}\n")
os.environ["DOCUMENTS_DIR"] = tempfile.mkdtemp(prefix="banc-visuels-")
sys.modules.setdefault("httpx", types.ModuleType("httpx"))
for paquet in ("security", "visuels", "mail"):
    m = types.ModuleType(paquet)
    m.__path__ = []
    sys.modules[paquet] = m
lecteur = charger("security.lecteur", "security/lecteur.py")
depot = charger("visuels.depot", "visuels/depot.py")
sys.modules["visuels"].depot = depot

A = types.SimpleNamespace(id="compte-a", role="direction")
B = types.SimpleNamespace(id="compte-b", role="bureau_etudes")
ADMIN = types.SimpleNamespace(id="compte-admin", role="super_admin")

print("1. Le dépôt note son propriétaire")
with lecteur.au_nom_de(A):
    cle = depot.deposer_octets(b"\x89PNG photo de chantier A", "image/png")
verifier("un dépôt pendant le geste de A appartient à A", depot.proprietaires(cle) == ["compte-a"], depot.proprietaires(cle))
verifier("A peut le lire ; B NON ; le super-administrateur oui",
         depot.peut_lire(cle, A) and not depot.peut_lire(cle, B) and depot.peut_lire(cle, ADMIN))
with lecteur.au_nom_de(B):
    cle_b = depot.deposer_octets(b"\x89PNG photo de chantier A", "image/png")
verifier("le MÊME contenu déposé par B : une seule clé, deux propriétaires",
         cle_b == cle and sorted(depot.proprietaires(cle)) == ["compte-a", "compte-b"] and depot.peut_lire(cle, B))
with lecteur.en_systeme():
    cle_sys = depot.deposer_octets(b"\x89PNG vignette de synchro", "image/png")
verifier("un dépôt du système (synchronisation) n'invente pas de propriétaire", depot.proprietaires(cle_sys) is None)
ancienne = depot.deposer_octets(b"\x89PNG image d'avant le correctif", "image/png")
verifier("un visuel d'avant le correctif (aucun propriétaire) reste lisible", depot.peut_lire(ancienne, B))
with lecteur.au_nom_de(A):
    depot.deposer_octets(b"\x89PNG image d'avant le correctif", "image/png")
verifier("le même contenu redéposé par A ne RÉCLAME pas l'image ancienne : B la voit toujours",
         depot.proprietaires(ancienne) is None and depot.peut_lire(ancienne, B))
import threading


def _deposer_en_parallele(personne, octets, cles):
    with lecteur.au_nom_de(personne):
        cles.append(depot.deposer_octets(octets, "image/png"))


cles_par = []
fils = [threading.Thread(target=_deposer_en_parallele, args=(A if i % 2 else B, b"\x89PNG deux personnes, un instant", cles_par))
        for i in range(12)]
for t in fils:
    t.start()
for t in fils:
    t.join()
verifier("douze dépôts simultanés du même contenu par A et B : les deux sont propriétaires",
         len(set(cles_par)) == 1 and sorted(depot.proprietaires(cles_par[0]) or []) == ["compte-a", "compte-b"],
         (set(cles_par), depot.proprietaires(cles_par[0])))
verifier("aucun fichier temporaire ne traîne", not list(depot.DOSSIER.glob("*.tmp")))
verifier("un nom de clé qui n'est pas une empreinte ne vaut rien", depot.proprietaires("../etc/passwd") is None
         and depot._chemin_acces("../x") is None)
verifier("l'identifiant du lecteur ne fuit pas hors du geste", lecteur.id_lecteur() is None)

print("2. La route et les pièces jointes appliquent la règle")
routeur = (BACKEND / "routers" / "visuels.py").read_text(encoding="utf-8")
verifier("la route vérifie le propriétaire et répond comme un visuel absent",
         "lire(cle) if peut_lire(cle, current_user) else None" in routeur)
verifier("le cache du navigateur distingue les sessions (poste partagé entre profils)",
         '"Vary": "Authorization"' in routeur)
attaches = (BACKEND / "mail" / "attaches.py").read_text(encoding="utf-8")
debut = attaches.index("async def _du_depot(")
fin = attaches.index("async def _de_l_atelier(")
espace = {}
exec(compile(attaches[debut:fin], "attaches", "exec"), espace)
octets_b, _, _ = asyncio.run(espace["_du_depot"](cle, B))
autre = depot.deposer_octets(b"\x89PNG plan de A seulement", "image/png", proprietaire="compte-a")
refus, _, _ = asyncio.run(espace["_du_depot"](autre, B))
permis, _, _ = asyncio.run(espace["_du_depot"](autre, A))
verifier("joindre un visuel : son propriétaire oui, un autre compte non",
         octets_b and refus is None and permis == b"\x89PNG plan de A seulement")
verifier("l'appel de la résolution passe l'utilisateur", "await _du_depot(m.group(1).lower(), user)" in attaches)
agent2 = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
verifier("les photos jointes au chat appartiennent à la personne du tour",
         "with au_nom_de(SimpleNamespace(id=state.get(\"user_id\")" in agent2)

print("2 bis. Une image reçue par mail entre dans un document, dans SA boîte et avec les droits")
VUS = []


async def _resoudre_pieces(refs, user, boite, plafond=None):
    VUS.append(boite)
    return [{"nom": "photo.png", "mime": "image/png", "octets": b"\x89PNG"}], []


async def _verifier_acces(user, boite, envoi=False):
    if user.id != "compte-a":
        raise PermissionError("403")
    return boite


for nom, attrs in {"mail.attaches": {"resoudre": _resoudre_pieces},
                   "mail.lecture": {"boite_de_piece": lambda ref: "accueil@exemple-sols.fr" if ref == "0123456789abcdef" else None},
                   "mail.authorization": {"verifier_acces": _verifier_acces},
                   "bureautique": {}, "bureautique.modele": {"CLES_IMAGE": ("image",), "RE_IMAGE_RANGEE": __import__("re").compile("x^"),
                                                             "_TYPES": {"image": "image"}}}.items():
    m = types.ModuleType(nom)
    m.__dict__.update(attrs)
    m.__path__ = []
    sys.modules[nom] = m
images = charger("bureautique.images", "bureautique/images.py")
images.normaliser_octets = lambda o, m: (o, "png")
octets_img, _, _ = asyncio.run(images.resoudre("piece:0123456789abcdef", A))
verifier("la pièce se résout dans la boîte d'où elle vient (plus une boîte vide)",
         VUS[-1] == "accueil@exemple-sols.fr" and octets_img == b"\x89PNG", VUS)
try:
    asyncio.run(images.resoudre("piece:0123456789abcdef", B))
    verifier("sans droit sur cette boîte, la pièce est refusée", False)
except images.ImageRefusee as e:
    verifier("sans droit sur cette boîte, la pièce est refusée, et c'est dit", "pas accès" in str(e))

print("2 ter. Les visuels anciens : rattachés quand les messages l'établissent, jamais devinés")
rattacher = charger("rattacher_visuels", "scripts/rattacher_visuels.py")
vieux_a = depot.deposer_octets(b"\x89PNG vieux rendu de A", "image/png")
vieux_b = depot.deposer_octets(b"\x89PNG vieux rendu vu par A et B", "image/png")
orphelin = depot.deposer_octets(b"\x89PNG vieux rendu que plus rien ne cite", "image/png")
sans = rattacher.cles_sans_proprietaire(depot.DOSSIER)
verifier("le constat liste les visuels sans propriétaire, pas les autres",
         {vieux_a, vieux_b, orphelin} <= sans and cle not in sans, sans)
messages = [("compte-a", '```ui\n{"type": "visuel", "images": [{"cle": "%s"}, {"cle": "%s"}]}\n```' % (vieux_a, vieux_b)),
            ("compte-b", '{"pieces": [{"nom": "photo.jpg", "cle": "%s"}]}' % vieux_b),
            ("compte-b", "la clé %sff n'est pas une clé (trop longue)" % orphelin)]
etablis = rattacher.etablir(sans, messages)
verifier("les propriétaires viennent des conversations qui citent la clé (bloc visuel, pièces)",
         etablis.get(vieux_a) == {"compte-a"} and etablis.get(vieux_b) == {"compte-a", "compte-b"}
         and orphelin not in etablis, etablis)
constat = rattacher.appliquer(depot, sans, etablis, ecrire=False, fermer=False)
verifier("le constat seul n'écrit rien", depot.proprietaires(vieux_a) is None and constat["indetermines"] >= 1, constat)
rattacher.appliquer(depot, sans, etablis, ecrire=True, fermer=False)
verifier("--ecrire : A voit son vieux rendu, B ne le voit plus ; l'orphelin reste lisible",
         depot.peut_lire(vieux_a, A) and not depot.peut_lire(vieux_a, B)
         and depot.peut_lire(vieux_b, B) and depot.peut_lire(orphelin, B))
rattacher.appliquer(depot, rattacher.cles_sans_proprietaire(depot.DOSSIER), {}, ecrire=True, fermer=True)
verifier("--fermer-indetermines : l'orphelin est réservé au super-administrateur, rien n'est effacé",
         not depot.peut_lire(orphelin, B) and depot.peut_lire(orphelin, ADMIN) and depot.lire(orphelin))
with lecteur.au_nom_de(B):
    depot.deposer_octets(b"\x89PNG vieux rendu que plus rien ne cite", "image/png")
verifier("quelqu'un qui redépose l'image réservée la retrouve", depot.peut_lire(orphelin, B))

print("3. Le jeton ne part que vers le backend (exécuté par Node)")
helper = FRONTEND / "lib" / "origineBackend.ts"
node = shutil.which("node")
if not helper.exists():
    verifier("lib/origineBackend.ts existe", False)
elif not node:
    print("  (Node absent : contrôle du jeton non joué)")
else:
    script = r'''
const fs = require("fs")
let src = fs.readFileSync(process.argv[1], "utf8")
src = src.replace(/export function/g, "function").replace(/:\s*\{ adresse: string; authentifier: boolean \}/g, "")
  .replace(/\((url): string, (apiUrl)\?: string, (jeton)\?: string\): Record<string, string>/, "($1, $2, $3)")
  .replace(/\((url): string, (apiUrl)\?: string\)/, "($1, $2)").replace(/let (backend|adresse): \w+/g, "let $1")
globalThis.window = { location: { origin: "https://app.exemple.fr" } }
const f = new Function(src + "; return { cibleDocument, entetesPour }")()
const cas = [["/api/documents/a", "", true], ["https://app.exemple.fr/api/visuels/x", "", true],
             ["https://tiers.exemple/x.pdf", "", false], ["//tiers.exemple/x", "", false],
             ["javascript:alert(1)", "", false], ["http://localhost:8000/api/documents/a", "http://localhost:8000", true]]
const faux = cas.filter(([u, api, att]) => f.cibleDocument(u, api).authentifier !== att)
const entetes = Object.keys(f.entetesPour("https://tiers.exemple/x", "", "JWT")).length
console.log(JSON.stringify({ faux, entetes }))
'''
    sortie = subprocess.run([node, "-e", script, str(helper)], capture_output=True, text=True, timeout=30)
    try:
        import json
        r = json.loads(sortie.stdout.strip().splitlines()[-1])
        verifier("relatif et même origine : jeton ; tiers, « //tiers », javascript: : jamais",
                 r["faux"] == [] and r["entetes"] == 0, r)
    except Exception as e:  # noqa: BLE001
        verifier("le contrôle Node s'exécute", False, (e, sortie.stderr[-300:]))
    for composant in ("components/blocks/business/FileCard.tsx", "components/chat/ApercuDocument.tsx"):
        src = (FRONTEND / composant).read_text(encoding="utf-8")
        verifier(f"{composant.split('/')[-1]} passe par cibleDocument, sans jeton inconditionnel",
                 "cibleDocument(url, apiUrl)" in src and "authentifier && backendToken" in src
                 and 'url.startsWith("http") ? url' not in src)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
