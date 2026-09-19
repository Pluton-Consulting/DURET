"""
CE QU'UNE NAVIGATION EN LECTURE A LE DROIT DE TOUCHER (19/09).

La lecture seule retirait TOUTE interaction : ni clic, ni saisie. L'agent ne
pouvait donc ni ouvrir un menu, ni suivre un lien, ni fermer une bannière de
cookies, ni taper dans le moteur de recherche d'un site — il devinait des
adresses (« /produits/taralay », page introuvable) puis partait chercher sur
Google, que les domaines autorisés bloquent. Relevé en production le 19/09 :
douze étapes sur gerflor.fr, zéro page utile, « rapport d'impossibilité ».

Lire un site, c'est cliquer. Ce qui sort d'une lecture, c'est ENVOYER : un
formulaire posté, une commande, une inscription, une suppression. La frontière
passe donc là, et elle se juge sur l'élément visé, au moment du clic :

  * un clic est permis, sauf sur un bouton qui poste un formulaire (méthode
    autre que GET) ou dont le libellé engage (panier, commander, payer,
    supprimer, s'inscrire, envoyer…) ;
  * une saisie n'est permise que dans un champ de RECHERCHE — jamais un mot de
    passe, une adresse, un téléphone, ni un champ ordinaire de formulaire ;
  * une touche n'est permise que si elle navigue (Entrée, Échap, flèches…) ;
  * un clic par coordonnées est refusé : on ne sait pas ce qu'il vise ;
  * un dépôt de fichier, jamais.

Module PUR (aucun import de browser-use) : il reçoit un nœud qui porte
`tag_name`, `attributes`, `parent_node` et, s'il existe,
`get_all_children_text()`. C'est ce qui le rend éprouvable au banc.
"""
from __future__ import annotations

import re
import unicodedata

# Libellés qui ENGAGENT : un clic dessus fait quelque chose chez le site.
# Ce n'est pas un jugement d'intention de la personne — c'est un verrou de
# sécurité, et un verrou se veut mécanique et fermé.
_ENGAGE = re.compile(
    r"\b(panier|commander|commande|acheter|achat|payer|paiement|reglement|"
    r"supprimer|suppression|effacer|resilier|desabonner|desinscri\w*|"
    r"s ?inscrire|inscription|creer (?:un|mon) compte|souscrire|"
    r"envoyer|envoi|soumettre|publier|poster|reserver|reservation|"
    r"add to (?:cart|basket|bag)|cart|checkout|buy|purchase|pay|order|"
    r"delete|remove|unsubscribe|subscribe|sign ?up|register|send|submit|book now)\b")

# Un champ où l'on tape pour CHERCHER.
_RECHERCHE = re.compile(r"search|recherch|chercher|query|keyword|mots? cles?|trouver")
_NOMS_RECHERCHE = {"q", "s", "k", "kw", "query", "term", "terms", "search", "recherche", "motcle", "mot"}
_TYPES_TEXTE = {"", "text", "search"}

# Touches qui déplacent ou valident une recherche, jamais du texte.
_TOUCHES = {"enter", "return", "escape", "esc", "tab", "shift+tab", "arrowdown", "arrowup",
            "arrowleft", "arrowright", "pagedown", "pageup", "home", "end", "space", " "}


def _plat(texte: str) -> str:
    t = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _balise(noeud) -> str:
    return str(getattr(noeud, "tag_name", "") or getattr(noeud, "node_name", "") or "").lower()


def _attr(noeud) -> dict:
    return getattr(noeud, "attributes", None) or {}


def _texte(noeud) -> str:
    try:
        return re.sub(r"\s+", " ", noeud.get_all_children_text() or "").strip()
    except Exception:  # noqa: BLE001 — un nœud sans enfants lisibles garde ses attributs
        return ""


def _libelle(noeud, texte: str | None = None) -> str:
    """Ce que la PERSONNE lit sur l'élément. Ni `id` ni `name` : ce sont des noms techniques
    (le bouton de recherche de Gerflor s'appelle `edit-submit` — le lire comme « submit »
    l'a fait refuser le 19/09 alors qu'il ne fait que chercher)."""
    a = _attr(noeud)
    morceaux = [a.get(k, "") for k in ("aria-label", "title", "value", "alt")]
    morceaux.append((_texte(noeud) if texte is None else texte)[:200])
    return _plat(" ".join(m for m in morceaux if m))


# Une adresse de lien qui agit au lieu de montrer (paniers en GET, déconnexion…).
# Jugée sur l'adresse APLATIE (« add-to-cart » → « add to cart »), mot par mot : un tri
# « ?orderby=prix » n'est pas une commande.
_LIEN_ENGAGE = re.compile(r"\b(add to cart|panier|basket|checkout|commande|order|delete|supprim\w*|"
                          r"logout|log out|deconnexion|unsubscribe|desinscri\w*|desabonn\w*)\b")


