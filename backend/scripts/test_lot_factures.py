"""
Banc de LA LECTURE EN LOT QUI GARDE LES TOTAUX (22/09, Duret, prompt 17 de la recette).

« Totalise les achats WURTH 2026 » : `nas_lire_lot` a lu cinq factures, puis le résultat a été
rogné à 4 000 caractères AVANT le modèle — « lus 1 sur 5, le dernier raccourci ». La moitié du
texte d'une facture était faite d'espaces de mise en page, et la coupe tombait avant les
totaux : le modèle a rappelé le même lot cinq fois, jusqu'à la garde anti-rejeu. Une seule
facture sur treize a été lue jusqu'à son montant.

CE QUE CE BANC PROUVE (`outils.nas.lire_lot` EXÉCUTÉ, NAS doublé, factures de la forme réelle) :
  · les espaces de mise en page sont resserrés ;
  · chaque facture montrée garde son DÉBUT et sa FIN — le total est là pour toutes ;
  · le résultat tient sous le plafond du geste : plus aucune coupe derrière ;
  · 13 factures = 3 pages, `pour_continuer` mène à la suivante, la dernière page n'en a pas ;
  · `nas_lire_lot` est dans les résultats à plafond relevé, et déclare `page`.
Tombe sur la version d'avant (texte brut, 1 sur 5, pas de page).

Usage : python backend/scripts/test_lot_factures.py [backend]
"""
import ast
import asyncio
import contextlib
import json
import pathlib
import sys
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def facture(numero: int) -> str:
    """Une facture fournisseur telle que l'extracteur PDF la rend : colonnes alignées à l'espace."""
    lignes = ["FACTURE", "", " " * 49 + f"SARL CLIENT EXEMPLE       N° de facture       43354{numero:05d}"]
    for i in range(18):
        lignes.append(f"         {i + 1}               0892223{i}           073" + " " * 17
                      + "25        2           9,67      1" + " " * 23 + "19,34")
        lignes.append(" " * 10 + "Mastic silicone à base aqueuse" + " " * 25 + "Poids brut     0,958 KG")
    lignes += ["", "TVA        Mont. de base     Taux TVA      Montant TVA              Montant net"
               f"                                      {numero * 10 + 100},{numero:02d}",
               f"TOTAL HT FACTURE {numero}                                      {numero * 10 + 100},{numero:02d} EUR"]
    return "\n".join(lignes)


FICHIERS = [{"chemin": f"/home/Drive/ARCHIVES 2026/Facture FOURNISSEUR_{n}.pdf", "dossier": False}
            for n in range(13)]


@contextlib.asynccontextmanager
async def _connexion():
    yield None, None, None


async def _chercher(client, base, sid, motif, dossier=None):
    return {"resultats": FICHIERS}


async def _lire(client, base, sid, chemin):
    n = int(chemin.rsplit("_", 1)[1].split(".")[0])
    return {"chemin": chemin, "type": "document", "texte": facture(n)}


class NasRefuse(Exception):
    pass


sys.modules["nas"] = types.ModuleType("nas")
sys.modules["nas.acces"] = types.SimpleNamespace(connexion=_connexion, _lire_ouvert=_lire,
                                                 _chercher_ouvert=_chercher, NasRefuse=NasRefuse)
from outils import nas  # noqa: E402


async def _dossier(client, base, sid, dossier):
    return dossier


nas._dossier_resolu = _dossier

source_agent1 = (racine / "agents" / "agent1.py").read_text(encoding="utf-8")
plafond = 12000
for n in ast.parse(source_agent1).body:
    if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "PLAFOND_RESULTAT_GENEREUX" for t in n.targets):
        plafond = ast.literal_eval(n.value)


def lire(**k):
    try:
        return asyncio.run(nas.lire_lot("Facture FOURNISSEUR", "/home/Drive/ARCHIVES 2026", 5, **k))
    except TypeError as e:          # l'ancienne signature n'a pas `page`
        return {"erreur": str(e)}


print("1. Une page du lot")
r = lire()
lus = r.get("lus") or []
verifier("cinq factures lues", len(lus) == 5, len(lus))
verifier("les espaces de mise en page sont resserrés", lus and "  " not in lus[0]["texte"],
         lus[0]["texte"][:200] if lus else "")
verifier("CHAQUE facture montrée garde son total",
         lus and all(f"TOTAL HT FACTURE {i}" in lu["texte"] for i, lu in enumerate(lus)),
         [lu["texte"][-120:] for lu in lus][:2])
verifier("chaque facture garde aussi son début (numéro)", lus and all("N° de facture" in lu["texte"] for lu in lus))
taille = len(json.dumps(r, ensure_ascii=False))
verifier(f"le résultat tient sous le plafond du geste ({taille} < {plafond}) : aucune coupe derrière", taille < plafond)

print("2. Les pages suivantes")
verifier("13 factures = 3 pages", r.get("pages") == 3, r.get("pages"))
verifier("`pour_continuer` mène à la page 2", "page=2" in str(r.get("pour_continuer")), r.get("pour_continuer"))
r3 = lire(page=3)
verifier("la page 3 lit les 3 dernières", [lu["chemin"][-6:-4] for lu in r3.get("lus") or []] == ["10", "11", "12"],
         [lu.get("chemin") for lu in r3.get("lus") or []] or r3)
verifier("la dernière page n'a pas de suite", "lus" in r3 and r3.get("pour_continuer") is None, r3)

print("3. Le geste")
verifier("`nas_lire_lot` est un résultat à plafond relevé",
         '"nas_lire_lot",' in source_agent1.split("RESULTATS_GENEREUX")[1][:3000])
outils_src = (racine / "skills" / "outils.py").read_text(encoding="utf-8")
verifier("`nas_lire_lot` déclare `page`", 'optionnels=["dossier", "limite", "page"]' in outils_src)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
