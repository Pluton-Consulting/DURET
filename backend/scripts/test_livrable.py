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
espace = {"logger": _Journal(), "AgentState": dict}
extraire(racine / "agents" / "agent1.py",
         {"_re_livrables", "_BLOC_UI_RE", "_TYPES_LIVRABLE", "_reference_bloc",
          "_blocs_livrables", "fichiers_du_fil", "_plat_nom", "_designe_le_meme",
          "_livrables_a_l_ecran"}, espace)
livrables = espace["_livrables_a_l_ecran"]
fichiers_du_fil = espace["fichiers_du_fil"]

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
