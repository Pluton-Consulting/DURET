"""
Banc du LIVRABLE — ce qui a été produit atteint l'écran, ce qui est inventé s'efface.

Rejoue la conversation réelle du 23/08 (traces Langfuse, 13:05 → 13:10), celle
où un Excel de 477 clients a été produit puis jamais montré :

  · tour 1 — `liste_clients {fichier: true}` réussit, le modèle termine par une
    QUESTION (« quel est votre mail ? »). Le filet des promesses ne pouvait pas
    s'appliquer : une question n'est pas une promesse. Le fichier doit
    néanmoins s'afficher.
  · tour 3 — plus aucune action, et le modèle fabrique une vignette de son cru
    (`{"type":"doc","name":"Liste des clients"}`) : ni URL, ni aperçu, ni
    téléchargement. Elle doit céder la place au VRAI fichier du fil.

Les fonctions sont extraites des modules livrés (agent1.py charge un graphe
entier à l'import : on ne prend que ce qu'on teste). Ni base, ni réseau.
"""
import sys, ast, pathlib, json

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
racine = pathlib.Path(BACKEND)

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
    """Exécute, du module livré, les seules définitions demandées."""
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = []
    for n in arbre.body:
        # `from __future__ import annotations` d'abord : sans lui, une
        # annotation `list | None` s'évaluerait ici et tomberait sur Python 3.9.
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            gardes.append(n)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id in noms for c in n.targets):
            gardes.append(n)
        elif isinstance(n, ast.Import) and any(
                (a.asname or a.name) in noms for a in n.names):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), chemin, "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


class _Msg:
    def __init__(self, content):
        self.content = content


class _Journal:
    def info(self, *a, **k):
        pass
    warning = info


def bloc_ui(obj):
    return "```ui\n" + json.dumps(obj, ensure_ascii=False) + "\n```"


def res(skill, sortie, ok=True):
    return {"skill": skill, "ok": ok,
            "resultat_masque": json.dumps(sortie, ensure_ascii=False)}


# ── agent1 : le livrable à l'écran ─────────────────────────────────────────
# `reclame_un_prealable` vit dans annonce.py (importable seul : il ne dépend
# que de `re`) ; on le charge comme le fait test_annonce.py, et on le donne au
# namespace où les fonctions d'agent1 iront le chercher.
import importlib.util
_spec = importlib.util.spec_from_file_location("annonce", racine / "agents" / "annonce.py")
_annonce = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_annonce)

espace = {"logger": _Journal(), "AgentState": dict,
          "reclame_un_prealable": _annonce.reclame_un_prealable}
extraire(racine / "agents" / "agent1.py",
         {"_re_livrables", "_BLOC_UI_RE", "_TYPES_LIVRABLE", "_reference_bloc",
          "_blocs_livrables", "fichiers_du_fil", "_plat_nom", "_designe_le_meme",
          "_meme_livrable", "_livrables_a_l_ecran", "_redaction_dement_le_livrable"}, espace)
livrables = espace["_livrables_a_l_ecran"]
fichiers_du_fil = espace["fichiers_du_fil"]
dement = espace["_redaction_dement_le_livrable"]

FICHIER = {"type": "fichier", "url": "/api/documents/8UZRq9I-WO-KNO90pS8G2dzQvxjbuh4q",
           "nom": "clients.xlsx", "titre": "Liste des clients", "format": "xlsx",
           "octets": 19834}
SORTIE = {"trouve": True, "source_type": "client", "nombre": 478, "affiches": 477,
          "fichier": FICHIER["url"], "bloc_ui": FICHIER,
          "message_final": "478 clients, la liste complète est dans le fichier Excel ci-dessous."}

print(f"\n═══ LE LIVRABLE ATTEINT L'ÉCRAN — {BACKEND}\n")

# 1. Le cas exact du 23/08 : le fichier est produit, le modèle pose une question.
question = ("Pour créer ce fichier Excel, j'ai besoin de connaître votre adresse email. "
            "Quel est votre mail professionnel ?")
