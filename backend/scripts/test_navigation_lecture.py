"""
LA NAVIGATION AUTONOME LIT UN SITE COMME UNE PERSONNE, SANS RIEN ENVOYER (19/09, banc Duret).

Relevé en production (« Va sur le site de Gerflor, trouve la gamme Taralay… ») : douze
étapes, zéro page utile. Trois causes, toutes prouvées :
  1. le Chromium de l'agent s'annonçait « HeadlessChrome » → Akamai : « Access Denied »
     (la même page s'ouvre avec l'identité d'un Chrome ordinaire) ;
  2. la lecture seule retirait TOUT clic : ni menu, ni lien, ni bannière, ni recherche du
     site — l'agent devinait des adresses (page introuvable) ;
  3. l'action `search` de browser-use ouvrait Google/DuckDuckGo dans l'onglet de l'agent :
     hors des domaines autorisés, « blocked by security policy ».

Ce banc charge `browser-worker/lecture_sure.py` tel quel (module pur) et vérifie, sur des
éléments doublés, ce que la lecture laisse faire et ce qu'elle refuse ; puis il lit le
câblage de `browser_agent.py` (identité, recherche servie par le conteneur, aucun
identifiant en lecture).
"""
import ast
import importlib.util
import sys
from pathlib import Path

RACINE = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve().parent
TRAVAILLEUR = RACINE / "browser-worker"
echecs = []


def verifier(nom, cond, detail=""):
    print(("  ✓ " if cond else "  ✗ ") + nom + ("" if cond else f"  → {detail}"))
    if not cond:
        echecs.append(nom)


spec = importlib.util.spec_from_file_location("lecture_sure_banc", TRAVAILLEUR / "lecture_sure.py")
ls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ls)


class Noeud:
    def __init__(self, tag, attrs=None, texte="", parent=None):
        self.tag_name, self.attributes, self._texte, self.parent_node = tag, attrs or {}, texte, parent

    def get_all_children_text(self):
        return self._texte


def permis(action, noeud, **params):
    params.setdefault("index", 7)
    return ls.interaction_permise(action, params, noeud)[0]


print("═══ LECTURE SÛRE — " + str(TRAVAILLEUR / "lecture_sure.py"))
page = Noeud("body")
nav = Noeud("nav", parent=page)
form_post = Noeud("form", {"method": "post", "action": "/contact"}, parent=page)
form_get = Noeud("form", {"action": "/recherche", "role": "search"}, parent=page)
form_sans = Noeud("form", {"id": "newsletter"}, parent=page)

# ── Ce qu'on lit : liens, menus, bannières, onglets ──
verifier("un lien de menu se clique",
         permis("click", Noeud("a", {"href": "/fr/produits/sols-pvc"}, "Sols PVC", nav)))
verifier("une carte produit (lien long qui parle de commande) se clique : c'est sa fiche",
         permis("click", Noeud("a", {"href": "/fr/taralay-impression-compact"},
                               "Taralay Impression Compact — sol PVC hétérogène, disponible à la commande "
                               "en rouleaux de 2 m, classement U4P3", nav)))
verifier("« Tout accepter » d'une bannière de cookies se clique",
         permis("click", Noeud("button", {"type": "button", "id": "onetrust-accept-btn-handler"}, "Tout accepter", page)))
verifier("« Valider mes choix » (cookies, hors formulaire posté) se clique",
         permis("click", Noeud("button", {}, "Valider mes choix", page)))
verifier("un bouton d'onglet / « voir plus » se clique",
         permis("click", Noeud("div", {"role": "button"}, "Voir plus de produits", page)))
verifier("le bouton d'un formulaire de recherche en GET se clique",
         permis("click", Noeud("button", {"type": "submit"}, "Rechercher", form_get)))
verifier("un lien de tri « ?orderby=prix » n'est pas une commande",
         permis("click", Noeud("a", {"href": "/produits?orderby=prix"}, "Prix croissant", nav)))
verifier("un choix dans une liste de filtres se fait",
         permis("select_dropdown", Noeud("select", {"name": "usage"}, "Tous les usages", page), text="Logement"))

# ── Ce qui envoie : refusé ──
verifier("le bouton d'un formulaire POSTÉ est refusé",
         not permis("click", Noeud("button", {"type": "submit"}, "Valider", form_post)))
verifier("un <input type=submit> posté est refusé",
         not permis("click", Noeud("input", {"type": "submit", "value": "OK"}, "", form_post)))
verifier("« Ajouter au panier » est refusé",
         not permis("click", Noeud("button", {"type": "button"}, "Ajouter au panier", page)))
verifier("« Commander un échantillon » est refusé",
         not permis("click", Noeud("button", {}, "Commander un échantillon", page)))
verifier("un lien « add-to-cart » en GET est refusé (le panier se remplit par l'adresse)",
         not permis("click", Noeud("a", {"href": "/boutique?add-to-cart=123"}, "Taralay", nav)))
verifier("un lien de déconnexion est refusé",
         not permis("click", Noeud("a", {"href": "/logout"}, "Mon compte", nav)))
verifier("« S'inscrire » (newsletter) est refusé",
         not permis("click", Noeud("button", {}, "S'inscrire", form_sans)))
verifier("un clic par coordonnées (sans index) est refusé : on ne sait pas ce qu'il vise",
         not ls.interaction_permise("click", {"coordinate_x": 10, "coordinate_y": 20}, None)[0])
