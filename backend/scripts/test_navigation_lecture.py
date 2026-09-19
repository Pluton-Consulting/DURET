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
gerflor = Noeud("form", {"action": "/search/collections", "method": "GET", "id": "gerflor-search-form"}, parent=page)
verifier("le bouton de recherche de Gerflor (id « edit-submit », valeur « Rechercher ») se clique — refusé le 19/09",
         permis("click", Noeud("input", {"type": "submit", "id": "edit-submit", "value": "Rechercher",
                                         "class": "btn-search js-form-submit form-submit"}, "", gerflor)))
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
verifier("une gamme entière se relève sur la page qui liste TOUT, avec le décompte « N sur M » (19/09 : "
         "l'agent avait conclu « c'est tout » sur une page de collection, 4 produits sur 44)",
         "liste TOUS" in cons and "combien tu en as relevés sur" in cons)
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

# ── Plusieurs pages d'un geste : `ouvrir_page` avec `urls` (19/09) ──
import asyncio as _aio
import types as _types
src_sk = (RACINE / "backend" / "browser" / "skills.py").read_text(encoding="utf-8")
src_to = (RACINE / "backend" / "browser" / "tools.py").read_text(encoding="utf-8")
arbre_sk, arbre_to = ast.parse(src_sk), ast.parse(src_to)
lus = []


async def faux_fetch(url, user_id, agent_id, reason="", capture=True):
    lus.append((url, capture))
    if "absente" in url:
        return {"success": False, "content": "Échec"}
    corps = ("Menu Produits Applications Inspiration " * 40
             + "Applications sur le marché : santé, éducation, tertiaire, fort trafic. "
             + "Données techniques " * 60)
    return {"success": True, "title": url.rsplit("/", 1)[-1], "content": f"Source : {url}\nTitre : t\n\n{corps}"}


outils_mod = _types.ModuleType("browser.tools")
exec(compile(ast.Module(body=[n for n in arbre_to.body if isinstance(n, ast.FunctionDef) and n.name == "_plat_web"],
                        type_ignores=[]), "tools", "exec"), outils_mod.__dict__)
outils_mod.fetch_url = faux_fetch
sys.modules.setdefault("browser", _types.ModuleType("browser"))
sys.modules["browser.tools"] = outils_mod
esp = {"logger": _types.SimpleNamespace(info=lambda *a, **k: None)}
garde = [n for n in arbre_sk.body
         if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in ("_adresses", "_passages", "_ouvrir_plusieurs", "_page_introuvable"))
         or (isinstance(n, ast.Assign) and any(isinstance(c, ast.Name) and c.id in ("MAX_PAGES_PAR_APPEL", "BUDGET_PAGES") for c in n.targets))]
exec(compile(ast.Module(body=garde, type_ignores=[]), "skills", "exec"), esp)
verifier("une seule adresse reste le geste d'avant (une page, avec son aperçu)",
         esp["_adresses"]({"url": "gerflor.fr"}) == ["https://gerflor.fr"])
adr = esp["_adresses"]({"urls": "www.gerflor.fr/produits/a, https://www.gerflor.fr/produits/b\nwww.gerflor.fr/produits/a"})
verifier("`urls` en texte : séparées, protocole complété, sans doublon",
         adr == ["https://www.gerflor.fr/produits/a", "https://www.gerflor.fr/produits/b"], adr)
urls = [f"https://www.gerflor.fr/produits/taralay-{i}" for i in range(14)] + ["https://www.gerflor.fr/absente"]
res = _aio.run(esp["_ouvrir_plusieurs"](urls, {"cherche": "applications usage"}, None))
verifier("douze pages lues au plus par appel, le reste DIT (non ouvertes)",
         len(res["pages"]) == 12 and len(res["non_ouvertes"]) == 3 and "rappelle `ouvrir_page`" in res["a_faire"], res.get("non_ouvertes"))
verifier("lues SANS capture (un Chromium de moins par page)", lus and all(c is False for _, c in lus), lus[:2])
verifier("chaque page rend le passage qui porte ce qu'on cherche, dans le budget",
         all("santé, éducation" in p["contenu"] and len(p["contenu"]) <= 1200 for p in res["pages"]),
         [(len(p["contenu"]), "santé, éducation" in p["contenu"]) for p in res["pages"]])
verifier("le tableau des pages lues est garanti à l'écran", res["bloc_garanti"] and len(res["bloc_ui"]["rows"]) == 12)
res2 = _aio.run(esp["_ouvrir_plusieurs"](["https://a.fr/1", "https://www.gerflor.fr/absente"], {}, None))
verifier("une page qui ne s'ouvre pas est dite non lue, les autres passent",
         res2["lues"] == 1 and res2["non_lues"] == ["https://www.gerflor.fr/absente"], res2.get("non_lues"))
verifier("après une navigation, la suite rapide est dite : `ouvrir_page` avec `urls`, pas un autre `naviguer`",
         '"adresses_trouvees": trouvees[:40]' in src_sk and "`ouvrir_page` et le paramètre `urls`" in src_sk)
src_a1 = (RACINE / "backend" / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("les résultats web ne se coupent plus à 4 000 caractères",
         '"chercher_web", "ouvrir_page", "naviguer",' in src_a1)

garde2 = [n for n in arbre_sk.body if isinstance(n, ast.FunctionDef) and n.name == "_page_introuvable"]
esp2 = {}
exec(compile(ast.Module(body=garde2, type_ignores=[]), "skills", "exec"), esp2)
verifier("une page « Page not found » servie en 200 n'est pas une source (19/09 : son aperçu s'affichait)",
         esp2["_page_introuvable"]("Page not found | Gerflor Professionnels", "Menu Produits " * 50))
verifier("…une fiche produit normale l'est", not esp2["_page_introuvable"](
    "TARALAY PREMIUM COMPACT 43 : Hétérogènes U3U4 | Gerflor", "Applications : santé, éducation. " * 40))
verifier("…une page courte qui ne dit que « introuvable » aussi",
         esp2["_page_introuvable"]("Gerflor", "Désolé, cette page est introuvable."))

print("\n" + ("✓ 0 échec" if not echecs else f"✗ {len(echecs)} échec(s)"))
sys.exit(1 if echecs else 0)