r = livrables(question, {"tool_results": [res("liste_clients", SORTIE)], "messages": []})
verifier("un fichier produit s'affiche même quand le modèle pose une question",
         FICHIER["url"] in r and r.startswith("Pour créer"), r[:160])
verifier("le bloc restitué est un vrai bloc `fichier`", '"type": "fichier"' in r, r[-160:])

# 2. Le modèle a fait son travail : on n'ajoute rien.
deja = "478 clients.\n\n" + bloc_ui(FICHIER)
r = livrables(deja, {"tool_results": [res("liste_clients", SORTIE)], "messages": []})
verifier("un fichier déjà montré n'est pas montré deux fois", r.count(FICHIER["url"]) == 1, r)

# 3. La vignette inventée du tour 3 cède la place au vrai fichier du fil.
fil = [_Msg("478 clients.\n\n" + bloc_ui(FICHIER))]
invente = ("La liste des clients existe déjà :\n\n"
           + bloc_ui({"type": "doc", "name": "Liste des clients", "kind": "XLSX",
                      "meta": "19 Ko, 477 clients"})
           + "\n\nSouhaitez-vous la télécharger ?")
r = livrables(invente, {"tool_results": [], "messages": fil})
verifier("une vignette inventée est remplacée par le fichier réel du fil",
         ('"type": "doc"' not in r) and FICHIER["url"] in r, r[:200])

# 4. Un `doc` qui parle d'AUTRE CHOSE (résultat de recherche) reste intact.
autre = "Voici le document trouvé :\n\n" + bloc_ui(
    {"type": "doc", "name": "CCTP lot 3 - plantations.pdf"})
r = livrables(autre, {"tool_results": [], "messages": fil})
verifier("une carte `doc` sans rapport n'est pas touchée",
         "CCTP lot 3" in r and FICHIER["url"] not in r, r[:200])

# 5. Un bloc `fichier` écrit de mémoire, dont l'URL n'existe pas, ne s'affiche pas.
faux = "Voici le fichier :\n\n" + bloc_ui(
    {"type": "fichier", "url": "/api/documents/inventé", "nom": "clients.xlsx"})
r = livrables(faux, {"tool_results": [], "messages": fil})
verifier("une URL inventée est retirée, la vraie prend sa place",
         "inventé" not in r and FICHIER["url"] in r, r[:200])

# 6. Rien de produit, rien dans le fil : le texte ne bouge pas.
r = livrables("Bonjour, comment puis-je vous aider ?", {"tool_results": [], "messages": []})
verifier("sans livrable, le texte est rendu tel quel", r == "Bonjour, comment puis-je vous aider ?", r)

# 7. Les fichiers du fil se relisent dans l'historique, le plus récent en dernier.
autre_fichier = dict(FICHIER, url="/api/documents/AUTRE", nom="devis.xlsx", titre="Devis")
vus = fichiers_du_fil({"messages": [_Msg(bloc_ui(FICHIER)), _Msg(bloc_ui(autre_fichier)),
                                    _Msg(bloc_ui({"type": "table", "columns": [], "rows": []}))]})
verifier("l'historique rend les fichiers, pas les tableaux",
         [b["url"] for b in vus] == [FICHIER["url"], "/api/documents/AUTRE"], str(vus))

# 8. Une planche de visuels est un livrable comme un autre.
visuel = {"type": "visuel", "titre": "Essai", "images": [{"cle": "79800c896bd4e138b125d2d0"}]}
r = livrables("Je prépare le rendu.", {"tool_results": [res("tester_visuel", {"genere": True, "bloc_ui": visuel})],
                                       "messages": []})
verifier("un visuel produit s'affiche aussi", "79800c896bd4e138b125d2d0" in r, r[:160])

