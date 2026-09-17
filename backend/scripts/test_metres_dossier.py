"""
Banc des MÉTRÉS D'UN DOSSIER DU SERVEUR (17/09).

Le relevé : « fais les métrés des lots 11 et 12 à partir du dossier souche
"construction 29 lgts…" » → zéro ligne. Le dossier n'était jamais ouvert, le
DPGF était confié à un modèle sous une règle de citation mot à mot, une ligne
fausse faisait perdre les justes, et le tableau des surfaces du plan — la
donnée exacte — était illisible pour cette règle.

Tout est EXÉCUTÉ, sans base Postgres ni réseau ni modèle : les textes imitent
la forme exacte relevée en production (aucune donnée de client).

    python backend/scripts/test_metres_dossier.py backend
"""
import asyncio
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

BACKEND = Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(BACKEND))
TEMP = tempfile.TemporaryDirectory(prefix="banc-metres-")
os.environ["DOCUMENTS_DIR"] = TEMP.name + "/documents"
ECHECS = []


def verifier(nom, condition, detail=""):
    print(("  ✓ " if condition else "  ✗ ") + nom + (f"  → {detail}" if detail and not condition else ""))
    if not condition:
        ECHECS.append(nom)


# ─── 1. Un DPGF se lit par le code ──────────────────────────────────────────
print("1. Le tableau chiffré (DPGF) est lu par le code")
from skills.tableaux_quantites import famille_de_piece, lire, lire_surfaces

DPGF = "\n".join([
    'Feuille DPGF — ligne 3 : B3="N°" | C3="Désignation" | D3="U" | E3="Quantité" | F3="P.U." | G3="Total"',
    'Feuille DPGF — ligne 5 : B5="3.1" | C5="Logements"',
    'Feuille DPGF — ligne 6 : B6="3.1.1" | C6="Isolant phonique sous carrelage" | D6="m2" | E6="453"',
    'Feuille DPGF — ligne 7 : B7="3.1.2" | C7="Plinthes assorties" | D7="ml" | E7="1 250,5"',
    'Feuille DPGF — ligne 8 : B8="3.1.3" | C8="Carrelage des halls" | D8="m2"',
    'Feuille DPGF — ligne 9 : C9="Sous-total logements" | G9="[FORMULE SANS VALEUR CALCULÉE : =SUM(G6:G8)]"',
    'Feuille DPGF — ligne 10 : B10="3.1.4" | C10="Nettoyage" | D10="Ft"',
])
t = lire({"id": "s1", "nom": "OPERATION-DCE-DPGF-LOT 11 CARRELAGE FAIENCE.xlsx", "contenu": DPGF})
verifier("l'en-tête est reconnu (unité + quantité)", t["entete"] is True)
verifier("deux lignes chiffrées, exactes", [l["quantite"] for l in t["lignes"]] == ["453", "1250.5"], str([l["quantite"] for l in t["lignes"]]))
verifier("l'unité est normalisée (m2 → m², ml)", [l["unite"] for l in t["lignes"]] == ["m²", "ml"])
verifier("le lot vient du nom du fichier", t["lignes"][0]["lot"].startswith("Lot 11"), t["lignes"][0]["lot"])
verifier("l'intertitre situe le poste", t["lignes"][0]["local"] == "Logements", t["lignes"][0]["local"])
verifier("la preuve est la CELLULE", t["lignes"][0]["operandes"][0]["preuve"] == "s1:DPGF!E6", t["lignes"][0]["operandes"][0]["preuve"])
verifier("un poste sans quantité est « à métrer », pas inventé", [a["poste"] for a in t["a_metrer"]] == ["3.1.3 Carrelage des halls", "3.1.4 Nettoyage"], str(t["a_metrer"]))
verifier("un sous-total n'est pas un intertitre", all(a["local"] == "Logements" for a in t["a_metrer"]))
sans = lire({"id": "s2", "nom": "notes.xlsx", "contenu": 'Feuille A — ligne 1 : A1="Bonjour" | B1="12"'})
verifier("sans en-tête reconnaissable : le classeur repart vers la lecture habituelle", sans["entete"] is False and not sans["lignes"])
verifier("un PDF n'est pas pris pour un classeur", lire({"id": "s3", "nom": "x.pdf", "contenu": "=== Page 1 ===\n453 m2"})["entete"] is False)

