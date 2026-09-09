"""
Banc « CHAQUE LIVRABLE SE PRÉSENTE PAR CE QU'IL CONTIENT » — le test de Noa du
09/09, 11:31 (Symbiose) : un prospect, un plan et quatre photos en pièces
jointes, « prépare un dossier complet avec un déroulé de chantier, le
quantitatif des matériaux et des photomontages réalistes ».

Relevé de Noa : « il a aussi produit un excel qui liste des fichiers avec
marqué illisible, et il m'a donné un pdf qui n'a absolument rien à voir qu'il
a l'air de renvoyer à chaque fois ; il a affiché le composant de recherche
internet mais on ne sait pas à quoi ça a servi. » Quatre causes, dans le code :
  1. `termines()` (atelier) comptait parmi les documents PRODUITS tout fichier
     LU sur le serveur (origine « serveur », posée le 08/09 pour que le fichier
     s'affiche) : un PDF de paie ouvert la veille pendant un essai entrait dans
     la liste du prompt ET dans `_cartes_de_l_atelier` — le modèle le rendait
     « dans le dossier » du client à chaque conversation, et le filet des
     livrables, qui le trouvait à l'atelier, le laissait passer ;
  2. l'inventaire lisait par l'extracteur de l'ingestion, qui rend None pour
     toute image : quatre photos et un plan « sans texte lisible », un classeur
     qui ne disait rien du dossier — présenté par le modèle comme « le détail
     chiffré des fournitures », parce qu'il n'avait que le titre pour en parler ;
  3. le tableau web garanti ne portait que l'adresse : ni ce qu'on y a lu, ni
     ce que la recherche a servi à établir ;
  4. rien ne disait au modèle de décrire chaque livrable d'après son CONTENU,
     ni de ne montrer que ce qui a été produit pour la demande.

CE QUE CE BANC PROUVE (sans base, sans réseau, sans modèle) :
  · l'atelier RÉEL (dossier temporaire) : `termines` ne rend que les documents
    produits (rédigés, trame, reproduction), chacun avec son `contenu` ; un
    fichier lu sur le serveur ou reçu par mail n'y est plus, tout en restant
    téléchargeable ;
  · `_livrables_a_l_ecran` EXÉCUTÉ sur la réponse de 11:31, atelier réel : le
    PDF étranger s'efface, le Word et le classeur restent ;
  · `chercher_web` EXÉCUTÉ : deux colonnes (adresse, ce qu'on y a lu) et la
    consigne de dire à quoi la recherche a servi ; `_blocs_garantis` fond deux
    recherches en gardant la recherche de chaque ligne ; `web_search` rend le
    détail par page ;
  · `lire_sans_deposer` EXÉCUTÉ (pièces) : une photo est décrite par la vision
    avec la consigne du classement, un fichier vide ou trop lourd le dit ;
    `analyser` dépose toujours la vignette d'un DWG ;
  · la source du client (`lire_fichier`) EXÉCUTÉE contre un stockage doublé :
    le binaire part au lecteur par type ; l'inventaire EXÉCUTÉ : une photo est
    « lu — description par la vision », et la consigne dit ce qu'EST le classeur ;
  · le prompt porte la règle, et la consigne de l'atelier explique `contenu`.
Tombe sur la version d'avant (1, 2, 3 et 4).
"""
import ast
import asyncio
import json
import os
import pathlib
import re
import sys
import tempfile
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(chemin, nom):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    sys.modules[nom] = mod
    return mod


def extraire(chemin, noms, espace):
    """Exécute, du module livré, les seules définitions demandées."""
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    gardes = []
    for n in arbre.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            gardes.append(n)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms:
            gardes.append(n)
        elif isinstance(n, ast.Assign) and any(
                isinstance(c, ast.Name) and c.id in noms for c in n.targets):
            gardes.append(n)
        elif isinstance(n, ast.Import) and any((a.asname or a.name) in noms for a in n.names):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


