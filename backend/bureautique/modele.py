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
# LE SURLIGNAGE D'UNE LIGNE DE CLASSEUR (17/09) : « mets les trois priorités en premier et
# surligne-les en orange ». Des fonds CLAIRS (le texte reste lisible), vocabulaire fermé.
SURLIGNAGES = {"orange": "FCE4C4", "jaune": "FFF3B0", "vert": "DDEFD9", "rouge": "F8D4D4",
               "bleu": "D9E5F5", "gris": "E8E8E8"}
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
    # 15/09 (Noa : « il fait tout le temps la même trame de documents, c'est
    # horrible »). Des blocs qui changent la PAGE, pas seulement le texte.
    "encadre":     "texte, titre (facultatif), ton (charte|info|attention) — un "
                   "encadré coloré pour ce qui doit sauter aux yeux",
    "citation":    "texte, auteur (facultatif) — un témoignage, un engagement",
    "chiffres":    "items[{valeur, libelle}] (2 à 4) — les chiffres clés en grand, côte à côte",
    "colonnes":    "texte + image (référence, comme le bloc image), image_a_gauche "
                   "(bool), titre (facultatif) — une photo À CÔTÉ de son texte",
}

# LE STYLE D'UN DOCUMENT (15/09) : la même charte, quatre allures. Le modèle le
# choisit selon le document ; absent = « classique ».
STYLES = {
    "classique": "page de garde sobre, titres à la couleur de la maison — rapports, "
                 "mémoires, cahiers des charges",
    "moderne":   "bandeau de couleur en couverture, titres soulignés d'un filet, "
                 "en-tête avec logo — offres, présentations de projet",
    "epure":     "sans page de garde, beaucoup de blanc, titres gris foncé — courriers, "
                 "notes, comptes rendus",
    "plaquette": "grande image de couverture, titre en grand, photos mises en valeur — "
                 "plaquettes, dossiers de présentation, références chantier",
}
TONS = ("charte", "info", "attention")

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


def _texte_lignes(v, limite: int = MAX_TEXTE) -> str:
    """Comme `_texte`, mais les RETOURS À LA LIGNE restent (15/09) : un paragraphe
    écrit « Pièces à fournir :\n- DC1\n- Kbis » doit devenir une liste au rendu,
    pas une ligne « - DC1 - Kbis »."""
    lignes = [" ".join(l.split()) for l in str(v if v is not None else "").splitlines()]
    return "\n".join(l for l in lignes if l)[:limite]


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
    "encadre": "encadre", "encadré": "encadre", "callout": "encadre", "note": "encadre",
    "alerte": "encadre", "box": "encadre",
    "citation": "citation", "quote": "citation", "temoignage": "citation", "témoignage": "citation",
    "chiffres": "chiffres", "chiffres_cles": "chiffres", "kpi": "chiffres", "stats": "chiffres",
    "colonnes": "colonnes", "deux_colonnes": "colonnes", "texte_image": "colonnes",
    "image_texte": "colonnes", "columns": "colonnes",
}


def _champ_texte(brut: dict, limite: int = MAX_TEXTE, lignes: bool = False) -> str:
    """Le texte d'un bloc, sous le nom que le modèle lui a donné ce jour-là."""
    for cle in ("texte", "text", "contenu", "content", "valeur", "value"):
        v = (_texte_lignes if lignes else _texte)(brut.get(cle), limite)
        if v:
            return v
    return ""


_CLES_CONTENU_IMBRIQUE = ("contenu", "blocs", "elements", "content", "children")


def _est_feuille(brut: dict) -> bool:
    return _TYPES.get(_texte(brut.get("bloc") or brut.get("type") or brut.get("kind"), 40).lower()) == "feuille"


def _a_des_lignes(brut: dict) -> bool:
    return bool(brut.get("lignes") or brut.get("rows") or brut.get("entetes") or brut.get("headers"))


