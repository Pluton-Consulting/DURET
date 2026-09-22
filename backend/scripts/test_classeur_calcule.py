"""
Banc du CLASSEUR CALCULÉ PAR LE CODE (22/09, Duret, prompts 15 et 16 de la recette).

« Le chiffre d'affaires HT de janvier à août d'après Facturation_20260910.xlsx », puis « le
classement des clients » : le classeur n'était pas un jeu importé, l'assistant l'a LU comme du
texte par pages de 8 000 caractères (16 fragments, ~40 appels), a calculé sur 6 fragments (le
relecteur l'a refusé), puis le temps du tour s'est épuisé. Aucun chiffre rendu.

CE QUE CE BANC PROUVE (skills/donnees.py et ingestion/parsers.py EXÉCUTÉS sur un vrai .xlsx
fabriqué en mémoire, de la forme d'un export de facturation : une feuille de synthèse, puis
une feuille de détail avec un titre AU-DESSUS des en-têtes, 400 lignes) :
  · `lire_feuilles` rend TOUTES les feuilles, et trouve les en-têtes sous le titre ;
  · `interroger_donnees(fichier=…)` sans calcul : les feuilles, leurs colonnes, leurs lignes ;
  · avec `agreger` + `annee` : le total EXACT de TOUTES les lignes de l'année, au centime ;
  · par mois : chaque mois juste ; par client : classé du plus grand au plus petit, et la
    somme des groupes égale le total ;
  · `filtres` et `contient` filtrent avant le calcul ; la feuille la plus longue est retenue
    d'office (et c'est dit) ; une feuille inconnue est signalée avec la liste des feuilles ;
  · les montants au-delà d'un milliard sont écartés comme partout ailleurs.
Tombe sur la version d'avant (`fichier` ignoré, `lire_feuilles` absent).

Usage : python backend/scripts/test_classeur_calcule.py [backend]
"""
import asyncio
import datetime
import importlib.util
import io
import pathlib
import sys
import types
from decimal import Decimal

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


try:
    from openpyxl import Workbook
except ImportError:
    print("openpyxl absent : banc non jouable ici (le conteneur l'a).")
    sys.exit(0)

# ── Le paquet `ingestion` importe la base : on charge parsers.py par son fichier ──
sys.modules["ingestion"] = types.ModuleType("ingestion")
_spec = importlib.util.spec_from_file_location("ingestion.parsers", racine / "ingestion" / "parsers.py")
parsers = importlib.util.module_from_spec(_spec)
sys.modules["ingestion.parsers"] = parsers
_spec.loader.exec_module(parsers)
from skills import donnees  # noqa: E402

# ── Un export de facturation, de la forme réelle ─────────────────────────────
CLIENTS = ["Ville de BIGANOS", "Bordeaux Métropole", "ETCHART", "Mairie de la Crèche", "Gironde Habitat"]
wb = Workbook()
tcd = wb.active
tcd.title = "TCD"
tcd.append(["Étiquettes de lignes", "2024", "2025", "2026"])
tcd.append(["ETCHART", 1200.5, 800, 300])
feuille = wb.create_sheet("SITUATIONS")
feuille.append(["EXPORT FACTURATION — SARL EXEMPLE"])          # un TITRE au-dessus
feuille.append([None])
feuille.append(["N° facture", "Date facture", "Client", "Type", "Montant HT", "Commentaire"])
attendu_2026 = Decimal("0")
par_mois, par_client = {}, {}
for i in range(400):
    annee = 2025 if i % 4 == 0 else 2026
    mois = 1 + (i % 12)
    jour = 1 + (i % 27)
    client = CLIENTS[i % len(CLIENTS)]
    montant = Decimal(1000 + (i * 37) % 9000) + Decimal(i % 100) / 100
    type_ = "Avoir" if i % 25 == 0 else "Facture"
    feuille.append([f"F{annee}-{i:04d}", datetime.datetime(annee, mois, jour), client, type_,
                    float(montant), "reprise travaux terrasse" if i % 7 == 0 else ""])
    if annee == 2026:
        attendu_2026 += montant
        cle = f"2026-{mois:02d}"
        par_mois[cle] = par_mois.get(cle, Decimal("0")) + montant
        par_client[client] = par_client.get(client, Decimal("0")) + montant
feuille.append(["F2026-9999", datetime.datetime(2026, 3, 3), "SIRET PRIS POUR UN MONTANT", "Facture",
                79742715000017, ""])
tampon = io.BytesIO()
wb.save(tampon)
OCTETS = tampon.getvalue()

print("1. Toutes les feuilles, en-têtes trouvés sous le titre")
if not hasattr(parsers, "lire_feuilles"):
    verifier("ingestion/parsers.py définit `lire_feuilles`", False, "absent")
