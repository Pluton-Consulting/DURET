"""
Vocabulaire des documents produits par l'assistant.

POURQUOI UN FORMAT DÉCLARATIF, et pas du code généré. Faire écrire du
python-docx au modèle serait plus souple sur le papier et ingérable en pratique :
du code produit par un modèle doit être exécuté, donc isolé, donc bridé — et il
échoue de mille façons qu'aucune vérification n'anticipe. Ici le modèle décrit
CE QU'IL VEUT ; le rendu est du code écrit une fois, testé, identique à chaque
appel. Un élément inconnu est ignoré, jamais exécuté.

POURQUOI PAR MORCEAUX. Un rapport de deux cents pages ne tient pas dans une
réponse de modèle. Le document s'ouvre, se remplit en autant d'appels que
nécessaire, puis se ferme. Chaque ajout est écrit sur DISQUE : la taille du
document n'est jamais bornée par la mémoire d'un processus.

Le vocabulaire est VOLONTAIREMENT court. Chaque bloc doit se rendre proprement
dans les trois formats, ou dire pourquoi il ne s'y rend pas. Une richesse que
seul le .docx saurait honorer produirait des documents muets en PDF, ce que
personne ne comprendrait à la lecture.
"""
from __future__ import annotations

FORMATS = ("docx", "pdf", "xlsx")

# Un bloc = un type + ses champs. Les champs absents prennent un défaut sûr.
# Mise en forme d'un paragraphe : vocabulaire FERMÉ, traduit par chaque rendu.
# Demander une taille en points ou un code couleur laisserait passer des valeurs
# invalides, et un rouge choisi au hasard peut être illisible à l'impression.
TAILLES = {"petit": 8, "normal": 11, "grand": 20, "tres_grand": 36}
# Le bleu est celui de la MARQUE, assombri pour rester lisible à l'impression
# (5,3 de contraste sur blanc) : un document sorti par l'assistant porte
# l'identité de l'entreprise.
#
# Les autres restent des couleurs de document, pas des couleurs de marque —
# quand on demande « en rouge », on attend un rouge de correction, pas le rouge
# vif du logo, qui fatigue sur un paragraphe entier. Et toujours pas de jaune :
# illisible sur blanc à toute taille.
COULEURS = {
    "rouge": "C0272D", "vert": "2F5233", "bleu": "0A6FB4",
    "orange": "C2610A", "gris": "6B6B6B", "noir": "000000",
}
def _couleur_de_marque(cle: str, repli: str) -> str:
    """Une couleur de la charte du client, en hexadécimal sans dièse.

    LA CHARTE EST UNE DONNÉE, PAS DU CODE. Elle vit déjà dans `emails/marque.py`
    — le seul fichier qui diverge entre les deux maisons — et sert les mails.
    Un document produit « aux couleurs de la maison » doit puiser à la même
    source, sinon les deux dériveront. Une valeur illisible retombe sur le
    repli : un document sans couleur vaut mieux qu'un document illisible.
    """
    try:
        from emails.marque import MARQUE
        brut = str(MARQUE.get(cle) or "").lstrip("#").strip().upper()
    except Exception:  # noqa: BLE001 — la marque ne doit jamais casser un rendu
        brut = ""
    return brut if len(brut) == 6 and all(c in "0123456789ABCDEF" for c in brut) else repli


# `charte` = la couleur d'accent de la maison (titres, mises en avant) ;
# `charte_fond` = le ton foncé de l'en-tête. Deux suffisent : au-delà, le
# modèle choisirait au hasard.
COULEURS["charte"] = _couleur_de_marque("couleur", COULEURS["noir"])
COULEURS["charte_fond"] = _couleur_de_marque("fond", COULEURS["noir"])

