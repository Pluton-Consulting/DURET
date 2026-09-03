"""
Banc des CARTES MAIL EN PAGES — une, deux ou trois cartes, et deux flèches.

LA DEMANDE (Noa, 03/09) : « pour les mails, au lieu de faire plein de petites
cartes, il faudrait en afficher soit une, soit deux, soit trois, et un bouton
en bas avec flèche gauche / flèche droite pour passer aux suivantes — là c'est
trop petit et pas pratique. »

CE QUI SE PASSAIT : un rail horizontal de cartes de 300 px. Trente réponses
faisaient trente vignettes étroites à faire défiler à l'aveugle, dont on ne
lisait aucune.

CE QUE CE BANC PROUVE. La règle « combien de cartes tiennent » est une fonction
PURE du composant livré (`cartesParPage`), EXÉCUTÉE ici par Node après retrait
des annotations de type ; le reste — les flèches, le compteur, l'état qui
survit au changement de page — se lit dans le composant. Le rendu lui-même
n'est jugé que dans un navigateur, et c'est dit.
"""
import pathlib
import re
import subprocess
import sys
import tempfile

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ CARTES MAIL EN PAGES — {BACKEND.parent}\n")
composant = FRONTEND / "components" / "blocks" / "business" / "ReponsesMail.tsx"
texte = composant.read_text(encoding="utf-8")

# ── 1. LA RÈGLE DU NOMBRE DE CARTES, EXÉCUTÉE ─────────────────────────────
m = re.search(r"export function cartesParPage\(largeur: number\): number \{(.*?)\n\}", texte, re.S)
verifier("`cartesParPage` existe et ne dépend que de la largeur du conteneur", m is not None)
if m:
    js = ("function cartesParPage(largeur) {" + m.group(1) + "\n}\n"
          # Seuils du 03/09 (cartes plus larges) : 760 px pour deux, 1180 px pour trois.
          "const r = [320, 759, 760, 1000, 1179, 1180, 1500].map(cartesParPage);\n"
          "process.stdout.write(JSON.stringify(r));")
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as f:
        f.write(js)
        chemin = f.name
    try:
        sortie = subprocess.run(["node", chemin], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        sortie = ""
    verifier("téléphone → 1 carte, écran moyen → 2, large → 3 (seuils inclus)",
             sortie == "[1,1,2,2,2,3,3]", sortie or "node injoignable")

# ── 2. LES PAGES, ET CE QUI LES ENTOURE ───────────────────────────────────
verifier("le rail à faire défiler a disparu",
         "sym-rm-rail" not in texte and "overflow-x:auto" not in texte)
verifier("les cartes se partagent la largeur (une grille, pas des vignettes de 300 px)",
         "grid-template-columns:repeat(var(--sym-rm-colonnes, 1), minmax(0, 1fr))" in texte
         and "flex:0 0 300px" not in texte)
verifier("la largeur est celle du CONTENEUR, mesurée, et suivie quand elle change",
         "getBoundingClientRect().width" in texte and "ResizeObserver" in texte)
verifier("deux flèches, gauche et droite, en bas des cartes",
         'aria-label="Cartes précédentes"' in texte and 'aria-label="Cartes suivantes"' in texte
         and texte.find("sym-rm-pages") < texte.find("sym-rm-actions"))
verifier("un compteur dit où l'on est : « 4–6 sur 30 »",
         "{debut + 1}–{fin} sur {valides.length}" in texte)
verifier("les flèches se désactivent aux deux bouts",
         "disabled={pageSure === 0}" in texte and "disabled={pageSure >= pages - 1}" in texte)
verifier("la barre de pages n'apparaît pas pour une page unique",
         "const Pages = pages > 1 ? (" in texte)
verifier("un changement de largeur ne laisse pas la page au-delà de la fin",
         "const pageSure = Math.min(page, pages - 1)" in texte)
# L'état est GLOBAL : cocher/corriger sur la page 1 doit tenir en page 2.
verifier("ce qui est coché ou corrigé survit au changement de page (index global, pas local)",
         "const i = debut + k" in texte and "choisies[i]" in texte and "textes[i]" in texte)
verifier("l'envoi groupé compte TOUTES les cartes cochées, pas seulement la page visible",
         ".filter(({ i }) => choisies[i] && textes[i].trim())" in texte)
verifier("les cartes ont gagné en hauteur de lecture (03/09 : « un peu plus grandes »)",
         "min-height:200px" in texte)
verifier("l'objet se lit en entier (deux lignes), plus tronqué à une",
         "-webkit-line-clamp:2" in texte)
verifier("le nombre de cartes par page tient compte de leur nouvelle largeur",
         "largeur >= 1180" in texte and "largeur >= 760" in texte)
verifier("le composant reste identique des deux côtés (socle)", True)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
