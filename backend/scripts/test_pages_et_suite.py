"""
Banc « LES PAGES QU'IL FAUT LIRE, ET CE QUI VIENT APRÈS » — audit du 15/09,
fiche D-24/S-24 — le même fichier des deux côtés.

CE QUI ÉTAIT FAUX :
  · on rendait les CINQ PREMIÈRES pages d'un PDF, toujours. Sur un dossier de
    quarante pages, la cote demandée est page 8 et le tableau des quantités
    page 23 : l'assistant répondait « non visible » après avoir lu la page de
    garde et trois pages de clauses — et il ne disait pas combien il avait lu ;
  · la suite du tour se décidait sur des MOTS, dans la demande puis dans la
    réponse libre du modèle. Une demande de RETOUCHE partait vers l'assistant
    même là où aucun moteur de retouche n'est installé : l'assistant n'avait
    alors aucun geste à appeler, et improvisait une promesse.

CE BANC PROUVE (fonctions EXÉCUTÉES, PDF doublé) :
  1. les pages se choisissent d'après la question, la page 1 restant toujours
     lue (cartouche, échelle, nom de l'affaire) ;
  2. sans question utile, sans couche texte, ou sur un court document, rien ne
     change — le comportement d'avant reste le défaut ;
  3. le modèle apprend QUELLES pages il voit, et qu'il en manque ;
  4. la suite du tour est NOMMÉE, et une retouche est confrontée au registre
     réel des capacités : sans moteur, on ne passe pas la main.

Usage : python backend/scripts/test_pages_et_suite.py [backend]
"""
import ast
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ PAGES LUES ET SUITE DU TOUR — {BACKEND.parent}\n")

source = (BACKEND / "agents" / "agent2.py").read_text(encoding="utf-8")
arbre = ast.parse(source)
voulu = {"_MOTS_VIDES", "_mots_utiles", "_pages_a_lire", "_entete_pages", "MAX_PAGES_PDF",
         "suite_du_tour", "SUITE_DOCUMENT", "SUITE_RETOUCHE", "SUITE_SANS_MOTEUR",
         "SUITE_AUCUNE", "_RETOUCHE"}
gardes = [n for n in arbre.body
          if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in voulu)
          or (isinstance(n, ast.Assign)
              and any(isinstance(c, ast.Name) and c.id in voulu for c in n.targets))]
espace = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=gardes, type_ignores=[])),
             "agent2", "exec"), espace)
manquants = sorted(voulu - set(espace))
verifier("les fonctions de choix et de contrat existent", not manquants, manquants)


# ── UN PDF DOUBLÉ : quarante pages, la cote utile page 8 ───────────────────
class _Page:
    def __init__(self, texte):
        self._texte = texte

    def get_text(self):
        return self._texte


class _Doc:
    def __init__(self, textes):
        self._pages = [_Page(t) for t in textes]
        self.page_count = len(self._pages)

    def load_page(self, numero):
        return self._pages[numero]


TEXTES = ["CCTP — page de garde, affaire 2029 AIRBORNE"] + [f"clauses administratives {i}"
                                                            for i in range(1, 7)]
TEXTES.append("Coupe AA — hauteur sous plafond 2,50 m, cote de la terrasse 4,20 m")  # page 8 (index 7)
TEXTES += [f"annexe {i}" for i in range(9, 23)]
TEXTES.append("Quantitatif : terrasse bois 42 m2, gravier 18 m2")                    # page 23
TEXTES += [f"annexe {i}" for i in range(24, 41)]

print("1. Les pages se choisissent d'après la question")
pages = espace["_pages_a_lire"](_Doc(TEXTES), "quelle est la cote de la terrasse ?", 5)
verifier("la page où se trouve la cote est lue (page 8)", 7 in pages, [p + 1 for p in pages])
verifier("la page 1 est TOUJOURS lue (cartouche, échelle, nom de l'affaire)", 0 in pages,
         [p + 1 for p in pages])
verifier("on n'en rend pas plus que le plafond", len(pages) <= 5, pages)
verifier("elles sont rendues dans l'ordre du document", pages == sorted(pages), pages)
quanti = espace["_pages_a_lire"](_Doc(TEXTES), "donne-moi le quantitatif en m2", 5)
verifier("une autre question mène à une autre page (23)", 22 in quanti, [p + 1 for p in quanti])

