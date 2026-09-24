"""
Banc « LES BLOCS DU CHAT SE REDIMENSIONNENT À LA MAIN » (24/09, Duret).

Demande de Noa : « quand il met des composants dans le chat, comme des tableaux, on
doit pouvoir les redimensionner à la main, juste les agrandir en largeur ou en hauteur ».

CE QUE CE BANC PROUVE (contrat sur les fichiers livrés — aucun banc hors navigateur ne
peut tirer une poignée) : chaque bloc rendu est enveloppé par `BlocRedimensionnable`,
sauf les pastilles de suite et les badges ; la poignée est celle du navigateur
(`resize: both`) ; tant qu'on n'a pas tiré, la largeur commune et la hauteur qui défile
tiennent ; après, l'enfant suit le cadre ; au téléphone, pas de poignée.
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

verifier("le composant pose la classe et l'état « redimensionné »",
         'className="sym-bloc-redim"' in comp and 'data-redim={redimensionne ? "1" : "0"}' in comp)
verifier("l'état bascule sur un vrai geste (ResizeObserver, seuil de 12 px), pas sur un reflow",
         "new ResizeObserver" in comp and "> 12" in comp)
verifier("chaque bloc rendu est enveloppé", "<BlocRedimensionnable>{node}</BlocRedimensionnable>" in rend
         and "<BlocRedimensionnable>{renderBlock(b" in rend)
verifier("les pastilles de suite et les badges restent fixes",
         re.search(r'\["quick_replies", "badge", "suggestions"\]\.includes', rend) is not None)
bloc = theme.split(".sym-bloc-redim {", 1)[1].split("}", 1)[0]
verifier("poignée native : resize: both, overflow: auto", "resize: both" in bloc and "overflow: auto" in bloc)
verifier("largeur commune tant qu'on n'a pas tiré", "width: min(var(--bloc-largeur), 100%)" in bloc)
verifier("après un geste : l'enfant suit le cadre, sa hauteur maximale cède",
         '.sym-bloc-redim[data-redim="1"] > * { width: 100%; max-height: none !important; height: 100%; }' in theme)
verifier("au téléphone : pas de poignée", ".sym-bloc-redim { resize: none; width: 100%; }" in mobile
         and mobile.find(".sym-bloc-redim") > mobile.find("@media (max-width: 640px)"))

print(f"\n{'✅ tout passe' if not echecs else f'❌ {len(echecs)} échec(s)'}\n")
sys.exit(1 if echecs else 0)