def _module(nom, **attrs):
    m = types.ModuleType(nom)
    m.__path__ = []
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[nom] = m
    return m


class _Journal:
    def info(self, *a, **k):
        pass
    warning = debug = error = info


def bloc_ui(obj):
    return "```ui\n" + json.dumps(obj, ensure_ascii=False) + "\n```"


print(f"\n═══ CHAQUE LIVRABLE SE PRÉSENTE PAR CE QU'IL CONTIENT — {RACINE}\n")

# ══════════════════════════════════════════════════════════════════════════
# 1. L'ATELIER RÉEL : SEULS LES DOCUMENTS PRODUITS SONT « TERMINÉS »
# ══════════════════════════════════════════════════════════════════════════
print("── 1. L'atelier : ce qui compte comme produit")
DOSSIER = tempfile.mkdtemp(prefix="atelier-banc-")
os.environ["DOCUMENTS_DIR"] = DOSSIER
_module("bureautique")
atelier = charger(BACKEND / "bureautique" / "atelier.py", "bureautique.atelier")
verifier("l'atelier lit DOCUMENTS_DIR", atelier.DOSSIER == DOSSIER, atelier.DOSSIER)

WORD = "HOn-pT0eHl9w3osDpqk8FKsH_iZGavzm"
EXCEL = "oapdJPe3_W2Y0YOayDpZkKH2hC2FIds5"
DSN = "m_9wdTIp_PMnKLoYinTifbESqvcma-Pf"
EXTRAIT_WORD = ("# Dossier projet paysager M. et Mme Camp\n## 1. Déroulé de chantier\n"
                "- Implantation et traçage\n- Palissade Tokyo 10,85 m\n- Dalle béton 6 m²\n"
                "## 2. Quantitatif des matériaux\n[tableau : 9 ligne(s)]\n## 3. Photomontages\n"
                "Vue terrasse, avant / après. " + "Détail " * 40)
fiches = {
    WORD: {"entete": {"titre": "Dossier projet paysager M. et Mme Camp", "format": "docx"},
           "elements": 26, "octets": 40435, "termine": 1000.0, "extrait": EXTRAIT_WORD, "pages_estimees": 3},
    EXCEL: {"entete": {"titre": "Inventaire — MR ET MME CAMP", "format": "xlsx"},
            "elements": 1, "octets": 5481, "termine": 999.0, "extrait": "[feuille : 5 ligne(s)]"},
    "devis-trame": {"entete": {"titre": "Devis Martin", "format": "docx"}, "elements": 0,
                    "octets": 30000, "termine": 998.0, "origine": "trame"},
    "repro": {"entete": {"titre": "Devis type refait", "format": "docx"}, "elements": 0,
              "octets": 31000, "termine": 997.0, "origine": "reproduction"},
    DSN: {"entete": {"titre": "DSN_082026", "format": "pdf"}, "elements": 0, "octets": 8824,
          "termine": 1001.0, "origine": "serveur"},
    "pj": {"entete": {"titre": "facture-fournisseur", "format": "pdf"}, "elements": 0,
           "octets": 2000, "termine": 1002.0, "origine": "piece_jointe"},
}
for jeton, f in fiches.items():
    atelier._ecrire_fiche(jeton, {**f, "proprietaire": "u1", "ouvert": 900.0, "fini": True,
                                  "fichier": f"{jeton}.{f['entete']['format']}"})
    pathlib.Path(atelier._chemin(jeton, f["entete"]["format"])).write_bytes(b"x" * 10)
atelier._ecrire_fiche("ouvert", {"entete": {"titre": "Brouillon", "format": "docx"}, "elements": 2,
                                 "proprietaire": "u1", "ouvert": 900.0, "fini": False})
atelier._ecrire_fiche("autre", {**fiches[WORD], "proprietaire": "u2", "ouvert": 900.0, "fini": True})

finis = atelier.termines("u1")
ids = [d["document_id"] for d in finis]
verifier("`termines` rend les documents PRODUITS : rédigé, trame, reproduction — et eux seuls",
         sorted(ids) == sorted([WORD, EXCEL, "devis-trame", "repro"]), ids)
