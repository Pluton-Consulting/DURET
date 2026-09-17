"""
Banc « L'IMAGE ARRIVE À L'ENDROIT, ET LA TOURNER N'EST PAS LA REDESSINER » — 17/09,
14:47, Symbiose. « Tourne l'image pour que je la voie à l'endroit » : parti à
`modifier_visuel` (tirage facturé, image redessinée), et sur la MAUVAISE photo — le
modèle avait pris celle que l'assistant décrivait plus haut comme « pivotée de 90° ».
La racine : `_nettoyer_image` retirait l'EXIF sans APPLIQUER l'orientation ; une photo
de téléphone prise en portrait restait couchée partout.

Pillow requis pour la partie exécutée (présent dans l'image ; absent du poste, le
banc le dit et ne juge que le contrat).
"""
import ast
import io
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
echecs = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def fonction(src, nom):
    return next(ast.get_source_segment(src, n) for n in ast.walk(ast.parse(src))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom)


print("\n═══ L'IMAGE À L'ENDROIT —", BACKEND.parent)
a2 = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
# Duret : pas de module visuels (offre propre à Symbiose) — seule la partie SOCLE est jugée ici.
a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
plans = (BACKEND / "skills" / "plans_dossier.py").read_text(encoding="utf-8")

try:
    from PIL import Image
    pillow = True
except ImportError:
    pillow = False
    print("  (Pillow absent de ce poste : la partie exécutée est sautée, le contrat est jugé)")

if pillow:
    esp = {"io": io, "_MAX_IMG_WIDTH": 1600}
    exec(fonction(a2, "_nettoyer_image"), esp)
    # Une photo de téléphone : pixels COUCHÉS (300 × 200), étiquette EXIF 6 = « tourner de 90° ».
    img = Image.new("RGB", (300, 200), "white")
    img.putpixel((0, 0), (255, 0, 0))                    # le coin haut-gauche des pixels stockés
    exif = Image.Exif(); exif[274] = 6
    brut = io.BytesIO(); img.save(brut, format="JPEG", exif=exif, quality=95)
    net = Image.open(io.BytesIO(esp["_nettoyer_image"](brut.getvalue())))
    verifier("une photo de téléphone prise en portrait sort DEBOUT (200 × 300), plus couchée", net.size == (200, 300), str(net.size))
    verifier("l'étiquette d'orientation a bien disparu avec le reste de l'EXIF", net.getexif().get(274, 1) == 1)
    droit = Image.new("RGB", (300, 200), "white"); b2 = io.BytesIO(); droit.save(b2, format="JPEG")
    verifier("une image sans étiquette n'est pas touchée (300 × 200)", Image.open(io.BytesIO(esp["_nettoyer_image"](b2.getvalue()))).size == (300, 200))

verifier("l'orientation EXIF s'applique AVANT le ré-encodage, aux deux lectures d'image",
         "ImageOps.exif_transpose(Image.open(io.BytesIO(donnees))).convert(\"RGB\")" in a2 and "ImageOps.exif_transpose(brute)" in plans)
print("\n" + "═" * 70)
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec\n")