def deplier_feuilles(elements) -> list:
    """Une « feuille » qui PORTE ses blocs devient une feuille suivie de ses blocs.

    17/09, trace du fil d13ff0ac : « un Excel à deux feuilles ». Le modèle a écrit,
    quatre fois de suite et sous quatre variantes,
    {"type":"feuille","nom":"Achats BTF 2026","contenu":[{titre},{tableau},{chiffres}]}
    — la forme la plus naturelle qui soit. Or une feuille est PLATE ici (nom,
    entetes, lignes) : sans entêtes ni lignes à son niveau, elle était écartée, avec
    tout ce qu'elle contenait, et le tour répondait « aucun bloc n'a été retenu ».
    Dix minutes perdues, le mode d'emploi relu, l'Excel jamais sorti.

    Rien n'est inventé : le PREMIER tableau imbriqué donne à la feuille ses entêtes
    et ses lignes ; les autres blocs suivent dans le même onglet, dans leur ordre
    (le rendu écrit dans l'onglet courant). Un titre placé AVANT ce tableau est
    omis : l'onglet porte déjà son nom, et un titre sous le tableau n'aurait pas de
    sens. Une feuille déjà plate, ou tout autre bloc, passe tel quel.
    """
    sortie = []
    elements = list(elements or [])
    # LA FEUILLE-SÉPARATEUR (17/09, 15:45) : {"bloc":"feuille","titre":"Mails reçus"} puis,
    # à côté, {"bloc":"tableau",…}. Sans entêtes ni lignes la feuille était écartée, et
    # les deux tableaux tombaient dans le même onglet (« ignores=2 »). Une feuille NUE
    # suivie d'un tableau prend ce tableau : c'est ce que la personne a demandé.
    fusionnes, saute = [], False
    for i, brut in enumerate(elements):
        if saute:
            saute = False
            continue
        if (isinstance(brut, dict) and _est_feuille(brut) and not _a_des_lignes(brut)
                and not any(isinstance(brut.get(c), list) and brut.get(c) for c in _CLES_CONTENU_IMBRIQUE)
                and i + 1 < len(elements) and isinstance(elements[i + 1], dict)
                and _TYPES.get(_texte(elements[i + 1].get("bloc") or elements[i + 1].get("type")
                                      or elements[i + 1].get("kind"), 40).lower()) == "tableau"):
            suivant = elements[i + 1]
            fusionnes.append({**{k: v for k, v in suivant.items() if k not in ("bloc", "type", "kind", "legende")},
                              "type": "feuille",
                              "nom": brut.get("nom") or brut.get("name") or brut.get("titre") or brut.get("title")
                                     or suivant.get("titre") or suivant.get("legende")})
            saute = True
        else:
            fusionnes.append(brut)
    for brut in fusionnes:
        imbriques = None
        if isinstance(brut, dict) and _TYPES.get(
                _texte(brut.get("bloc") or brut.get("type") or brut.get("kind"), 40).lower()) == "feuille":
            if not (brut.get("lignes") or brut.get("rows") or brut.get("entetes") or brut.get("headers")):
                imbriques = next((brut[c] for c in _CLES_CONTENU_IMBRIQUE
                                  if isinstance(brut.get(c), list) and brut.get(c)), None)
        if imbriques is None:
            sortie.append(brut)
            continue

        def _est_tableau(x):
            return isinstance(x, dict) and (
                _TYPES.get(_texte(x.get("bloc") or x.get("type") or x.get("kind"), 40).lower())
                in ("tableau", "feuille") or x.get("lignes") or x.get("rows"))
        rang = next((i for i, x in enumerate(imbriques) if _est_tableau(x)), None)
        nom = brut.get("nom") or brut.get("name") or brut.get("titre") or brut.get("title")
        if rang is None:
            sortie.extend(imbriques)      # pas de tableau : ses blocs, sans onglet vide
            continue
        tableau = imbriques[rang]
        sortie.append({**{k: v for k, v in tableau.items() if k not in ("bloc", "type", "kind", "legende")},
                       "type": "feuille", "nom": nom or tableau.get("nom") or tableau.get("legende")})
        for i, x in enumerate(imbriques):
            if i == rang:
                continue
            est_titre = isinstance(x, dict) and _TYPES.get(
                _texte(x.get("bloc") or x.get("type") or x.get("kind"), 40).lower()) == "titre"
            if i < rang and est_titre:
                continue
            sortie.append(x)
    return sortie


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

    if bloc == "encadre":
        texte = _champ_texte(brut, lignes=True)
        if not texte:
            return None
        ton = _texte(brut.get("ton") or brut.get("tone"), 12).lower()
        return {"bloc": "encadre", "texte": texte, "titre": _texte(brut.get("titre") or brut.get("title"), 200),
                "ton": ton if ton in TONS else "charte"}

    if bloc == "citation":
        texte = _champ_texte(brut, 2000)
        return {"bloc": "citation", "texte": texte,
                "auteur": _texte(brut.get("auteur") or brut.get("author"), 200)} if texte else None

    if bloc == "chiffres":
        items = []
        # 17/09 : {"type":"chiffres","valeur":"4 661,10 €","libelle":"Total HT"} — un
        # seul chiffre, écrit à plat. Écarté jusqu'ici : le total disparaissait du classeur.
        aplat = ([{"valeur": brut.get("valeur") or brut.get("value"),
                   "libelle": brut.get("libelle") or brut.get("label")}]
                 if (brut.get("valeur") or brut.get("value")) else [])
        for i in (brut.get("items") or brut.get("chiffres") or aplat)[:4]:
            if isinstance(i, dict):
                v, l = _texte(i.get("valeur") or i.get("value"), 30), _texte(i.get("libelle") or i.get("label"), 80)
            elif isinstance(i, (list, tuple)) and len(i) >= 2:
                v, l = _texte(i[0], 30), _texte(i[1], 80)
            else:
                continue
            if v:
                items.append({"valeur": v, "libelle": l})
        return {"bloc": "chiffres", "items": items} if items else None

    if bloc == "colonnes":
        texte = _champ_texte(brut, lignes=True)
        fichier = str(brut.get("fichier") or "").strip()
        sortie = {"bloc": "colonnes", "texte": texte, "titre": _texte(brut.get("titre"), 200),
                  "image_a_gauche": bool(brut.get("image_a_gauche", brut.get("image_gauche")))}
        if RE_IMAGE_RANGEE.match(fichier):
            sortie["fichier"] = fichier
        else:
            ref = next((v.strip()[:500] for c in ("image", "photo", "ref", "cle", "nom")
                        if isinstance((v := brut.get(c)), str) and v.strip()), "")
            if ref:
                sortie["ref"] = ref
        return sortie if (texte or sortie.get("fichier") or sortie.get("ref")) else None

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
        texte = _champ_texte(brut, lignes=True)
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
            # Des lignes mises en avant : leurs RANGS (0 = première ligne de données).
            rangs = brut.get("surlignees") or brut.get("lignes_surlignees") or []
            if isinstance(rangs, list):
                rangs = sorted({i for i in rangs if type(i) is int and 0 <= i < len(lignes)})
                if rangs:
                    teinte = _texte(brut.get("surlignage") or brut.get("couleur_surlignage"), 12).lower()
                    sortie["surlignees"] = rangs
                    sortie["surlignage"] = teinte if teinte in SURLIGNAGES else "orange"
            if brut.get("total") is True or str(brut.get("total") or "").strip().lower() in ("true", "oui", "vrai", "1"):
                sortie["total"] = True
            colonnes=brut.get("colonnes_numeriques") or []
            if colonnes:
                import math
                if not isinstance(colonnes,list) or any(type(i) is not int or i<0 or i>=MAX_COLONNES for i in colonnes):raise ValueError("Colonnes numériques invalides.")
                for ligne in lignes:
                    for i in colonnes:
                        if i<len(ligne) and ligne[i]!="":
                            valeur=float(ligne[i].replace(",","."))
                            if not math.isfinite(valeur):raise ValueError("Quantité non finie.")
                            ligne[i]=valeur
                sortie["colonnes_numeriques"]=colonnes
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
        # (15/09) L'allure du document et son image de couverture.
        "style": (lambda v: v if v in STYLES else "classique")(
            _texte(brut.get("style") or brut.get("theme") or brut.get("gabarit"), 20).lower()
            .replace("é", "e")),
        "image_couverture": _texte(brut.get("image_couverture") or brut.get("couverture")
                                   or brut.get("photo_couverture"), 500),
        "image_couverture_fichier": (str(brut.get("image_couverture_fichier") or "")
                                     if RE_IMAGE_RANGEE.match(str(brut.get("image_couverture_fichier") or "")) else ""),
        "paysage": bool(brut.get("paysage")),
        # (15/09) Word : page de garde et sommaire. Absents = décidés par le rendu
        # (un document long les reçoit) ; `false` les retire.
        "page_de_garde": None if brut.get("page_de_garde") is None else bool(brut.get("page_de_garde")),
        "sommaire": None if brut.get("sommaire") is None else bool(brut.get("sommaire")),
    }