verifier("un fichier LU sur le serveur (origine « serveur ») n'est plus un document produit",
         DSN not in ids, ids)
verifier("une pièce jointe reçue n'y est toujours pas ; un document d'une autre personne non plus",
         "pj" not in ids and "autre" not in ids)
verifier("les plus récents d'abord", ids[0] == WORD and ids[1] == EXCEL, ids)
d_word = next(d for d in finis if d["document_id"] == WORD)
verifier("chaque document porte `contenu`, le DÉBUT RÉEL du document (titres du Word), sur une ligne",
         d_word.get("contenu", "").startswith("# Dossier projet paysager M. et Mme Camp ## 1. Déroulé de chantier")
         and "\n" not in d_word["contenu"], d_word.get("contenu"))
verifier("… borné à 240 caractères, la coupe dite par « … »",
         len(d_word.get("contenu", "")) <= 241 and d_word.get("contenu", "").endswith("…"), len(d_word.get("contenu", "")))
verifier("le classeur de l'inventaire dit ce qu'il est : une feuille de N lignes",
         next(d for d in finis if d["document_id"] == EXCEL).get("contenu") == "[feuille : 5 ligne(s)]")
verifier("`produit()` : sans origine = rédigé ici ; « serveur », « piece_jointe », « depot » = reçu",
         atelier.produit({}) and atelier.produit({"origine": "trame"})
         and not atelier.produit({"origine": "serveur"}) and not atelier.produit({"origine": "piece_jointe"})
         and not atelier.produit({"origine": "depot"}))
verifier("le fichier lu sur le serveur RESTE téléchargeable par son jeton (seule la liste change)",
         atelier.chemin_fichier(DSN, "u1") is not None and atelier.chemin_fichier(DSN, "u2") is None)

# ══════════════════════════════════════════════════════════════════════════
# 2. LA RÉPONSE DE 11:31 FACE AU FILET DES LIVRABLES, ATELIER RÉEL
# ══════════════════════════════════════════════════════════════════════════
print("\n── 2. _livrables_a_l_ecran, exécuté sur la réponse de 11:31")
_module("visuels")
espace = {"logger": _Journal(), "AgentState": dict, "_tracer_filet": lambda *a, **k: None}
extraire(BACKEND / "agents" / "agent1.py",
         {"_re_livrables", "_BLOC_UI_RE", "_TYPES_LIVRABLE", "_reference_bloc", "_blocs_livrables",
          "_blocs_de", "fichiers_du_fil", "_plat_nom", "_designe_le_meme", "_meme_livrable",
          "_livrables_a_l_ecran", "_cartes_de_l_atelier", "_signature_bloc", "_blocs_garantis",
          "cles_images_du_fil", "_CLE_IMAGE_RE", "_re_images", "_image_connue"}, espace)
livrables, cartes_atelier, blocs_garantis = (espace["_livrables_a_l_ecran"], espace["_cartes_de_l_atelier"],
                                             espace["_blocs_garantis"])

cartes = cartes_atelier({"user_id": "u1"})
verifier("`_cartes_de_l_atelier` ne fabrique une carte que pour un document produit",
         {c["url"] for c in cartes} == {f"/api/documents/{j}" for j in (WORD, EXCEL, "devis-trame", "repro")},
         [c["url"] for c in cartes])