else:
    feuilles = parsers.lire_feuilles("Facturation.xlsx", OCTETS)
    noms = [f["nom"] for f in feuilles]
    verifier("les deux feuilles sont lues", noms == ["TCD", "SITUATIONS"], noms)
    sit = feuilles[1] if len(feuilles) > 1 else {"entetes": [], "lignes": []}
    verifier("les en-têtes de SITUATIONS sont ceux du tableau, pas le titre",
             sit["entetes"][:5] == ["N° facture", "Date facture", "Client", "Type", "Montant HT"], sit["entetes"])
    verifier("ses 401 lignes, toutes", len(sit["lignes"]) == 401, len(sit["lignes"]))


async def _octets(ref, user, fil):
    return OCTETS, "Facturation_20260910.xlsx"


donnees._octets_du_classeur = _octets
UTILISATEUR = types.SimpleNamespace(id="u1", role="super_admin")


def interroger(**data):
    try:
        return asyncio.run(donnees.interroger_donnees({"fichier": "Facturation_20260910.xlsx", **data}, UTILISATEUR))
    except Exception as e:  # noqa: BLE001 — l'ancienne version part vers la base
        return {"erreur": repr(e)[:200]}


print("2. Sans calcul : les feuilles et leurs colonnes")
r = interroger()
verifier("`fichier` est pris en compte (feuilles rendues)",
         [f.get("nom") for f in r.get("feuilles") or []] == ["TCD", "SITUATIONS"], r)
verifier("chaque feuille dit ses lignes et ses colonnes",
         any(f.get("lignes") == 401 and "Montant HT" in f.get("colonnes", []) for f in r.get("feuilles") or []), r)

print("3. Le calcul porte sur TOUTES les lignes")
r = interroger(feuille="SITUATIONS", annee="2026", agreger={"operation": "somme", "colonne": "Montant HT",
                                                              "colonne_date": "Date facture"})
verifier("total 2026 exact, au centime",
         r.get("resultat") is not None and Decimal(str(r.get("resultat"))) == attendu_2026.quantize(Decimal("0.01")),
         (r.get("resultat"), attendu_2026))
verifier("la valeur aberrante (un SIRET) est écartée et signalée", bool(r.get("valeurs_aberrantes_ecartees")), r.get("note"))
verifier("le résultat dit la feuille et le fichier", r.get("feuille") == "SITUATIONS" and r.get("fichier"), r)

r = interroger(feuille="situations", annee="2026", agreger={"operation": "somme", "colonne": "Montant HT",
                                                              "colonne_date": "Date facture", "par": "mois"})
groupes = {g["groupe"]: g["resultat"] for g in r.get("groupes") or []}
verifier("par mois : les douze mois, chacun juste",
         groupes and all(Decimal(str(groupes.get(k))) == v.quantize(Decimal("0.01")) for k, v in par_mois.items()),
         (groupes, par_mois))

r = interroger(feuille="SITUATIONS", annee="2026", agreger={"operation": "somme", "colonne": "Montant HT",
                                                              "colonne_date": "Date facture", "par": "Client"})
ordre = [g["groupe"] for g in r.get("groupes") or []]
attendu = [c for c, _ in sorted(par_client.items(), key=lambda kv: -kv[1])]
verifier("par client : classés du plus grand au plus petit", ordre[:len(attendu)] == attendu, (ordre, attendu))
somme_groupes = sum(Decimal(str(g["resultat"])) for g in r.get("groupes") or [] if g["groupe"] in par_client)
verifier("la somme des clients égale le total", somme_groupes == attendu_2026.quantize(Decimal("0.01")),
         (somme_groupes, attendu_2026))

print("4. Filtres, recherche partielle, choix de la feuille")
r = interroger(feuille="SITUATIONS", filtres={"Type": "avoir"})
verifier("`filtres` : les 16 avoirs, à la casse près", r.get("nombre") == 16, r.get("nombre"))
r = interroger(feuille="SITUATIONS", contient={"Commentaire": "TERRASSE"})
verifier("`contient` : le mot dedans, à la casse près", r.get("nombre") == 58, r.get("nombre"))
r = interroger(annee="2026", agreger={"operation": "compte"})
verifier("sans `feuille`, la plus longue est retenue ET c'est dit",
         r.get("feuille") == "SITUATIONS" and "d'office" in str(r.get("note_feuille")), r)
r = interroger(feuille="Récapitulatif", agreger={"operation": "compte"})
verifier("une feuille inconnue est signalée avec la liste", "Récapitulatif" in str(r.get("message"))
         and [f["nom"] for f in r.get("feuilles") or []] == ["TCD", "SITUATIONS"], r)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