# ─── 2. Le tableau des surfaces d'un plan ───────────────────────────────────
print("2. Le tableau des surfaces d'un plan est lu par le code, somme contrôlée")
PLAN = "\n".join([
    "=== Page 1 ===", "[LECTURE VISUELLE REQUISE : relations graphiques non représentées par le texte]", "SURFACES", "1:1",
    "001", "001", "001", "T2", "T2", "T2", "WC", "CHAMBRE 1", "SEJOUR/CUISINE", "2,00", "12,50", "25,50", "40,00 m²",
    "102", "102", "T1", "T1", "SdE", "SEJOUR CUISINE", "4,00", "26,00", "30,00 m²",
    "203", "203", "T3", "T3", "WC", "CHAMBRE 2", "2,00", "11,00", "99,00 m²",          # somme fausse : colonnes mêlées
    "104", "LOGGIA", "6,29 m²", "6,28",                                                   # total AVANT la valeur
    "105", "LOGGIA", "5,00", "5,00 m²",
    "1 643,60 m²", "TOTAL SHAB",
])
s = lire_surfaces({"id": "p1", "nom": "12 SURFACES.pdf", "contenu": PLAN})
verifier("trois blocs gardés (deux logements, une loggia)", s["blocs"] == 3, str(s["blocs"]))
verifier("le bloc dont la somme ne retombe pas sur le total est REJETÉ", s["rejetes"] == 1 and not any(p["logement"] == "203" for p in s["pieces"]))
verifier("chaque pièce garde sa surface exacte", [(p["piece"], p["surface"]) for p in s["pieces"][:3]] == [("WC", Decimal("2.00")), ("CHAMBRE 1", Decimal("12.50")), ("SEJOUR/CUISINE", Decimal("25.50"))])
verifier("le niveau suit la numérotation (0xx, 1xx)", {p["logement"]: p["niveau"] for p in s["pieces"]} == {"001": "RDC", "102": "R+1", "105": "R+1"})
verifier("la citation dit le contrôle par la somme", "somme des 3 pièces (vérifiée)" in s["pieces"][0]["citation"])
verifier("le total général n'est pas pris pour un logement", all(p["logement"] != "TOTAL SHAB" for p in s["pieces"]))
verifier("un plan coté ordinaire ne rend rien", lire_surfaces({"id": "p2", "nom": "RDC.pdf", "contenu": "=== Page 1 ===\n2,40\n2,40\n5,00\n0,2 m2\n0,2 m2"})["blocs"] == 0)
verifier("les pièces se regroupent par type", {famille_de_piece(x) for x in ("CHAMBRE 2", "Chambre", "CHAMBRE 1")} == {"CHAMBRE"} and famille_de_piece("SEJOUR CUISINE") == famille_de_piece("SEJOUR / CUISINE") == "SEJOUR/CUISINE" and famille_de_piece("DGT 2") == "DEGAGEMENT")

# ─── 3. Le relevé par modèle : souple sur le cadre, strict sur le chiffre ───
print("3. Une ligne du modèle : souple sur le cadre, stricte sur le chiffre")
import skills.quantitatifs as q

preuves = {"c1:q1": 'Sol de la cuisine : 12,5 m2 de carrelage 30x30\nB7="Plinthes" | D7="ml" | E7="48"', "c1:1": "Le carrelage est posé dans les cuisines."}
ligne = {"lot": "Lot 11", "poste": "Carrelage cuisine", "unite": "m2", "formule": "c1",
         "operandes": [{"valeur": "12.5", "unite": "M2", "preuve": "c1:q1", "citation": "Sol de la  cuisine : 12,5 m² de carrelage"}],
         "affectation": {"preuve": "c1:1", "citation": "Le carrelage est posé dans les cuisines."}}