REPONSE_1131 = (
    "Le dossier complet pour M. et Mme Camp est prêt. Voici les livrables.\n\n"
    "Le dossier Word rassemble le déroulé de chantier dans l'ordre des travaux, le quantitatif des "
    "matériaux et les photomontages réalistes. L'inventaire Excel reprend le détail chiffré des "
    "fournitures.\n\n"
    + bloc_ui({"type": "fichier", "url": f"/api/documents/{WORD}",
               "nom": "Dossier projet paysager M. et Mme Camp.docx",
               "titre": "Dossier projet paysager M. et Mme Camp", "format": "docx", "octets": 40435})
    + "\n\n" + bloc_ui({"type": "fichier", "url": f"/api/documents/{EXCEL}", "nom": "Inventaire — MR ET MME CAMP.xlsx",
                        "titre": "Inventaire — MR ET MME CAMP", "format": "xlsx", "octets": 5481})
    + "\n\n" + bloc_ui({"type": "fichier", "url": f"/api/documents/{DSN}", "nom": "DSN_082026.pdf",
                        "titre": "DSN_082026", "format": "pdf", "octets": 8824})
    + "\n\n" + bloc_ui({"type": "quick_replies", "options": ["Ajuster le photomontage"]}))
r = livrables(REPONSE_1131, {"tool_results": [], "messages": [], "user_id": "u1"})
verifier("le PDF étranger (lu sur le serveur la veille) est EFFACÉ de la réponse",
         DSN not in r and "DSN_082026" not in r, r[-400:])
verifier("le Word et le classeur, produits, restent — une fois chacun",
         r.count(WORD) == 1 and r.count(EXCEL) == 1 and r.count('"type": "fichier"') == 2, r)
verifier("la prose et les suggestions ne bougent pas",
         r.startswith("Le dossier complet pour M. et Mme Camp est prêt.") and "quick_replies" in r)
# Mais un fichier du serveur MONTRÉ DANS CE FIL (carte garantie d'un `drive_ouvrir`)
# reste légitime au tour suivant : c'est le fil qui le connaît, pas l'atelier.
class _Msg:
    def __init__(self, content):
        self.content = content
        self.type = "ai"
fil = [_Msg("Voici le fichier.\n\n" + bloc_ui({"type": "fichier", "url": f"/api/documents/{DSN}",
                                                "nom": "DSN_082026.pdf", "titre": "DSN_082026", "format": "pdf"}))]
r2 = livrables("Le revoici.\n\n" + bloc_ui({"type": "fichier", "url": f"/api/documents/{DSN}", "nom": "DSN_082026.pdf",
                                             "titre": "DSN_082026", "format": "pdf"}),
               {"tool_results": [], "messages": fil, "user_id": "u1"})
verifier("un fichier ouvert DANS CE FIL peut être remontré (le fil prime, pas l'atelier)", DSN in r2, r2)

# ══════════════════════════════════════════════════════════════════════════
# 3. LA RECHERCHE WEB DIT CE QU'ELLE A LU, ET À QUOI ELLE A SERVI
# ══════════════════════════════════════════════════════════════════════════
print("\n── 3. chercher_web et le tableau fondu")
APPELS = []


async def _search(query, user_id, agent_id, max_results):
    APPELS.append(query)
    return {"success": True, "content": "…", "sources": ["https://a.fr/tokyo", "https://b.fr/cloture"],
            "resultats": [{"url": "https://a.fr/tokyo", "titre": "Clôture Tokyo",
                           "extrait": "Panneau Tokyo 180 × 180 cm, lames horizontales, pin autoclave"},
                          {"url": "https://b.fr/cloture", "titre": "", "extrait": "Clôtures bois — catalogue"}]}


async def _fetch(url, user_id, agent_id, reason=""):
    return {"success": True, "content": "Texte", "url": url}
_module("browser")
_module("browser.tools", web_search=_search, fetch_url=_fetch)
bsk = charger(BACKEND / "browser" / "skills.py", "browser_skills_double")
U = types.SimpleNamespace(id="u1", role="direction")
w = asyncio.run(bsk.chercher_web({"requete": "panneau Tokyo dimensions"}, U))
t = w["bloc_ui"]
verifier("le tableau garanti porte DEUX colonnes : l'adresse et ce qu'on y a lu",
         w["bloc_garanti"] is True and t["columns"] == ["Adresse consultée", "Ce qu'on y a lu"], t)