BLOCS = {
    "titre":       "texte, niveau (1 à 4), et au choix couleur "
                   "(charte|charte_fond|rouge|vert|bleu|orange|gris|noir) — "
                   "« charte » est la couleur de la maison",
    "paragraphe":  "texte, et au choix : gras, italique, centre (booléens), "
                   "taille (petit|normal|grand|tres_grand), "
                   "couleur (charte|charte_fond|rouge|vert|bleu|orange|gris|noir)",
    "liste":       "items[], ordonnee (bool)",
    "tableau":     "entetes[], lignes[[]], legende",
    "saut_page":   "(aucun champ)",
    "feuille":     "nom, entetes[], lignes[[]] (.xlsx : nouvel onglet ; "
                   "ailleurs : un tableau précédé de son nom)",
    "separateur":  "(aucun champ)",
    # 09/09 : « mettre une image du Drive ou une pièce jointe en pied de page
    # d'un Word ». La référence est celle qu'un geste a rendue (clé d'image
    # de la conversation, jeton, nom d'un fichier image du stockage) : le
    # skill la résout et range les octets sous le jeton du document.
    "image":       "image (référence : clé d'une image de la conversation, ou NOM "
                   "d'un fichier image du stockage), legende, largeur_cm (2 à 17), "
                   "centre (bool)",
}

# Les noms de champ sous lesquels le modèle écrit la référence d'une image.
CLES_IMAGE = ("image", "ref", "reference", "cle", "fichier", "source", "url", "nom", "photo")
# Une image DÉJÀ rangée à l'atelier : `<jeton>.img<n>.png|jpg`. C'est la seule
# forme que le rendu lit ; tout autre `fichier` est une référence à résoudre.
import re as _re
RE_IMAGE_RANGEE = _re.compile(r"^[A-Za-z0-9_-]{20,64}\.img\d+\.(?:png|jpg)$")
MAX_LARGEUR_CM = 17.0
MIN_LARGEUR_CM = 2.0

# Bornes. Un document sans limite finirait par épuiser le disque ou produire un
# fichier qu'aucun traitement de texte n'ouvre.
MAX_ELEMENTS = 20_000
MAX_LIGNES_TABLEAU = 5_000
MAX_COLONNES = 64
MAX_TEXTE = 20_000
MAX_FEUILLES = 50


def _texte(v, limite: int = MAX_TEXTE) -> str:
    return " ".join(str(v if v is not None else "").split())[:limite]


# LES SYNONYMES OBSERVÉS EN PRODUCTION, pas un dictionnaire imaginaire.
#
# L'export Langfuse du 14/08 montre le modèle envoyer {"type":"titre",
# "text":...}, {"type":"paragraphe","contenu":...} — jamais deux fois la même
# forme, et jamais la forme canonique {"bloc":...,"texte":...}. Chaque élément
# était écarté, « Aucun bloc n'a été retenu », et l'aller-retour de correction
# coûtait une minute de modèle pour reformuler EXACTEMENT le même contenu.
#
# Le vocabulaire canonique ne change pas : c'est lui qu'on documente et qu'on
# rend. Mais un synonyme évident — le mot anglais, le nom du champ voisin — ne
# détruit plus un versement entier. La philosophie « rien n'est deviné » tient
# toujours : un type réellement inconnu ou un contenu vide restent écartés ;
# on traduit ce qui est sans ambiguïté, on ne fabrique rien.
_TYPES = {
    "titre": "titre", "heading": "titre", "header": "titre", "title": "titre",
    "h1": "titre", "h2": "titre", "h3": "titre", "h4": "titre",
    "paragraphe": "paragraphe", "paragraph": "paragraphe", "p": "paragraphe",
    "texte": "paragraphe", "text": "paragraphe",
    "liste": "liste", "list": "liste", "ul": "liste", "ol": "liste",
    "puces": "liste", "bullet_list": "liste",
    "tableau": "tableau", "table": "tableau",
    "saut_page": "saut_page", "pagebreak": "saut_page", "page_break": "saut_page",
    "saut": "saut_page", "newpage": "saut_page",
    "feuille": "feuille", "sheet": "feuille", "onglet": "feuille",
    "separateur": "separateur", "separator": "separateur", "hr": "separateur",
    "ligne_horizontale": "separateur",
    "image": "image", "img": "image", "photo": "image", "picture": "image",
    "figure": "image", "illustration": "image", "visuel": "image",
}