r = q._verifier_ligne(dict(ligne), preuves)
verifier("sans niveau ni local, la ligne passe (« Non précisé »)", r["niveau"] == "Non précisé" and r["local"] == "Non précisé" and r["quantite"] == "12.5")
verifier("m2/M2 valent m², les espaces de la citation ne comptent pas", r["unite"] == "m²")
faux = dict(ligne, operandes=[{"valeur": "99", "unite": "m²", "preuve": "c1:q1", "citation": "Sol de la cuisine : 12,5 m2"}])
try:
    q._verifier_ligne(faux, preuves); verifier("une valeur absente de la citation est refusée", False)
except ValueError:
    verifier("une valeur absente de la citation est refusée", True)
invente = dict(ligne, operandes=[{"valeur": "12.5", "unite": "m²", "preuve": "c1:q1", "citation": "Sol du salon : 12,5 m²"}])
try:
    q._verifier_ligne(invente, preuves); verifier("une citation absente de la pièce est refusée", False)
except ValueError:
    verifier("une citation absente de la pièce est refusée", True)

# ─── 4. Le dossier du serveur : ce qu'on charge, ce qu'on écarte ────────────
print("4. Le dossier nommé : pièces utiles au travail, le reste DIT")
from skills.documents_dossier import choisir_fichiers, dossier_cite, lots_du_metier, lots_vises

demande = "fais les métrés des lots 11 et 12 à partir du dossier souche « construction 29 lgts sociaux 18-09-2026 »"
verifier("le dossier cité entre guillemets est reconnu", dossier_cite(demande) == "construction 29 lgts sociaux 18-09-2026", str(dossier_cite(demande)))
verifier("l'historique ne rouvre pas un dossier d'hier", dossier_cite("refais-le\nDEMANDES UTILISATEUR ANTÉRIEURES\n« ancien dossier de la veille »") is None)
verifier("les lots nommés : 11 et 12, ni 29, ni 18, ni 9", lots_vises(demande) == {11, 12}, str(lots_vises(demande)))
verifier("« lot 11 du dossier 29 lgts 18-09-2026 » ne vise que le 11", lots_vises("lot 11 du dossier 29 lgts 18-09-2026") == {11})
verifier("« lots 3, 4 et 12 » vise les trois", lots_vises("les lots 3, 4 et 12") == {3, 4, 12})


def f(nom, dossier="1 - DCE", octets=1000, modifie=100):
    return {"nom": nom, "ref": "/srv/" + dossier + "/" + nom, "octets": octets, "dossier": dossier, "modifie": modifie}