verifier("… avec, par adresse, le titre et les premiers mots de la page",
         t["rows"][0] == ["https://a.fr/tokyo", "Clôture Tokyo — Panneau Tokyo 180 × 180 cm, lames horizontales, pin autoclave"]
         and t["rows"][1] == ["https://b.fr/cloture", "Clôtures bois — catalogue"], t["rows"])
verifier("le titre du tableau dit ce qu'on a cherché", t["titre"] == "Recherche web — panneau Tokyo dimensions")
verifier("la consigne : dire en une phrase à quoi la recherche a servi et ce qu'on en retient",
         "à quoi cette recherche a servi" in w["a_faire"] and "ne le recopie pas" in w["a_faire"]
         and "n'a rien donné" in w["a_faire"], w.get("a_faire"))


async def _search_ancien(query, user_id, agent_id, max_results):
    return {"success": True, "content": "…", "sources": ["https://c.fr"]}
sys.modules["browser.tools"].web_search = _search_ancien
w2 = asyncio.run(bsk.chercher_web({"requete": "gazon King Park"}, U))
verifier("un conteneur qui ne détaille pas les pages : la seconde colonne reste VIDE, rien d'inventé",
         w2["bloc_ui"]["rows"] == [["https://c.fr", ""]], w2["bloc_ui"]["rows"])

outils = extraire(BACKEND / "browser" / "tools.py", {"_extrait"}, {})
verifier("`web_search` rend `resultats` (url, titre, extrait) par page consultée",
         '"resultats": [{"url": r["url"], "titre":' in (BACKEND / "browser" / "tools.py").read_text(encoding="utf-8"))
verifier("l'extrait d'une page : les premiers mots sur une ligne, coupe dite",
         outils["_extrait"]("Panneau\n\n  Tokyo   180 cm") == "Panneau Tokyo 180 cm"
         and outils["_extrait"]("mot " * 100).endswith("…") and len(outils["_extrait"]("mot " * 100)) <= 161)


def res_web(requete, lignes):
    return {"skill": "chercher_web", "ok": True,
            "resultat_masque": json.dumps({"requete": requete, "bloc_garanti": True,
                                           "bloc_ui": {"type": "table", "titre": f"Recherche web — {requete}",
                                                       "columns": ["Adresse consultée", "Ce qu'on y a lu"],
                                                       "rows": lignes}}, ensure_ascii=False)}
deux = [res_web("panneau Tokyo dimensions", [["https://a.fr/tokyo", "Clôture Tokyo — 180 × 180"]]),
        res_web("gazon King Park", [["https://d.fr/king-park", "King Park 40 mm"], ["https://a.fr/tokyo", "doublon"]])]
r = blocs_garantis("Voici le dossier.", {"tool_results": deux, "user_id": "u1"})
fondu = json.loads(re.search(r"```ui\n(.*?)\n```", r, re.S).group(1))
verifier("deux recherches → UN tableau à trois colonnes : la recherche, l'adresse, ce qu'on y a lu",
         r.count('"type": "table"') == 1 and fondu["columns"] == ["Recherche", "Adresse consultée", "Ce qu'on y a lu"], fondu)
verifier("… chaque ligne dit quelle recherche l'a consultée ; une adresse revue n'est pas répétée",
         fondu["rows"] == [["panneau Tokyo dimensions", "https://a.fr/tokyo", "Clôture Tokyo — 180 × 180"],
                           ["gazon King Park", "https://d.fr/king-park", "King Park 40 mm"]], fondu["rows"])
ancien = [{"skill": "chercher_web", "ok": True,
           "resultat_masque": json.dumps({"bloc_garanti": True, "bloc_ui": {"type": "table", "titre": "Recherche web — x",
                                                                            "columns": ["Adresse consultée"], "rows": [["https://x.fr"]]}})}] * 2
r = blocs_garantis("Voici.", {"tool_results": ancien, "user_id": "u1"})
fondu = json.loads(re.search(r"```ui\n(.*?)\n```", r, re.S).group(1))
verifier("des tableaux à l'ancienne forme (une colonne) se fondent sans casser",
         fondu["rows"] == [["x", "https://x.fr", ""]], fondu["rows"])