def _champ_texte(brut: dict, limite: int = MAX_TEXTE) -> str:
    """Le texte d'un bloc, sous le nom que le modèle lui a donné ce jour-là."""
    for cle in ("texte", "text", "contenu", "content", "valeur", "value"):
        v = _texte(brut.get(cle), limite)
        if v:
            return v
    return ""


def normaliser_element(brut) -> dict | None:
    """Ramène un élément à sa forme sûre, ou None s'il est inexploitable.

    Rien n'est deviné : un bloc réellement inconnu ou vide est ÉCARTÉ. Le
    laisser passer produirait un trou silencieux dans le document, découvert
    par le lecteur final — c'est-à-dire au pire moment. Les synonymes de
    `_TYPES`, eux, sont TRADUITS : écarter {"type":"heading"} n'a jamais
    protégé personne, ça faisait juste rater le versement.
    """
    # Une chaîne nue est un paragraphe qui s'ignore : c'est la forme la plus
    # simple qu'un modèle puisse produire, il n'y a rien d'ambigu à traduire.
    if isinstance(brut, str):
        texte = _texte(brut)
        return {"bloc": "paragraphe", "texte": texte, "gras": False,
                "italique": False, "centre": False,
                "taille": "normal", "couleur": ""} if texte else None
    if not isinstance(brut, dict):
        return None
    demande = _texte(brut.get("bloc") or brut.get("type") or brut.get("kind"),
                     40).lower()
    bloc = _TYPES.get(demande)
    if bloc is None:
        return None
    # « h2 » dit le niveau en même temps que le type : on le garde de côté
    # avant de normaliser, pour que {"type":"h2","text":...} sorte en titre de
    # niveau 2 et non de niveau 1.
    niveau_implicite = int(demande[1]) if demande in ("h1", "h2", "h3", "h4") else None

    if bloc in ("saut_page", "separateur"):
        return {"bloc": bloc}

    if bloc == "image":
        # Une image RANGÉE garde son `fichier` ; sinon la référence est gardée
        # telle quelle (`ref`), à résoudre par `bureautique/images.preparer`
        # avant le versement. Une image sans rien n'est pas un bloc.
        fichier = str(brut.get("fichier") or "").strip()
        sortie = {"bloc": "image", "legende": _texte(brut.get("legende") or brut.get("caption"), 300),
                  "centre": brut.get("centre", brut.get("center")) is not False}
        try:
            largeur = float(brut.get("largeur_cm", brut.get("largeur", brut.get("width_cm", 12))))
        except (TypeError, ValueError):
            largeur = 12.0
        sortie["largeur_cm"] = round(min(max(largeur, MIN_LARGEUR_CM), MAX_LARGEUR_CM), 1)
        if RE_IMAGE_RANGEE.match(fichier):
            sortie["fichier"] = fichier
            return sortie
        ref = ""
        for cle in CLES_IMAGE:
            v = brut.get(cle)
            if isinstance(v, str) and v.strip():
                ref = v.strip()[:500]
                break
        if not ref:
            return None
        sortie["ref"] = ref
        return sortie

    if bloc == "titre":
        texte = _champ_texte(brut, 500)
        if not texte:
            return None
        niveau = brut.get("niveau", brut.get("level", niveau_implicite))
        niveau = niveau if isinstance(niveau, int) and 1 <= niveau <= 4 else 1
        # UNE CHARTE SE VOIT DANS LES TITRES. Le champ est facultatif et le
        # vocabulaire reste FERMÉ : un titre sans couleur rend exactement comme
        # avant (le style Word d'origine).
        couleur = _texte(brut.get("couleur"), 12).lower()
        return {"bloc": "titre", "texte": texte, "niveau": niveau,
                "couleur": couleur if couleur in COULEURS else ""}

    if bloc == "paragraphe":
        texte = _champ_texte(brut)
        if not texte:
            return None
        # Mise en forme facultative, en vocabulaire FERMÉ. On demande « grand »
        # et « rouge », pas une taille en points ni un code hexadécimal : le
        # modèle produirait des valeurs invalides ou des couleurs illisibles, et
        # chaque format les exprime différemment. Ici, l'intention est bornée et
        # chaque rendu la traduit comme il sait le faire.
        taille = _texte(brut.get("taille"), 12).lower()
        couleur = _texte(brut.get("couleur"), 12).lower()
        return {"bloc": "paragraphe", "texte": texte,
                "gras": bool(brut.get("gras")),
                "italique": bool(brut.get("italique")),
                "centre": bool(brut.get("centre")),
                "taille": taille if taille in TAILLES else "normal",
                "couleur": couleur if couleur in COULEURS else ""}

    if bloc == "liste":
        source = (brut.get("items") or brut.get("elements")
                  or brut.get("points") or [])
        items = [_texte(i, 2000) for i in source]
        items = [i for i in items if i][:1000]
        # « ol » dit l'ordre en même temps que le type, comme « h2 » le niveau.
        ordonnee = bool(brut.get("ordonnee", brut.get("ordered"))) or demande == "ol"
        return {"bloc": "liste", "items": items,
                "ordonnee": ordonnee} if items else None

    if bloc in ("tableau", "feuille"):
        entetes = [_texte(e, 200) for e in
                   (brut.get("entetes") or brut.get("headers")
                    or brut.get("colonnes") or brut.get("columns")
                    or [])][:MAX_COLONNES]
        lignes = []
        for ligne in (brut.get("lignes") or brut.get("rows")
                      or [])[:MAX_LIGNES_TABLEAU]:
            if isinstance(ligne, dict):     # {colonne: valeur} accepté aussi
                ligne = [ligne.get(e, "") for e in entetes]
            if not isinstance(ligne, (list, tuple)):
                continue
            lignes.append([_texte(c, 2000) for c in ligne][:MAX_COLONNES])
        if not entetes and not lignes:
            return None
        sortie = {"bloc": bloc, "entetes": entetes, "lignes": lignes}
        if bloc == "tableau":
            sortie["legende"] = _texte(brut.get("legende"), 300)
        else:
            sortie["nom"] = _texte(brut.get("nom"), 31) or "Feuille"
        return sortie

    return None