# 9. Un bloc imbriqué (une planche d'images) se relit entier dans l'historique :
#    le motif doit aller jusqu'à la DERNIÈRE accolade, pas à la première.
vus = fichiers_du_fil({"messages": [_Msg("Voici l'essai.\n\n" + bloc_ui(visuel))]})
verifier("un bloc imbriqué est lu en entier",
         len(vus) == 1 and vus[0].get("images"), str(vus))

# ── le doublon du 29/08 : un même Excel affiché deux fois ──────────────────
print()

# 10. Le skill rappelé dans le tour (autres colonnes) : deux jetons, UN fichier.
V1 = dict(FICHIER, url="/api/documents/PREMIER-JET")
V2 = dict(FICHIER, url="/api/documents/SECOND-JET")
r = livrables("La liste est prête.",
              {"tool_results": [res("liste_clients", dict(SORTIE, bloc_ui=V1, fichier=V1["url"])),
                                res("liste_clients", dict(SORTIE, bloc_ui=V2, fichier=V2["url"]))],
               "messages": []})
verifier("le même livrable produit deux fois ne s'affiche qu'une fois, dernière version",
         r.count('"type": "fichier"') == 1 and V2["url"] in r and V1["url"] not in r, r[:300])

# 11. Le modèle recopie le bloc en échappant les barres obliques (JSON valide) :
#     la sous-chaîne de l'URL est introuvable dans le texte brut, le filet
#     ajoutait le bloc une seconde fois.
echappe = "```ui\n" + json.dumps(FICHIER, ensure_ascii=False).replace("/", "\\/") + "\n```"
r = livrables("478 clients.\n\n" + echappe,
              {"tool_results": [res("liste_clients", SORTIE)], "messages": []})
verifier("un bloc recopié avec des barres échappées n'est pas doublé",
         r.count('"type": "fichier"') == 1, r[:300])

# 12. Le modèle écrit le même bloc DEUX fois : un seul aperçu.
r = livrables("478 clients.\n\n" + bloc_ui(FICHIER) + "\n\n" + bloc_ui(FICHIER),
              {"tool_results": [res("liste_clients", SORTIE)], "messages": []})
verifier("le même bloc écrit deux fois par le modèle est dédoublonné",
         r.count('"type": "fichier"') == 1, r[:300])

# 13. Une version ANTÉRIEURE (tour passé) recopiée depuis l'historique, alors
#     que le tour vient d'en produire une neuve : la vieille cède la place.
vieille = dict(FICHIER, url="/api/documents/VERSION-D-HIER")
r = livrables("Voici la liste.\n\n" + bloc_ui(vieille),
              {"tool_results": [res("liste_clients", dict(SORTIE, bloc_ui=V2, fichier=V2["url"]))],
               "messages": [_Msg(bloc_ui(vieille))]})
verifier("une version antérieure du fil cède la place à celle du tour",
         V2["url"] in r and "VERSION-D-HIER" not in r and r.count('"type": "fichier"') == 1,
         r[:300])

# 14. Deux livrables DIFFÉRENTS produits dans le tour s'affichent tous les deux.
devis = {"type": "fichier", "url": "/api/documents/DEVIS-77", "nom": "devis.xlsx",
         "titre": "Devis du mois", "format": "xlsx"}
r = livrables("Les deux fichiers sont prêts.",
              {"tool_results": [res("liste_clients", SORTIE),
                                res("produire_document", {"trouve": True, "bloc_ui": devis})],
               "messages": []})
verifier("deux livrables différents ne sont pas fusionnés",
         FICHIER["url"] in r and devis["url"] in r, r[:300])

# ── le démenti du 30/08 : la question périmée au-dessus d'un fichier produit ─
print()

# La réponse EXACTE lue en production le 30/08 (vieille conversation, LongCat
# recopiait sa réponse d'avant le correctif du 29/08). L'Excel était produit,
# avec la bonne adresse — et ce texte s'affichait au-dessus.
PERIMEE = ('Pour créer ce fichier, j\'ai besoin de votre adresse email '
           'professionnelle exacte. "" est une balise masquée, pas un email réel.\n\n'
           'Quel est votre email ?\n\n'
           'Une fois communiqué, je créerai un fichier Excel avec :\n'
           '- Colonne A : les 90 noms de fournisseurs\n'
           '- Colonne B : votre email répété sur toutes les lignes')