# ══════════════════════════════════════════════════════════════════════════
# 4. LA LECTURE PAR TYPE, IMAGES COMPRISES, SANS DÉPÔT
# ══════════════════════════════════════════════════════════════════════════
print("\n── 4. mail/pieces.lire_sans_deposer et analyser")
faux_parsers = types.ModuleType("ingestion.parsers")


class _NS(Exception):
    pass
faux_parsers.FichierNonSupporte = _NS
faux_parsers.lire_pdf = lambda b: "DEVIS n° 2026-041 — terrasse bois"
faux_parsers.lire_docx = lambda b: "TEXTE WORD"
faux_parsers.ocr_disponible = lambda: True
faux_parsers.ocr_image = lambda b: ""
faux_parsers._decoder = lambda b: b.decode("utf-8", "replace")
_module("ingestion")
sys.modules["ingestion.parsers"] = faux_parsers
_module("mail")
pieces = charger(BACKEND / "mail" / "pieces.py", "mail.pieces")
CONSIGNES = []


async def _vision(octets, mime, consigne):
    CONSIGNES.append(consigne)
    return "Photo d'un jardin clos avec une piscine, vue depuis la terrasse ; haie à droite."
pieces.decrire_image = _vision
JPEG = b"\xff\xd8\xff" + b"\x00" * 40
lu = asyncio.run(pieces.lire_sans_deposer("vue3.jpg", "image/jpeg", JPEG, consigne_vision=pieces.CONSIGNE_FICHIER))
verifier("une photo est DÉCRITE par la vision (l'OCR n'a rien lu), méthode dite, rien n'est déposé",
         "jardin clos" in lu["texte"] and lu["methode"] == "description par la vision" and lu["tronque"] is False, lu)
verifier("… avec la consigne du CLASSEMENT (photo, plan, cotes), pas celle d'un mail",
         CONSIGNES[-1] == pieces.CONSIGNE_FICHIER and "dossier de l'entreprise" in CONSIGNES[-1]
         and "cotes" in CONSIGNES[-1])
lu = asyncio.run(pieces.lire_sans_deposer("devis.pdf", "application/pdf", b"%PDF-1.4"))
verifier("un PDF passe par le lecteur des pièces (OCR si scanné)",
         lu["texte"].startswith("DEVIS n° 2026-041") and "PDF" in lu["methode"])
verifier("vide et trop lourd se DISENT, sans lever",
         asyncio.run(pieces.lire_sans_deposer("x.pdf", None, b""))["methode"] == "fichier vide"
         and "trop lourd" in asyncio.run(pieces.lire_sans_deposer("x.pdf", None, b"x" * (pieces.MAX_OCTETS_PIECE + 1)))["methode"])
pieces.MAX_TEXTE_PIECE = 4
lu = asyncio.run(pieces.lire_sans_deposer("long.docx", None, b"PK"))
verifier("un texte au-delà du plafond est coupé et la coupe est dite", lu["tronque"] is True and lu["texte"] == "TEXT", lu)
pieces.MAX_TEXTE_PIECE = 6000

# `analyser` (les pièces d'un mail) passe par la même lecture et dépose encore la vignette DWG.
pieces.texte_de = lambda nom, mime, brut: {"texte": "", "methode": "vignette du DWG", "vignette": b"PNG-VIGNETTE",
                                           "vignette_mime": "image/png", "complement": "Plan AutoCAD 2018."}
deposes = []
_module("visuels.depot", deposer_octets=lambda octets, mime="image/png": deposes.append((octets, mime)) or "cle-vig")
sys.modules["bureautique.atelier"].deposer_fichier = lambda nom, octets, proprietaire, origine="depot": "jeton-dwg"
f = asyncio.run(pieces.analyser("plan.dwg", None, b"AC1032" + b"\x00" * 30, "u1"))
verifier("`analyser` : la vignette du DWG est déposée et montrée, le plan décrit par la vision, le complément en tête",
         f.get("vignette", {}).get("cle") == "cle-vig" and deposes[-1] == (b"PNG-VIGNETTE", "image/png")
         and f["texte"].startswith("Plan AutoCAD 2018.") and "jardin clos" in f["texte"] and f["lisible"] is True
         and f["bloc"]["type"] == "fichier", f)