ARBRE = [
    f("OP-DCE-DPGF-LOT 11 CARRELAGE FAIENCE.xlsx", modifie=200), f("OP-DCE-DPGF-LOT 11 CARRELAGE FAIENCE.xlsx", "1 - DCE/02-DPGF", modifie=100),
    f("OP-DCE-DPGF-LOT 12 SOLS SOUPLES.xlsx"), f("OP-DCE-CCTP-LOT 11 CARRELAGE FAIENCE.pdf"), f("OP-DCE-CCTP-LOT 12 SOLS SOUPLES.pdf"),
    f("OP-DCE-CCTP-LOT 00 DISPOSITIONS COMMUNES.pdf"), f("OP-DCE-CCTP-LOT 13 PEINTURE.pdf"), f("OP-DCE-DPGF-LOT 02 GROS OEUVRE.xlsx"),
    f("NATURE DES SOLS - RDC.pdf", "1 - DCE/03-PIECES GRAPHIQUES/01-PLANS ARCHITECTE"), f("NATURE DES PLAFONDS - RDC.pdf", "1 - DCE/03-PIECES GRAPHIQUES/01-PLANS ARCHITECTE"),
    f("12 SURFACES.pdf", "1 - DCE/03-PIECES GRAPHIQUES/01-PLANS ARCHITECTE"), f("02-1 RDC.pdf", "1 - DCE/03-PIECES GRAPHIQUES/01-PLANS ARCHITECTE"),
    f("09 FAÇADES OUEST et NORD.pdf", "1 - DCE/03-PIECES GRAPHIQUES/01-PLANS ARCHITECTE"), f("02-1 RDC.dwg", "1 - DCE/03-PIECES GRAPHIQUES/DWG"),
    f("DCE complet.zip", octets=600_000_000), f("2-2026-71RCv2.pdf", "1 - DCE/01-PIECES ADMINISTRATIVES"), f("4-2026-71CCAPv2.pdf", "1 - DCE/01-PIECES ADMINISTRATIVES"),
    f("3-2026-71CADRE_MEMOIRE_TECHNIQUE.docx", "1 - DCE/01-PIECES ADMINISTRATIVES"), f("G2 PRO - étude.pdf", "1 - DCE/07-ANNEXES/ETUDES GEOTECHNIQUES"),
    f("MEMOIRE Complet Vierge.docx", "2 - Etudes/3- Mémoire Technique"), f("METRE XXX.xlsx", "2 - Etudes/2 - métrés"), f("vide.pdf", octets=0),
]
retenus, ecartes = choisir_fichiers(ARBRE, {11, 12}, set(), "quantitatif")
noms = [x["nom"] for x in retenus]
verifier("métré : DPGF et CCTP des lots visés, plans de sols, surfaces, plan de niveau", set(noms) == {
    "OP-DCE-DPGF-LOT 11 CARRELAGE FAIENCE.xlsx", "OP-DCE-DPGF-LOT 12 SOLS SOUPLES.xlsx", "OP-DCE-CCTP-LOT 11 CARRELAGE FAIENCE.pdf",
    "OP-DCE-CCTP-LOT 12 SOLS SOUPLES.pdf", "NATURE DES SOLS - RDC.pdf", "12 SURFACES.pdf", "02-1 RDC.pdf"}, str(noms))
verifier("les pièces des lots passent en tête", noms[0].startswith("OP-DCE-DPGF-LOT 11") and "LOT" in noms[3])
verifier("deux fichiers du même nom : UN seul, le plus récent", sum(n == "OP-DCE-DPGF-LOT 11 CARRELAGE FAIENCE.xlsx" for n in noms) == 1 and next(x for x in retenus if "LOT 11" in x["nom"] and "DPGF" in x["nom"])["modifie"] == 200)
verifier("ce qui est écarté est DIT, par raison", {"autre lot", "pièce administrative (inutile à un métré)", "plan ou pièce d’un autre corps d’état"} <= set(ecartes) and any("doublon" in k for k in ecartes) and any("format non lu" in k for k in ecartes), str(ecartes))
verifier("le gabarit vierge de la maison n'est pas une source de quantités", "METRE XXX.xlsx" not in noms and any("gabarit" in k for k in ecartes))
redac, ecartes_doc = choisir_fichiers(ARBRE, {11, 12}, set(), "document")
noms_doc = {x["nom"] for x in redac}
verifier("rédaction : le règlement, le CCAP, le cadre et la trame de la maison entrent", {"2-2026-71RCv2.pdf", "4-2026-71CCAPv2.pdf", "3-2026-71CADRE_MEMOIRE_TECHNIQUE.docx", "MEMOIRE Complet Vierge.docx"} <= noms_doc, str(noms_doc))
verifier("rédaction : ni façades ni plan de niveau, et c'est dit", "02-1 RDC.pdf" not in noms_doc and "09 FAÇADES OUEST et NORD.pdf" not in noms_doc and any("plan graphique" in k for k in ecartes_doc))
deja, e2 = choisir_fichiers(ARBRE, {11, 12}, {"op-dce-dpgf-lot 12 sols souples.xlsx"}, "quantitatif")
verifier("une pièce déjà jointe à la conversation n'est pas rechargée", all("LOT 12 SOLS" not in x["nom"] or "CCTP" in x["nom"] for x in deja) and "déjà dans le travail" in e2)
tout, e3 = choisir_fichiers(ARBRE, {11, 12}, set(), "quantitatif", True)
verifier("« tout le dossier » lève le tri (seuls format et doublons jouent)", "OP-DCE-CCTP-LOT 13 PEINTURE.pdf" in {x["nom"] for x in tout} and "autre lot" not in e3)
verifier("sans lot nommé : les lots du métier de la maison", lots_du_metier(ARBRE) == {11, 12}, str(lots_du_metier(ARBRE)))