FOURN = {"type": "fichier", "url": "/api/documents/FOURNISSEURS-90",
         "nom": "fournisseurs.xlsx", "titre": "Liste des fournisseurs", "format": "xlsx"}
SORTIE_F = {"trouve": True, "nombre": 90, "bloc_ui": FOURN,
            "message_final": "90 fournisseurs, la liste complète est dans le fichier Excel ci-dessous."}

# 15. Le cas réel : livrable produit, texte qui réclame un préalable → démenti.
verifier("la question périmée du 30/08 est reconnue comme un démenti",
         dement(PERIMEE, [res("liste_fournisseurs", SORTIE_F)]))

# 16. Sans livrable produit, la même question est LÉGITIME : on n'y touche pas.
verifier("la même question sans livrable produit reste légitime",
         not dement(PERIMEE, []))

# 17. Le modèle montre le fichier ET pose une question : il a fait son travail.
verifier("un texte qui MONTRE le livrable n'est jamais remplacé",
         not dement("Voici la liste. Merci de me communiquer vos retours.\n\n"
                    + bloc_ui(FOURN), [res("liste_fournisseurs", SORTIE_F)]))

# 18. Une suite proposée n'est pas un préalable réclamé.
verifier("« voulez-vous que je l'envoie par mail ? » n'est pas un démenti",
         not dement("90 fournisseurs trouvés. Voulez-vous que je l'envoie par mail ?",
                    [res("liste_fournisseurs", SORTIE_F)]))

# 19. Le branchement existe dans le code livré : le filet est câblé, pas
#     seulement défini.
_src = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("rehydrate_node passe par le démenti du livrable",
         "elif _redaction_dement_le_livrable(text" in _src)


# ── le mauvais fichier du 30/08, 13:34 : une invention ne se corrige pas ───
#    avec N'IMPORTE quel fichier. « Fais un word avec les infos de
#    l'entreprise » : rien n'a été produit (routage à terre), le modèle a
#    prétendu l'avoir fait avec un bloc inventé, et le repli a restitué le
#    dernier fichier du fil — l'Excel des fournisseurs, sans aucun rapport.
print()

fil_fournisseurs = [_Msg("90 fournisseurs.\n\n" + bloc_ui(FOURN))]

# 20. Le cas réel : l'invention ne désigne rien qu'on tienne → RIEN ne
#     s'affiche, et l'écran dit que le fichier n'existe pas.
menteur = ("Voici le document avec toutes les informations de l'entreprise :\n\n"
           + bloc_ui({"type": "fichier", "url": "/api/documents/INVENTE",
                      "nom": "infos_entreprise.docx",
                      "titre": "Informations de l'entreprise"}))
r = livrables(menteur, {"tool_results": [], "messages": fil_fournisseurs})
verifier("une invention sans rapport ne restitue PAS le dernier fichier du fil",
         FOURN["url"] not in r and "INVENTE" not in r, r[:300])
verifier("et l'écran DIT que rien n'a été produit",
         "n'a pas été réellement produit" in r, r[:300])

# 21. « Remontre-moi la liste » : l'invention désigne LE MÊME fichier — le
#     repli d'origine reste entier, le vrai fichier revient.
meme = ("La voici :\n\n"
        + bloc_ui({"type": "fichier", "url": "/api/documents/URL-REINVENTEE",
                   "nom": "fournisseurs.xlsx", "titre": "Liste des fournisseurs"}))
r = livrables(meme, {"tool_results": [], "messages": fil_fournisseurs})
verifier("une invention qui désigne un fichier du fil est remplacée par le vrai",
         FOURN["url"] in r and "URL-REINVENTEE" not in r
         and "n'a pas été réellement produit" not in r, r[:300])