# ══════════════════════════════════════════════════════════════════════════
# 5. LA SOURCE DU CLIENT, PUIS L'INVENTAIRE
# ══════════════════════════════════════════════════════════════════════════
print("\n── 5. classement/source.lire_fichier, puis l'inventaire")
LECTURES = []


async def _lire_double(nom, mime, brut, consigne_vision=None, consigne_ocr=None):
    LECTURES.append((nom, mime, len(brut), consigne_vision))
    return {"texte": "Photo du jardin.", "methode": "description par la vision", "tronque": False}
pieces.lire_sans_deposer = _lire_double
_module("skills")
_module("skills.outils", _identite=lambda user: "id:" + str(user.id), _perimetres=lambda user: [])
_module("outils")
DRIVE = (BACKEND / "outils" / "drive.py").exists()
if DRIVE:
    async def _service(identite):
        return "svc:" + identite

    async def _binaire(fichier, service, nom, mime):
        return b"\xff\xd8" + b"\x00" * 10, fichier["name"], "image/jpeg"
    _module("outils.drive", _service=_service, _binaire=_binaire)
    REF = {"id": "f1", "name": "vue3.jpg", "mimeType": "image/jpeg", "size": "12"}
else:
    async def _octets(chemin):
        return b"\xff\xd8" + b"\x00" * 10, "vue3.jpg", "image/jpeg"
    _module("outils.nas", octets=_octets)
    REF = "/home/Drive/CAMP/vue3.jpg"
_module("classement")
source = charger(BACKEND / "classement" / "source.py", "classement.source")
lu = asyncio.run(source.lire_fichier(REF, U))
verifier("`lire_fichier` rend {texte, methode} : le binaire du stockage part au lecteur par type, consigne du classement",
         lu.get("texte") == "Photo du jardin." and lu.get("methode") == "description par la vision"
         and LECTURES[-1][:3] == ("vue3.jpg", "image/jpeg", 12) and LECTURES[-1][3] == pieces.CONSIGNE_FICHIER, (lu, LECTURES))
if DRIVE:
    async def _binaire_refus(fichier, service, nom, mime):
        raise RuntimeError("« Formulaire » est un élément Google qui ne se télécharge pas.")
    sys.modules["outils.drive"]._binaire = _binaire_refus
    try:
        asyncio.run(source.lire_fichier({"name": "Formulaire", "mimeType": "application/vnd.google-apps.form"}, U))
        verifier("un refus du stockage remonte tel quel (l'inventaire en fait la raison)", False)
    except RuntimeError as e:
        verifier("un refus du stockage remonte tel quel (l'inventaire en fait la raison)", "ne se télécharge pas" in str(e))
    trop = asyncio.run(source.lire_fichier({"name": "gros.pdf", "mimeType": "application/pdf",
                                            "size": str(pieces.MAX_OCTETS_PIECE + 1)}, U))
    verifier("un fichier trop lourd n'est pas téléchargé : la taille est dite", "trop lourd" in trop["methode"], trop)

# L'inventaire, avec une source qui décrit les photos.
sys.modules["skills.erreurs"] = types.ModuleType("skills.erreurs")


class SkillError(Exception):
    pass
sys.modules["skills.erreurs"].SkillError = SkillError
reg = types.ModuleType("skills.registre")


class Declaration:
    def __init__(self, **kw):
        self.__dict__.update(kw)
reg.Declaration = Declaration
sys.modules["skills.registre"] = reg
FICHIERS = [{"nom": "Plan coté.pdf", "ref": "r1", "octets": 120_000, "type": ""},
            {"nom": "vue3.jpg", "ref": "r2", "octets": 900_000, "type": ""},
            {"nom": "vue4.jpg", "ref": "r3", "octets": 800_000, "type": ""}]