# ─── 5. Les surfaces deviennent des métrés ──────────────────────────────────
print("5. Les surfaces des pièces sont attribuées aux postes d'après les clauses « Localisation »")
from ressources import dossiers

etapes = {}
dossiers.etape = lambda uid, fil, tache, cle, valeur=None: (etapes.__setitem__((tache, cle), valeur) if valeur is not None else None) or etapes.get((tache, cle))
appels = []
CCTP12 = "\n".join(["3.3 REVETEMENT DE SOL PVC DANS LOGEMENT", "-", "Fourniture et pose collée de revêtement de sol PVC acoustique : ............ m2",
                    "Localisation : Suivant plans, sols de toutes les pièces des logements hormis", "pièces humides revêtues en carrelage.",
                    "3.4 BARRES DE SEUIL", "-", "Fourniture de barres de seuil ............ ml", "Localisation : Suivant plans, au droit des changements de revêtements."])
CCTP11 = "\n".join(["3.6.1 Carreaux grès", "-", "Fourniture et pose de carreaux ............ m2", "Localisation : Suivant plans, pour l'ensemble des SDE et WC des logements à RDC."])
clauses = q.clauses_de_localisation("c12:1", CCTP12)
verifier("les clauses « Localisation » sont relevées avec leur article", len(clauses) == 2 and clauses[0]["article"].startswith("3.3 REVETEMENT") and "hormis" in clauses[0]["citation"] and "3.4" not in clauses[0]["citation"], str(clauses)[:300])


async def faux_json(consigne, donnees, verif=None, **k):
    appels.append(donnees)
    pvc = next(c["n"] for c in donnees["clauses"] if "hormis" in c["localisation"]); carrelage = next(c["n"] for c in donnees["clauses"] if "SDE et WC" in c["localisation"])
    ip = {x["poste"]: x["n"] for x in donnees["postes"]}
    r = {"affectations": [{"poste": ip["2.1 Revêtement PVC U2SP3"], "clause": pvc, "familles": ["CHAMBRE", "SEJOUR/CUISINE", "WC", "LOGGIA"], "niveaux": [], "partiel": False},
                          {"poste": ip["2.1 Revêtement PVC U2SP3"], "clause": pvc, "familles": ["CHAMBRE"], "niveaux": [], "partiel": False},
                          {"poste": ip["3.6.1 Carreaux grès"], "clause": carrelage, "familles": ["WC", "SDE"], "niveaux": ["RDC"], "partiel": False}],
         "sans_surface": []}
    if verif:
        verif(r)
    return r

q._json = faux_json
a_metrer = [{"lot": "Lot 12 — SOLS SOUPLES", "poste": "2.1 Revêtement PVC U2SP3", "unite": "m²", "local": "Logements"},
            {"lot": "Lot 12 — SOLS SOUPLES", "poste": "2.4 Barres de seuil", "unite": "ml", "local": "Logements"},
            {"lot": "Lot 11 — CARRELAGE", "poste": "3.10.5 Paillasses de douche", "unite": "m²", "local": ""}]
