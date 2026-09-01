"""
Fabrique le logo des mails — `backend/emails/logo.png`.

POURQUOI UN PNG, ET PAS LE SVG DU SITE. Aucun client de messagerie ne rend le
SVG : ni Outlook, ni Gmail, ni Apple Mail. Et une image distante est bloquée par
défaut chez la plupart — celle-ci vivrait de toute façon derrière le VPN, donc
inatteignable depuis un téléphone hors réseau. Le seul chemin qui affiche
vraiment un logo dans un mail est une pièce jointe « inline » référencée par
`cid:`, et elle doit être matricielle.

DEUX FAÇONS DE POSER CE FICHIER, au choix :

  1. Déposer directement un PNG à `backend/emails/logo.png` — c'est le plus
     simple si l'entreprise a déjà son logo en image. Hauteur utile : 72 px
     (l'en-tête l'affiche à 36 px, on double pour les écrans à forte densité).
     Fond TRANSPARENT de préférence : l'en-tête du mail est sombre.

  2. Lancer ce script, qui convertit le SVG du site. Il exige `cairosvg`, qui
     n'est ni sur le Mac ni dans l'image du conteneur : à installer le temps de
     la conversion (`pip install cairosvg`), pas à ajouter aux dépendances du
     produit pour un fichier qu'on génère une fois.

TANT QUE LE FICHIER N'EXISTE PAS, RIEN NE CASSE : `emails/marque.logo_image()`
rend None et le gabarit retombe sur la pastille dessinée en HTML. Un mail sans
logo reste lisible ; un mail avec un cadre vide fait négligé.

    python backend/scripts/logo_mail.py [chemin/vers/logo.svg]
"""
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent.parent
SVG_PAR_DEFAUT = RACINE / "frontend" / "public" / "duret-sols.svg"
CIBLE = RACINE / "backend" / "emails" / "logo.png"
HAUTEUR = 72


def main() -> int:
    svg = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else SVG_PAR_DEFAUT
    if not svg.exists():
        print(f"✗ SVG introuvable : {svg}")
        return 1
    try:
        import cairosvg
    except ImportError:
        print("✗ `cairosvg` n'est pas installé.\n"
              "  Deux options :\n"
              "    pip install cairosvg   puis relancer ce script\n"
              f"    ou déposer un PNG directement à {CIBLE}\n"
              "  (hauteur ~72 px, fond transparent — l'en-tête est sombre)")
        return 2

    CIBLE.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(url=str(svg), write_to=str(CIBLE), output_height=HAUTEUR)
    print(f"✓ {CIBLE} écrit ({CIBLE.stat().st_size} octets, {HAUTEUR} px de haut)")
    print("  Le prochain mail de connexion le portera. Aucun redéploiement du "
          "code n'est nécessaire au-delà du dépôt du fichier.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