verifier("un élément disparu est refusé (relire la page)",
         not ls.interaction_permise("click", {"index": 3}, None)[0])
verifier("déposer un fichier est refusé", not permis("upload_file", Noeud("input", {"type": "file"}, "", form_post)))

# ── Saisie : seulement dans un champ de recherche ──
verifier("écrire dans le moteur de recherche du site (type=search)",
         permis("input", Noeud("input", {"type": "search", "name": "keywords"}, "", form_get), text="Taralay"))
verifier("écrire dans un champ « q » d'un formulaire de recherche",
         permis("input", Noeud("input", {"type": "text", "name": "q"}, "", form_get), text="Taralay"))
verifier("écrire dans un champ au placeholder « Rechercher un produit »",
         permis("input", Noeud("input", {"placeholder": "Rechercher un produit"}, "", page), text="Taralay"))
verifier("écrire une adresse mail (newsletter) est refusé",
         not permis("input", Noeud("input", {"type": "email", "name": "email"}, "", form_sans), text="x@y.fr"))
verifier("écrire un mot de passe est refusé",
         not permis("input", Noeud("input", {"type": "password", "name": "search_pwd"}, "", form_post), text="x"))
verifier("écrire dans le champ « Nom » d'un formulaire de contact est refusé",
         not permis("input", Noeud("input", {"type": "text", "name": "nom"}, "", form_post), text="Duret"))

# ── Touches ──
verifier("Entrée (valider une recherche) est permise", ls.interaction_permise("send_keys", {"keys": "Enter"})[0])
verifier("Échap (fermer une fenêtre) est permise", ls.interaction_permise("send_keys", {"keys": "Escape"})[0])
verifier("taper du texte au clavier est refusé", not ls.interaction_permise("send_keys", {"keys": "bonjour"})[0])
verifier("un raccourci (Control+a) est refusé", not ls.interaction_permise("send_keys", {"keys": "Control+a"})[0])

# ── Domaines, identité, consigne ──
dom = ls.domaines_de_lecture(["https://www.gerflor.fr/produits", "gerflor.fr", "cstb.fr"])
verifier("« https://www.gerflor.fr/produits » → gerflor.fr et ses sous-domaines, sans doublon",
         dom == ["gerflor.fr", "*.gerflor.fr", "cstb.fr", "*.cstb.fr"], dom)
verifier("un résultat sur cdn.gerflor.fr est dans le périmètre, gerflor.com non",
         ls.hote_autorise("https://cdn.gerflor.fr/fiche.pdf", dom) and not ls.hote_autorise("https://www.gerflor.com/", dom))
verifier("un site imité (gerflor.fr.exemple.com) n'est pas dans le périmètre",
         not ls.hote_autorise("https://gerflor.fr.exemple.com/", dom))
ua = ls.agent_utilisateur("Chromium 152.0.7977.75 built on Debian GNU/Linux 13 (trixie)")
verifier("l'identité est celle d'un Chrome ordinaire, à la version du binaire",
         "Chrome/152.0.0.0" in ua and "Headless" not in ua, ua)
verifier("sans version lisible, une identité plausible quand même", "Chrome/" in ls.agent_utilisateur(""))
cons = ls.consigne_de_navigation(dom, True)
verifier("la consigne dit d'explorer au lieu de deviner, nomme les sites et ce que la lecture permet",
         "N'invente pas" in cons and "gerflor.fr" in cons and "*.gerflor" not in cons and "LECTURE" in cons, cons)

# ── Le câblage de browser_agent.py ──
src = (TRAVAILLEUR / "browser_agent.py").read_text(encoding="utf-8")
arbre = ast.parse(src)
verifier("le navigateur de l'agent reçoit l'identité d'un Chrome ordinaire",
         '"user_agent": await _agent_utilisateur()' in src)
verifier("l'agent reçoit sa consigne de situation", "extend_system_message=lecture_sure.consigne_de_navigation(" in src)
verifier("aucun identifiant n'est injecté en lecture",
         "sensitive = {} if readonly else credentials.build_sensitive_data(" in src)
fonctions = {n.name for n in ast.walk(arbre) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
verifier("l'action `search` est redéfinie et servie par le lecteur du conteneur",
         "search" in fonctions and "rapide.chercher(q, 4, 12000, concurrence=1)" in src)
verifier("chaque interaction passe par la garde de lecture avant de s'exécuter",
         "lecture_sure.interaction_permise(action_name" in src)
verifier("l'agent tourne en mode rapide, sans juge final (appels du modèle divisés par deux)",
         "flash_mode=True" in src and "use_judge=False" in src)
import re as _re
motif = _re.search(r'_CREDIT_EPUISE = re\.compile\((r"[^"]+")', src)
credit = _re.compile(eval(motif.group(1)), _re.I) if motif else None
verifier("un refus 402 « more credits » se reconnaît, un délai dépassé non",
         credit is not None
         and credit.search("Error code: 402 - {'error': {'message': 'This request requires more credits'")
         and not credit.search("LLM call timed out after 120 seconds"))
verifier("le crédit épuisé se dit en toutes lettres au lieu d'un faux résumé",
         "faute de crédit chez son" in src and "NAVIGATION INACHEVÉE" in src)
verifier("le lecteur rapide sait lire une page à la fois",
         "concurrence: int = 2" in (TRAVAILLEUR / "rapide.py").read_text(encoding="utf-8"))

print("\n" + ("✓ 0 échec" if not echecs else f"✗ {len(echecs)} échec(s)"))
sys.exit(1 if echecs else 0)