chiffrees = [{"lot": "Lot 11 — CARRELAGE", "poste": "3.6.1 Carreaux grès", "unite": "m²", "quantite": "5", "local": ""}]
preuves5 = {"c12:1": CCTP12, "c11:1": CCTP11, "c11:q1": CCTP11}
noms5 = {"c12": "OP-CCTP-LOT 12 SOLS SOUPLES.pdf", "c11": "OP-CCTP-LOT 11 CARRELAGE.pdf"}
plans5 = [{"id": "p1", "nom": "12 SURFACES.pdf"}]
lignes, reserves, metres, controle = asyncio.run(q._affecter_surfaces("u", "f", "t", demande, s["pieces"], plans5, a_metrer, chiffrees, [], preuves5, noms5))
verifier("le modèle reçoit les postes en m² (pas les ml, pas les ouvrages ponctuels) et les clauses, jamais une surface",
         len(appels) == 1 and sorted(x["poste"] for x in appels[0]["postes"]) == ["2.1 Revêtement PVC U2SP3", "3.6.1 Carreaux grès"] and len(appels[0]["clauses"]) == 3 and "surface" not in str(appels[0]["familles"]))
verifier("une pièce n'entre qu'une fois dans un poste, à sa surface exacte", sorted(l["quantite"] for l in lignes) == ["12.50", "25.50", "26.00"], str([(l["local"], l["quantite"]) for l in lignes]))
verifier("une pièce NOMMÉE par le lot carrelage ne revient pas par « toutes les pièces hormis… »", not any("WC" in l["local"] for l in lignes))
verifier("une loggia n'est pas une « pièce du logement » : écartée si la clause ne la nomme pas", not any("LOGGIA" in l["local"] for l in lignes))
verifier("chaque ligne cite le plan ET la clause du CCTP (recopiée par le serveur)", all(l["operandes"][0]["preuve"].startswith("p1:surfaces!") and "Localisation" in l["affectation"]["citation"] and l["affectation"]["preuve"] == "c12:1" for l in lignes))
verifier("le local nomme le logement et la pièce, le niveau suit", any(l["local"].startswith("Logement 001 (T2) — ") and l["niveau"] == "RDC" for l in lignes))
verifier("le poste métré quitte la liste « à métrer »", metres == {("Lot 12 — SOLS SOUPLES", "2.1 Revêtement PVC U2SP3")})
verifier("un poste DÉJÀ chiffré n'est pas doublé : il est contrôlé (DPGF, relevé, écart), au niveau dit par la clause", len(controle) == 1 and controle[0][2:5] == [5.0, 2.0, -3.0], str(controle)[:200])
verifier("les réserves disent : habitable, clauses, contrôle du DPGF", any("HABITABLES" in x for x in reserves) and any("NATURE DES SOLS" in x for x in reserves) and any("Contrôle du DPGF" in x for x in reserves))
asyncio.run(q._affecter_surfaces("u", "f", "t", demande, s["pieces"], plans5, a_metrer, chiffrees, [], preuves5, noms5))
verifier("l'affectation est une étape acquise : pas de second appel à la reprise", len(appels) == 1)
l0, r0, m0, c0 = asyncio.run(q._affecter_surfaces("u", "f", "t2", demande, s["pieces"], plans5, [a_metrer[1]], [], [], preuves5, noms5))
verifier("sans poste en m² : aucune ligne, aucun appel, les surfaces restent livrées", not l0 and len(appels) == 1 and any("sans affectation" in x for x in r0))
l1, r1_, m1, c1 = asyncio.run(q._affecter_surfaces("u", "f", "t3", demande, s["pieces"], plans5, a_metrer, [], [], {}, noms5))
verifier("sans clause de localisation : aucune ligne, et c'est dit", not l1 and any("Aucune clause" in x for x in r1_))

# ─── 6. Le chargement du dossier et la file ─────────────────────────────────
print("6. Le dossier se charge une fois, se suit à l'écran, et la file ne le perd pas")
import importlib
import json as json_mod
import types

importlib.reload(dossiers)                      # la vraie base SQLite, dans le dossier temporaire
import skills.documents_dossier as dd
import ressources.documents_file as df