def _formulaire(noeud):
    """Le <form> qui contient le nœud, s'il y en a un (30 niveaux au plus)."""
    n, pas = getattr(noeud, "parent_node", None), 0
    while n is not None and pas < 30:
        if _balise(n) == "form":
            return n
        n, pas = getattr(n, "parent_node", None), pas + 1
    return None


def _envoie_un_formulaire(noeud) -> bool:
    """Vrai si ce clic POSTE un formulaire (un formulaire en GET ne fait que lire)."""
    balise, a = _balise(noeud), _attr(noeud)
    type_ = str(a.get("type", "")).lower()
    form = _formulaire(noeud)
    if balise == "input" and type_ in ("submit", "image"):
        pass
    elif balise == "button" and type_ in ("", "submit") and form is not None:
        pass
    else:
        return False
    if form is None:
        return False
    methode = str(_attr(form).get("method", "get")).lower()
    return methode not in ("", "get", "dialog")


def champ_de_recherche(noeud) -> bool:
    balise, a = _balise(noeud), _attr(noeud)
    type_ = str(a.get("type", "")).lower()
    if balise == "input" and type_ == "search":
        return True
    if balise not in ("input", "textarea") and str(a.get("contenteditable", "")).lower() != "true":
        return False
    if balise == "input" and type_ not in _TYPES_TEXTE:
        return False                     # mot de passe, adresse, téléphone, nombre…
    if str(a.get("role", "")).lower() in ("searchbox", "combobox"):
        return True
    if str(a.get("name", "")).lower() in _NOMS_RECHERCHE or str(a.get("id", "")).lower() in _NOMS_RECHERCHE:
        return True
    indices = " ".join(str(a.get(k, "")) for k in ("name", "id", "placeholder", "aria-label", "class", "title"))
    if _RECHERCHE.search(_plat(indices)):
        return True
    form = _formulaire(noeud)
    if form is not None:
        fa = _attr(form)
        if str(fa.get("role", "")).lower() == "search" or _RECHERCHE.search(
                _plat(" ".join(str(fa.get(k, "")) for k in ("action", "id", "class", "name")))):
            return True
    return False


def interaction_permise(action: str, params: dict, noeud=None) -> tuple[bool, str]:
    """(permis, raison). `noeud` = l'élément visé par l'index, quand il y en a un."""
    params = params or {}
    if action in ("upload_file",):
        return False, "Déposer un fichier n'est pas permis pendant une lecture."
    if action in ("send_keys",):
        brut = str(params.get("keys", ""))
        cle = " " if brut == " " else brut.strip().lower().replace(" ", "")
        if cle in _TOUCHES:
            return True, ""
        return False, "Seules les touches de navigation (Entrée, Échap, flèches) sont permises pendant une lecture."
    if params.get("index") is None:
        return False, "Un clic sans élément désigné ne peut pas être vérifié : désigne l'élément par son index."
    if noeud is None:
        return False, "Cet élément n'est plus sur la page : relis la page avant d'agir."
    if action in ("input", "input_text"):
        if champ_de_recherche(noeud):
            return True, ""
        return False, ("Pendant une lecture, on n'écrit que dans un champ de RECHERCHE ; "
                       "ce champ-là appartient à un formulaire. Passe par les menus ou la recherche du site.")
    if action in ("click", "click_element_by_index", "select_dropdown", "select_dropdown_option"):
        if _envoie_un_formulaire(noeud):
            return False, "Ce bouton envoie un formulaire au site : refusé pendant une lecture."
        href = str(_attr(noeud).get("href", "") or "")
        if _balise(noeud) == "a" and href and not href.lower().startswith(("javascript:", "#")):
            # UN LIEN MONTRE. On juge son ADRESSE, et son libellé seulement s'il est
            # court : une carte produit entière (« disponible à la commande… ») est
            # un lien vers sa fiche, pas un bouton qui commande.
            texte = _texte(noeud)
            if _LIEN_ENGAGE.search(_plat(href)) or (len(texte) <= 60 and _ENGAGE.search(_libelle(noeud, texte))):
                return False, ("Ce lien agit chez le site (panier, commande, suppression, déconnexion) : "
                               "refusé pendant une lecture. Continue par un autre chemin.")
            return True, ""
        if _ENGAGE.search(_libelle(noeud)):
            return False, ("Ce bouton engage quelque chose chez le site (commande, envoi, inscription, "
                           "suppression) : refusé pendant une lecture. Continue par un autre chemin.")
        return True, ""
    return False, "Cette action n'est pas permise pendant une lecture."