# ── la livraison fantôme atteint le FORCEUR — le routage lui-même ──────────
#    Trois tours de suite le 30/08 : le modèle prétend AU PASSÉ avoir produit
#    le Word (« c'est bon, il est téléchargeable ») sans appeler un seul
#    skill. `est_une_annonce` couvre le futur ; le passé doit partir au
#    forceur, qui repart d'un contexte neuf.
print()

import re as _re
import types as _types
faux_proto = _types.ModuleType("skills.protocol")
faux_proto.BLOC_ACTION_RE = _re.compile(r"```action\s*\{.*?\}\s*```", _re.S)
faux_proto.BLOC_NATIF_RE = _re.compile(r"(?!x)x")
faux_proto.BLOC_ACTION_TRONQUE_RE = _re.compile(r"(?!x)x")
faux_proto.BALISAGE_OUTIL_RE = _re.compile(r"(?!x)x")
sys.modules.setdefault("skills", _types.ModuleType("skills"))
sys.modules["skills.protocol"] = faux_proto

espace2 = dict(espace)
espace2.update({
    "est_une_annonce": _annonce.est_une_annonce,
    "promesse_sans_suite": _annonce.promesse_sans_suite,
    "cloture_attendue": _annonce.cloture_attendue,
    "pretend_avoir_livre": _annonce.pretend_avoir_livre,
    "demande_une_production": _annonce.demande_une_production,
    "MAX_FORCAGES_PAR_TOUR": 2,
})
extraire(racine / "agents" / "agent1.py",
         {"route_apres_llm", "_texte_visible", "_montre_un_fichier_du_fil"}, espace2)
route = espace2["route_apres_llm"]

# 22. Le tour exact : demande de production, prétention au passé, zéro action.
verifier("« j'ai créé le document » sans production part au FORCEUR",
         route({"llm_response": "C'est bon, le document Word a été créé et le "
                                "fichier est téléchargeable.",
                "query": "fais un word avec toutes les infos de l'entreprise",
                "tool_results": [], "forcages": 0,
                "messages": fil_fournisseurs}) == "forcer")

# 23. La remontrance honnête : un VRAI fichier du fil sous la prétention.
verifier("« voici le fichier » avec le vrai bloc du fil ne force RIEN",
         route({"llm_response": "Voici le fichier demandé.\n\n" + bloc_ui(FOURN),
                "query": "remontre-moi la liste des fournisseurs",
                "tool_results": [], "forcages": 0,
                "messages": fil_fournisseurs}) == "rehydrate")

# 24. La clarification légitime sur une demande de production.
verifier("une question de clarification n'est pas forcée",
         route({"llm_response": "Quelles informations voulez-vous dans le document ?",
                "query": "fais un word avec toutes les infos de l'entreprise",
                "tool_results": [], "forcages": 0, "messages": []}) == "rehydrate")

# 25. La vraie production : un livrable est sorti, rien à forcer.
verifier("une production réelle passe sans forçage",
         route({"llm_response": "Voici le fichier.\n\n" + bloc_ui(FOURN),
                "query": "fais un excel des fournisseurs",
                "tool_results": [res("liste_fournisseurs", SORTIE_F)],
                "forcages": 0, "messages": []}) == "rehydrate")

# 26. Le budget de forçage borne tout : pas de boucle infinie.
verifier("budget épuisé : le tour se termine au lieu de boucler",
         route({"llm_response": "Le document a été créé et est téléchargeable.",
                "query": "fais un word avec les infos",
                "tool_results": [], "forcages": 2,
                "messages": []}) == "rehydrate")


# ── routines : la colonne demandée, et le mail qu'on ne demande pas ────────
espace_r = {"logging": __import__("logging"), "re": __import__("re"),
            "unicodedata": __import__("unicodedata")}
extraire(racine / "skills" / "routines.py",
         {"_plat", "_CLE_PAR_LIBELLE", "_C_EST_MOI", "_colonnes_gardees",
          "_colonnes_ajoutees"}, espace_r)
