"""
Banc « LES BLOCS DU CHAT SE REDIMENSIONNENT À LA MAIN » (24/09, Duret).

Demande de Noa : « quand il met des composants dans le chat, comme des tableaux, on
doit pouvoir les redimensionner à la main, juste les agrandir en largeur ou en hauteur ».
Puis, sur la version déployée avec la poignée NATIVE (`resize: both`) : « j'arrive pas
à redimensionner les tableaux du chat, on doit pouvoir » → poignée MAISON.

CE QUE CE BANC PROUVE (contrat sur les fichiers livrés — aucun banc hors navigateur ne
peut tirer une poignée) : chaque bloc rendu est enveloppé par `BlocRedimensionnable`,
sauf les pastilles de suite et les badges ; le cadre porte une poignée VISIBLE au coin,
enfant du cadre (pas du contenu qui défile), tirée par pointer capture, qui pose
largeur et hauteur en style, bornée (220 × 48 au moins, jamais plus large que la
colonne), et que le double-clic remet à zéro ; le tirage n'atteint pas la scène
(balayage) ; tant qu'on n'a pas tiré, la largeur commune et la hauteur qui défile
tiennent ; après, l'enfant suit le cadre ; au téléphone, pas de poignée ; la poignée
native a disparu (deux poignées au même coin se gêneraient).
"""
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONT = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LES BLOCS SE REDIMENSIONNENT — {FRONT}\n")
comp = (FRONT / "components" / "chat" / "BlocRedimensionnable.tsx").read_text(encoding="utf-8")
rend = (FRONT / "components" / "chat" / "MessageRenderer.tsx").read_text(encoding="utf-8")
theme = (FRONT / "app" / "theme.css").read_text(encoding="utf-8")
mobile = (FRONT / "app" / "mobile.css").read_text(encoding="utf-8")

verifier("chaque bloc rendu est enveloppé", "<BlocRedimensionnable>{node}</BlocRedimensionnable>" in rend
         and "<BlocRedimensionnable>{renderBlock(b" in rend)
verifier("les pastilles de suite et les badges restent fixes",
         re.search(r'\["quick_replies", "badge", "suggestions"\]\.includes', rend) is not None)
verifier("deux couches : le cadre et le contenu, la poignée enfant du CADRE",
         'className="sym-bloc-redim"' in comp and 'className="sym-bloc-redim-contenu">{children}' in comp
         and comp.index('className="sym-bloc-redim-contenu"') < comp.index('className="sym-redim-coin"'))
verifier("la poignée se tire (pointerdown → capture → pointermove) et pose largeur ET hauteur en style",
         "onPointerDown={tirer}" in comp and "setPointerCapture(e.pointerId)" in comp
         and 'addEventListener("pointermove", bouger)' in comp
         and "el.style.width = " in comp and "el.style.height = " in comp)
verifier("bornes : 220 × 48 au moins, jamais plus large que la colonne du fil",
         "LARGEUR_MIN = 220" in comp and "HAUTEUR_MIN = 48" in comp
         and "Math.min(largeurMax" in comp and "parentElement.getBoundingClientRect().width" in comp)
verifier("le tirage n'atteint pas la scène (stopPropagation) ni la sélection de texte (preventDefault)",
         "e.stopPropagation()" in comp and "e.preventDefault()" in comp)
verifier("double-clic sur le coin : taille d'origine (styles effacés, état remis)",
         "onDoubleClick={remettre}" in comp and 'el.style.width = ""' in comp and "setRedimensionne(false)" in comp)
verifier("l'état « redimensionné » ne se pose qu'au tirage",
         'data-redim={redimensionne ? "1" : "0"}' in comp and "setRedimensionne(true)" in comp
         and "ResizeObserver" not in comp)
verifier("la poignée est nommée pour l'accessibilité", 'role="separator"' in comp and "aria-label=" in comp)
bloc = theme.split(".sym-bloc-redim {", 1)[1].split("}", 1)[0]
verifier("le cadre est le repère de la poignée (position: relative), largeur commune tant qu'on n'a pas tiré",
         "position: relative" in bloc and "width: min(var(--bloc-largeur), 100%)" in bloc)
verifier("plus de poignée native (deux poignées au même coin se gêneraient)",
         "resize: both;" not in theme and "::-webkit-resizer" not in theme)
coin = theme.split(".sym-redim-coin {", 1)[1].split("}", 1)[0]
verifier("la poignée : coin bas-droit, visible, curseur de redimensionnement, sans geste tactile parasite",
         "position: absolute" in coin and "right: 0" in coin and "bottom: 0" in coin
         and "cursor: nwse-resize" in coin and "touch-action: none" in coin and "background:" in coin)
verifier("après un geste : le contenu défile dans le cadre et l'enfant le suit, sa hauteur maximale cède",
         '.sym-bloc-redim[data-redim="1"] > .sym-bloc-redim-contenu { overflow: auto; }' in theme
         and '.sym-bloc-redim[data-redim="1"] > .sym-bloc-redim-contenu > * { width: 100%; height: 100%; max-height: none !important; }' in theme)
verifier("au téléphone : pas de poignée", ".sym-redim-coin { display: none; }" in mobile
         and mobile.find(".sym-redim-coin") > mobile.find("@media (max-width: 640px)"))

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