def domaines_de_lecture(domaines: list[str]) -> list[str]:
    """« https://www.gerflor.fr/produits » → gerflor.fr et ses sous-domaines.

    En LECTURE aucun identifiant n'est injecté : ouvrir les sous-domaines du site
    nommé (www., cdn., media.) ne peut rien exposer, et c'est là que vivent ses
    fiches techniques. En écriture, les hôtes restent exacts (identifiants).
    """
    sortie: list[str] = []
    for d in domaines or []:
        hote = re.sub(r"^[a-z]+://", "", str(d or "").strip().lower()).split("/")[0].split(":")[0]
        hote = hote.lstrip("*.").removeprefix("www.")
        if not hote or "." not in hote:
            continue
        for motif in (hote, "*." + hote):
            if motif not in sortie:
                sortie.append(motif)
    return sortie


def hote_autorise(url: str, domaines: list[str]) -> bool:
    """Même règle que ci-dessus, pour filtrer des résultats de recherche."""
    hote = re.sub(r"^[a-z]+://", "", str(url or "").lower()).split("/")[0].split(":")[0]
    for d in domaines or []:
        base = d.removeprefix("*.")
        if hote == base or hote.endswith("." + base):
            return True
    return False


def agent_utilisateur(version_chromium: str) -> str:
    """L'identité d'un Chrome ordinaire, à la version réelle du Chromium de l'image.

    « HeadlessChrome » dans l'identité suffit à Akamai pour répondre « Access
    Denied » (gerflor.fr, mesuré le 19/09 : refusé en l'état, servi avec un
    Chrome ordinaire). La version majeure suit le binaire, pour rester
    cohérente avec ce que le moteur sait faire.
    """
    m = re.search(r"(\d{2,3})\.\d+\.\d+", str(version_chromium or ""))
    majeure = m.group(1) if m else "140"
    return (f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{majeure}.0.0.0 Safari/537.36")


def consigne_de_navigation(domaines: list[str], lecture: bool) -> str:
    """Ce que l'agent doit savoir de SA situation, en plus des règles de browser-use."""
    lignes = [
        "RÈGLES DE CETTE NAVIGATION :",
        "- Pour trouver une information sur un site, explore-le comme une personne : menus, liens, "
        "onglets, pages de gamme ou de catégorie, moteur de recherche du site. N'invente pas "
        "d'adresse : une adresse devinée mène souvent à « page introuvable » — dans ce cas reviens "
        "en arrière et passe par la navigation du site.",
        "- L'action `search` cherche sur le web et rend des adresses avec un extrait de leur contenu ; "
        "ouvre ensuite la bonne adresse avec `navigate`. N'ouvre jamais un moteur de recherche à la main.",
        "- Une bannière de cookies : ferme-la (accepter ou refuser) pour lire la page.",
        "- Une page refusée (Access Denied, captcha) : ne la recharge pas plus de deux fois ; essaie une "
        "autre page du même site ou l'action `search`.",
        "- Quand on te demande TOUTE une gamme, une liste ou un catalogue : trouve la page qui les liste TOUS "
        "(le moteur de recherche du site avec le nom, une catégorie filtrée) — une page de « collection » ou "
        "de présentation n'en montre souvent qu'une partie. Parcours toutes ses pages si elle est paginée, "
        "relève le nombre de résultats que le site annonce, et dis dans `done` combien tu en as relevés sur "
        "combien. Ne conclus jamais « c'est tout » sans ce décompte.",
        "- Si la tâche demande le détail de NOMBREUSES pages (toute une gamme, une liste de fiches), ne les "
        "ouvre pas une à une : relève leurs adresses (extract avec extract_links) et rends-les TOUTES dans "
        "`done`, une par ligne — elles seront lues en parallèle ensuite, bien plus vite.",
        "- Termine par `done` avec les faits trouvés, chacun suivi de l'adresse de la page où tu l'as lu. "
        "Si tu n'as pas trouvé, dis précisément ce que tu as essayé et ce que tu as vu.",
    ]
    if lecture:
        lignes.insert(3, "- Tu es en LECTURE : tu peux cliquer sur des liens, des menus, des onglets et des "
                         "boutons d'affichage, et écrire dans un champ de RECHERCHE. Un clic qui enverrait, "
                         "commanderait, inscrirait ou supprimerait est refusé : n'insiste pas.")
    if domaines:
        noms = ", ".join(d for d in domaines if not d.startswith("*."))
        lignes.append(f"- Sites autorisés : {noms} (sous-domaines compris). Toute autre adresse est "
                      "bloquée : ne tente pas d'en sortir.")
    return "\n".join(lignes)