def normaliser_entete(brut: dict) -> dict:
    """En-tête, pied de page et identité du document."""
    fmt = _texte(brut.get("format") or brut.get("type"), 8).lower()
    return {
        "format": fmt if fmt in FORMATS else "docx",
        "titre": _texte(brut.get("titre"), 300) or "Document",
        "sous_titre": _texte(brut.get("sous_titre"), 300),
        "entete": _texte(brut.get("entete"), 200),
        "pied": _texte(brut.get("pied"), 200),
        # Une image (un logo) sur CHAQUE page, en en-tête ou en pied : la
        # référence est résolue et rangée par le skill (`_fichier`), le rendu
        # ne lit que le fichier rangé.
        "entete_image": _texte(brut.get("entete_image") or brut.get("logo_entete")
                               or brut.get("image_entete") or brut.get("logo"), 500),
        "pied_image": _texte(brut.get("pied_image") or brut.get("logo_pied")
                             or brut.get("image_pied"), 500),
        "entete_image_fichier": (str(brut.get("entete_image_fichier") or "")
                                 if RE_IMAGE_RANGEE.match(str(brut.get("entete_image_fichier") or "")) else ""),
        "pied_image_fichier": (str(brut.get("pied_image_fichier") or "")
                               if RE_IMAGE_RANGEE.match(str(brut.get("pied_image_fichier") or "")) else ""),
        # La numérotation est produite par le rendu, jamais écrite par le
        # modèle : lui demander « page 3 sur 47 » supposerait qu'il sache
        # combien de pages sortiront, ce qu'il ne peut pas savoir.
        "numeroter": brut.get("numeroter") is not False,
        "paysage": bool(brut.get("paysage")),
    }