gardees, ajoutees = espace_r["_colonnes_gardees"], espace_r["_colonnes_ajoutees"]


class _Moi:
    email = "noa@pluton-consulting.fr"
    name = "Noa Benitez"


print()
verifier("« une colonne pleine de noms » → la seule colonne Client",
         gardees({"colonnes": ["Client"]}) == ["nom"], str(gardees({"colonnes": ["Client"]})))
verifier("les libellés du modèle sont reconnus (mail, ville…)",
         gardees({"colonnes": "nom, ville et mail"}) == ["nom", "ville", "email"],
         str(gardees({"colonnes": "nom, ville et mail"})))
verifier("sans `colonnes`, on ne restreint rien", gardees({}) is None)
verifier("`@moi` devient l'adresse de la session",
         ajoutees({"ajouts": {"E-mail": "@moi"}}, _Moi()) == [("E-mail", _Moi.email)],
         str(ajoutees({"ajouts": {"E-mail": "@moi"}}, _Moi())))
verifier("« mon mail » aussi",
         ajoutees({"ajouts": {"Mail": "mon mail"}}, _Moi()) == [("Mail", _Moi.email)],
         str(ajoutees({"ajouts": {"Mail": "mon mail"}}, _Moi())))
verifier("une valeur littérale reste littérale",
         ajoutees({"ajouts": {"Source": "export 2026"}}, _Moi()) == [("Source", "export 2026")])
verifier("les ajouts passés en JSON (LongCat sait faire ça) sont lus",
         ajoutees({"ajouts": '{"E-mail": "@moi"}'}, _Moi()) == [("E-mail", _Moi.email)])
verifier("pas d'ajouts → rien", ajoutees({}, _Moi()) == [])
verifier("un jeton orphelin sur une colonne mail retombe sur l'adresse de la session",
         ajoutees({"ajouts": {"E-mail": "[EMAIL_2]"}}, _Moi()) == [("E-mail", _Moi.email)],
         str(ajoutees({"ajouts": {"E-mail": "[EMAIL_2]"}}, _Moi())))
verifier("un jeton orphelin ailleurs laisse la cellule vide, jamais la balise",
         ajoutees({"ajouts": {"Source": "[PER_3]"}}, _Moi()) == [("Source", "")],
         str(ajoutees({"ajouts": {"Source": "[PER_3]"}}, _Moi())))
verifier("un ajout borné à trois colonnes",
         len(ajoutees({"ajouts": {"a": "1", "b": "2", "c": "3", "d": "4"}}, _Moi())) == 3)

# ── anonymiseur : un jeton ne se remasque pas ──────────────────────────────
sys.path.insert(0, str(racine))
from security.anonymizer import anonymizer  # noqa: E402

print()
# Ce que faisait le NER sur un texte DÉJÀ masqué (carte réelle du 23/08 :
# « [LOC_2] -> "[LOC_1]" », « [PER_7] -> "[PER_1] E-MAIL" »). On appelle le
# poseur de jetons directement : c'est le geste que spaCy déclenchait, et
# spaCy n'est pas installé sur ce poste.
carte, compteurs = {}, {}
rendu = anonymizer._placeholder_for("[PER_1]", "PER", carte, compteurs)
verifier("un jeton seul n'est pas remasqué", rendu == "[PER_1]" and carte == {}, str((rendu, carte)))
rendu = anonymizer._placeholder_for("[PER_1] E-MAIL", "PER", carte, compteurs)
verifier("un span qui AVALE un jeton n'est pas remasqué non plus",
         rendu == "[PER_1] E-MAIL" and carte == {}, str((rendu, carte)))
rendu = anonymizer._placeholder_for("Dupont", "PER", carte, compteurs)
verifier("une vraie entité est toujours masquée",
         rendu == "[PER_1]" and carte == {"[PER_1]": "Dupont"}, str((rendu, carte)))
verifier("aucune valeur de carte ne contient de jeton",
         not any("[" in str(v) for v in carte.values()), str(carte))

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