dd.dossiers = dossiers; df.dossiers = dossiers
uid, fil = dossiers.identite("00000000-0000-0000-0000-000000000001", "fil-metres")
listages = []


async def faux_arbre(dossier, user, **k):
    listages.append(dossier)
    if "introuvable" in dossier:
        raise ValueError("ce dossier n'existe pas sur le serveur")
    return "/srv/AO/" + dossier, ARBRE, False

source_mod = types.ModuleType("classement.source"); source_mod.arbre_du_dossier = faux_arbre; source_mod.METIERS_DE_LA_MAISON = ("carrelage", "sols souples")
sys.modules.setdefault("classement", types.ModuleType("classement")); sys.modules["classement.source"] = source_mod
lecteur = types.ModuleType("security.lecteur")
import contextlib
lecteur.au_nom_de = lambda user: contextlib.nullcontext()
sys.modules["security.lecteur"] = lecteur
suivis = []


async def faux_ajouter(data, user):
    nom = data["reference"].rsplit("/", 1)[-1]
    if nom.startswith("02-1"):
        raise ValueError("PDF illisible")
    x = dossiers.etape(uid, fil, "dossier", "chargement"); suivis.append((x["charges"], x["a_charger"], x["en_cours"]))
    ident = dossiers.enregistrer(uid, fil, nom, "contenu de " + nom, data["reference"], "sha-" + nom)
    return {"source": ident, "nom": nom}

dd.ajouter = faux_ajouter
user = types.SimpleNamespace(id=uid, email="personne@exemple-sols.fr", role="direction")
r1 = asyncio.run(dd.dossier_du_travail(uid, fil, {}, user, demande, "quantitatif"))
verifier("le dossier cité est ouvert et ses pièces utiles deviennent des sources", r1 and len(r1["ajoutes"]) == 6 and r1["lots"] == [11, 12] and r1["vus"] == len(ARBRE), str(r1)[:300])
verifier("un fichier illisible est DIT, il n'arrête pas les autres", any("02-1 RDC.pdf" in x for x in r1["ignores"]))
verifier("l'écran suit l'ouverture (n/N pièces), puis la dit finie", suivis and suivis[0][1] == 7 and suivis[0][2] is True and dossiers.etape(uid, fil, "dossier", "chargement")["en_cours"] is False, str(suivis[:2]))
r2 = asyncio.run(dd.dossier_du_travail(uid, fil, {}, user, demande, "quantitatif"))
verifier("au 2ᵉ essai rien n'est rechargé, et le compte rendu garde les 6 pièces", len(r2["ajoutes"]) == 6 and len(dossiers.manifeste(uid, fil)) == 6, str(len(r2["ajoutes"])))
r3 = asyncio.run(dd.dossier_du_travail(uid, fil, {"dossier": "dossier introuvable"}, user, "fais les métrés", "quantitatif"))
verifier("un dossier introuvable n'arrête rien : il est signalé", r3 and r3.get("introuvable") and not r3["ajoutes"])
verifier("sans dossier nommé ni cité : rien n'est ouvert", asyncio.run(dd.dossier_du_travail(uid, fil, {}, user, "fais les métrés des pièces jointes", "quantitatif")) is None)

fil2 = dossiers.identite(uid, "fil-file")[1]
dossiers.enregistrer(uid, fil2, "piece jointe.pdf", "texte", "/api/documents/abc", "sha-pj")
j1 = df.soumettre(uid, fil2, "quantitatif", {"demande": demande, "_demande_utilisateur": demande})
with dossiers.base() as c:
    donnees = c.execute("SELECT donnees FROM file_documentaire WHERE id=?", (j1["tache_documentaire"],)).fetchone()[0]