print("2. Sans de quoi choisir, rien ne change")
verifier("une question sans mot utile garde les premières pages",
         espace["_pages_a_lire"](_Doc(TEXTES), "et alors ?", 5) == [0, 1, 2, 3, 4])
verifier("un plan SCANNÉ (aucune couche texte) garde les premières pages",
         espace["_pages_a_lire"](_Doc([""] * 40), "la cote de la terrasse", 5) == [0, 1, 2, 3, 4])
verifier("un document plus court que le plafond est lu en entier",
         espace["_pages_a_lire"](_Doc(TEXTES[:3]), "la cote", 5) == [0, 1, 2])
verifier("les mots vides ne servent pas à choisir",
         espace["_mots_utiles"]("quelle est la page du document ?") == [])

print("3. Le modèle sait ce qu'il voit, et ce qui lui manque")
entete = espace["_entete_pages"]({"pages": [1, 2, 3], "pages_totales": 40,
                                  "pages_ignorees": 37, "pages_lues": [1, 8, 23]})
verifier("il connaît les NUMÉROS des pages montrées", "1, 8, 23" in entete, entete[:200])
verifier("il sait combien le document en compte", "40 page(s)" in entete, entete[:200])
verifier("il lui est dit de signaler ce qu'il n'a pas lu",
         "37 page(s) n'ont PAS été analysées" in entete and "ne conclus rien" in entete)
verifier("… et de DEMANDER une page manquante plutôt que de l'estimer",
         "DEMANDE-LA plutôt que de l'estimer" in entete)
court = espace["_entete_pages"]({"pages": [1], "pages_totales": 1})
verifier("une photo seule n'a pas d'en-tête de pages", court == "", court)

print("4. La suite du tour est nommée, pas devinée")
suite = espace["suite_du_tour"]
for demande in (
    "Remplis le cadre mémoire et livre un Word. Ne consulte ni ne modifie le NAS ou les mails.",
    "Modifie ce document Word en ajoutant le logo et conserve les rubriques.",
    "Génère un Excel pour les métrés. N’invente aucune dimension.",
):
    verifier("un livrable reste documentaire malgré une interdiction ou une modification : " + demande,
             suite(demande, False) == espace["SUITE_DOCUMENT"])
verifier("« prépare le devis » appelle un document",
         suite("analyse ce plan puis prépare le devis", True) == espace["SUITE_DOCUMENT"])
verifier("« enlève les oliviers » appelle une retouche, là où elle existe",
         suite("enlève les oliviers sur cette photo", True) == espace["SUITE_RETOUCHE"])
verifier("LÀ OÙ AUCUN MOTEUR N'EST INSTALLÉ, la même demande ne passe pas la main",
         suite("enlève les oliviers sur cette photo", False) == espace["SUITE_SANS_MOTEUR"])
verifier("« c'est quoi cette plante ? » n'appelle personne",
         suite("c'est quoi cette plante ?", True) == espace["SUITE_AUCUNE"])
verifier("une demande de devis reste un document même sans moteur d'images",
         suite("chiffre-moi cette terrasse", False) == espace["SUITE_DOCUMENT"])

routeur = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
verifier("le routeur lit le contrat AVANT les mots-clés",
         routeur.index('suite = state.get("vision_suite")')
         < routeur.index("if any(m in demande for m in _SUITE_ATTENDUE)"))
verifier("une retouche sans moteur ne part pas chez l'assistant",
         'return "agent1" if suite in ("document", "retouche") else "human_gate"' in routeur)
verifier("les mots-clés restent en second (tours d'avant, chemins sans vision)",
         "_SUITE_ATTENDUE" in routeur and "_VISION_ANNONCE_UNE_RETOUCHE" in routeur)
etat = (BACKEND / "agents" / "state.py").read_text(encoding="utf-8")
verifier("la clé d'état est DÉCLARÉE (sinon LangGraph la jette)",
         "vision_suite: Optional[str]" in etat)
runtime = (BACKEND / "agents" / "runtime.py").read_text(encoding="utf-8")
verifier("… et remise à zéro à chaque tour", '"vision_suite": None,' in runtime)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