LUS = {"r1": {"texte": "Plan de masse coté, parcelle 320 m², piscine 8 × 4.", "methode": "texte du PDF (OCR si scanné)"},
       "r2": {"texte": "Photo de la terrasse et de la piscine, haie à droite.", "methode": "description par la vision"},
       "r3": ""}
src2 = types.ModuleType("classement.source")
src2.NOM_STOCKAGE = "Drive d'essai"


async def _fichiers(dossier, user):
    return "Drive/CLIENTS/CAMP", list(FICHIERS)


async def _lire(ref, user):
    return LUS[ref]
src2.fichiers_du_dossier, src2.lire_fichier = _fichiers, _lire
sys.modules["classement.source"] = src2
_module("langchain_core")
_module("langchain_core.messages", HumanMessage=lambda content: ("human", content),
        SystemMessage=lambda content: ("system", content))


class _Modele:
    async def ainvoke(self, messages):
        return types.SimpleNamespace(content="Décrit : " + messages[1][1][:20])
_module("llm")
_module("llm.router", LLMTier=types.SimpleNamespace(LIGHT="light"), get_llm=lambda tier: _Modele())
ATELIER = {}
at = sys.modules["bureautique.atelier"]
at.ouvrir = lambda entete, proprio: ATELIER.update({"entete": entete}) or "J1"
at.ajouter = lambda jeton, elements, proprio: ATELIER.update({"elements": elements})
at.terminer = lambda jeton, proprio: {"octets": 4321}
inv = charger(BACKEND / "skills" / "inventaire.py", "inventaire_double")
r = asyncio.run(inv.inventaire_dossier({"dossier": "CAMP"}, U))
lignes = ATELIER["elements"][0]["lignes"]
verifier("une PHOTO est lue : « lu — description par la vision » dans la colonne Lecture, décrite en une phrase",
         lignes[1][0] == "vue3.jpg" and lignes[1][3] == "lu — description par la vision"
         and lignes[1][4].startswith("Décrit : Photo de la terrasse"), lignes[1])
verifier("un PDF : « lu — texte du PDF (OCR si scanné) »", lignes[0][3] == "lu — texte du PDF (OCR si scanné)", lignes[0])
verifier("une chaîne nue reste acceptée (source d'avant) ; vide = « sans texte lisible »",
         lignes[2][3] == "sans texte lisible" and r["lus"] == 2, lignes[2])
verifier("la démarche dit la méthode de chaque lecture",
         any("vue3.jpg » : lu (" in d and "description par la vision" in d for d in r["demarche"]), r["demarche"])
verifier("la consigne dit ce qu'EST le classeur : la liste des fichiers, jamais un quantitatif ni un livrable d'office",
         "LISTE DES FICHIERS" in r["a_faire"] and "quantitatif" in r["a_faire"] and "livrables" in r["a_faire"], r["a_faire"])

# ══════════════════════════════════════════════════════════════════════════
# 6. LE PROMPT ET LA CONSIGNE DE L'ATELIER
# ══════════════════════════════════════════════════════════════════════════
print("\n── 6. Ce que le modèle lit")
ag1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("règle du prompt : CHAQUE LIVRABLE SE PRÉSENTE PAR CE QU'IL CONTIENT",
         "CHAQUE LIVRABLE SE PRÉSENTE PAR CE QU'IL CONTIENT." in ag1
         and "Un inventaire de fichiers n'est pas un quantitatif" in ag1
         and "Une recherche web faite en chemin se dit en une phrase" in ag1)
verifier("la liste des documents terminés explique `contenu` et dit que l'atelier est par personne",
         "`contenu` est le DÉBUT " in ag1 and "toutes conversations confondues" in ag1)
verifier("le tableau web fondu garde la recherche et l'extrait",
         '"columns": ["Recherche", "Adresse consultée", "Ce qu\'on y a lu"]' in ag1)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