verifier("un travail qui attend un dossier ne FIGE pas ses sources au dépôt", '"sources"' not in donnees, donnees[:200])
j0 = df.soumettre(uid, fil2, "quantitatif", {"demande": "fais les métrés des pièces jointes"})
with dossiers.base() as c:
    fige = c.execute("SELECT donnees FROM file_documentaire WHERE id=?", (j0["tache_documentaire"],)).fetchone()[0]
verifier("sans dossier, les sources restent figées au dépôt (règle d'origine)", '"sources"' in fige)
df.piloter(uid, fil2, j1["tache_documentaire"], retirer=True)
verifier("un travail retiré disparaît de l'écran", all(x["id"] != j1["tache_documentaire"] for x in df.progression(uid, fil2)))
j1b = df.soumettre(uid, fil2, "quantitatif", {"demande": demande, "_demande_utilisateur": demande})
with dossiers.base() as c:
    statut = c.execute("SELECT statut,essais FROM file_documentaire WHERE id=?", (j1b["tache_documentaire"],)).fetchone()
verifier("le même travail REDEMANDÉ après retrait repart (il n'était pas « en cours » pour rien)", j1b["tache_documentaire"] == j1["tache_documentaire"] and tuple(statut) == ("attente", 0), str(tuple(statut)))
with dossiers.base() as c:
    c.execute("UPDATE file_documentaire SET statut='en_cours' WHERE id=?", (j1["tache_documentaire"],))
dossiers.etape(uid, fil2, "dossier", "chargement", {"dossier": "construction 29 lgts", "vus": 305, "a_charger": 24, "charges": 9, "en_cours": True})
phase = next(x["phase"] for x in df.progression(uid, fil2) if x["id"] == j1["tache_documentaire"])
verifier("pendant l'ouverture, l'écran dit « n/N pièces utiles chargées »", "9/24" in phase and "305 fichiers vus" in phase, phase)
with dossiers.base() as c:
    donnees_j = json_mod.loads(c.execute("SELECT donnees FROM file_documentaire WHERE id=?", (j1["tache_documentaire"],)).fetchone()[0]); donnees_j["tache"] = "tache-ecran"
    c.execute("UPDATE file_documentaire SET donnees=? WHERE id=?", (json_mod.dumps(donnees_j), j1["tache_documentaire"]))
dossiers.etape(uid, fil2, "dossier", "chargement", {"dossier": "x", "vus": 1, "a_charger": 1, "charges": 1, "en_cours": False})
asyncio.run(dd.dire(uid, fil2, "tache-ecran", "lecture visuelle du plan « 06 COUPES.pdf », page 1"))
phase = next(x["phase"] for x in df.progression(uid, fil2) if x["id"] == j1["tache_documentaire"])
verifier("l'écran dit CE QUI SE FAIT : la pièce et la page en cours", "en ce moment : lecture visuelle du plan « 06 COUPES.pdf », page 1" in phase, phase)
dossiers.etape(uid, fil2, "tache-ecran", "suivi_lecture", {"pieces": 23, "parties": 41}); dossiers.etape(uid, fil2, "tache-ecran", "analyse:s1:1", {"faits": []})
asyncio.run(dd.dire(uid, fil2, "tache-ecran", "analyse de « CCAP.pdf » — partie 3 sur 8"))
phase = next(x["phase"] for x in df.progression(uid, fil2) if x["id"] == j1["tache_documentaire"])
verifier("…et l'avancement : « 1 sur 41 parties (23 pièces) », la partie en cours nommée", "1 sur 41 parties analysées (23 pièces)" in phase and "partie 3 sur 8" in phase, phase)
source_q = (BACKEND / "skills" / "quantitatifs.py").read_text()
verifier("un nouvel essai du quantitatif reprend le CONTRAT du premier (pièces et demande)", "contrat['sources']" in source_q and "if not contrat:await" in source_q)

print()
if ECHECS:
    print(f"ÉCHEC — {len(ECHECS)} contrôle(s) :")
    for e in ECHECS:
        print("   ·", e)
    sys.exit(1)
print("Banc des métrés d'un dossier : tout passe.")
