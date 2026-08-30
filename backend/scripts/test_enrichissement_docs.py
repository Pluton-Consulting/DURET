"""
Banc de l'enrichissement DOCUMENTAIRE — le savoir des fichiers, au bon niveau.

Le cœur de la campagne (30/08) est la CONFIDENTIALITÉ : une connaissance tirée
d'un fichier hérite du niveau des partages RÉELS de ce fichier. La traduction
partages → niveau est une fonction pure : ce banc l'exerce sur tous les cas
qui comptent — dont la RÈGLE STRICTE (jamais l'ombre d'une fuite : un niveau
n'est accordé que si tous ceux qu'il rend lecteurs ont réellement le partage).

Sans base ni réseau : les modules sont chargés seuls, l'accès client doublé.
"""
import asyncio
import importlib.util
import pathlib
import sys
import types

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "backend"
racine = pathlib.Path(BACKEND)
sys.path.insert(0, str(racine))

echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, racine / chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


acces = charger("acces_docs", "learning/acces_docs.py")
campagne = charger("enrichissement_docs", "learning/enrichissement_docs.py")

print(f"\n═══ ENRICHISSEMENT DOCUMENTAIRE — {BACKEND}\n")
print("1. La traduction partages → niveau (règle stricte : aucune fuite)")

ANNUAIRE = {"direction@ex.fr": "direction", "com@ex.fr": "commercial",
            "cond@ex.fr": "conducteur", "be@ex.fr": "bureau_etudes",
            "adm@ex.fr": "administratif", "terrain@ex.fr": "terrain"}


def perms(*adresses, types=()):
    return ([{"type": t} for t in types]
            + [{"type": "user", "emailAddress": a} for a in adresses])


N = acces.niveau_depuis_permissions
verifier("partagé à tout le domaine → all", N(perms(types=["domain"]), ANNUAIRE) == "all")
verifier("« toute personne avec le lien » → all", N(perms(types=["anyone"]), ANNUAIRE) == "all")
verifier("partagé à TOUS les comptes → all",
         N(perms(*ANNUAIRE), ANNUAIRE) == "all")
verifier("commercial + conducteur + bureau d'études → commercial_plus",
         N(perms("com@ex.fr", "cond@ex.fr", "be@ex.fr"), ANNUAIRE) == "commercial_plus")
verifier("bureau d'études seul → bureau_etudes_plus",
         N(perms("be@ex.fr"), ANNUAIRE) == "bureau_etudes_plus")
verifier("UN SEUL commercial → direction_only (le niveau commercial_plus "
         "ouvrirait aussi aux conducteurs, qui n'ont pas le partage)",
         N(perms("com@ex.fr"), ANNUAIRE) == "direction_only")
verifier("direction seule → direction_only",
         N(perms("direction@ex.fr"), ANNUAIRE) == "direction_only")
verifier("une adresse EXTERNE n'élargit rien",
         N(perms("client@ailleurs.com"), ANNUAIRE) == "direction_only")
verifier("externe + domaine : le domaine décide → all",
         N(perms("client@ailleurs.com", types=["domain"]), ANNUAIRE) == "all")
verifier("aucun partage lisible → le plus restrictif", N([], ANNUAIRE) == "direction_only")
verifier("un groupe non résolu n'élargit pas l'accès",
         N([{"type": "group", "emailAddress": "equipe@ex.fr"}], ANNUAIRE) == "direction_only")

# ── 2. la mécanique de campagne ────────────────────────────────────────────
print("\n2. Les lots et le classement")

lots = campagne._lots(["a" * 60, "b" * 60, "c" * 60], budget=100)
verifier("les lots coupent au budget, sans perdre un texte",
         [len(l) for l in lots] == [1, 1, 1] or sum(len(l) for l in lots) == 3, str(lots))
verifier("un texte plus gros que le budget part quand même, seul",
         campagne._lots(["x" * 500], budget=100) == [["x" * 500]])
verifier("rien ne rend rien", campagne._lots([], budget=100) == [])

# `_classer` avec un accès client DOUBLÉ : le niveau réel prime, l'échec
# retombe sur le niveau stocké, un niveau hors échelle sur le plus restrictif.
faux_acces = types.ModuleType("learning.acces_docs")


async def _niveau_reel(source_id, source_type):
    if source_id == "f-direction":
        return "direction_only"
    if source_id == "f-casse":
        raise RuntimeError("partage illisible")
    return None

faux_acces.niveau_reel = _niveau_reel
faux_learning = types.ModuleType("learning")
faux_learning.acces_docs = faux_acces
sys.modules["learning"] = faux_learning
sys.modules["learning.acces_docs"] = faux_acces

DOCS = [
    {"source_id": "f-direction", "source_type": "drive", "nom": "salaires.pdf",
     "acces_stocke": "all", "texte": "..."},
    {"source_id": "f-casse", "source_type": "drive", "nom": "plan.pdf",
     "acces_stocke": "commercial_plus", "texte": "..."},
    {"source_id": "f-normal", "source_type": "drive", "nom": "catalogue.pdf",
     "acces_stocke": "all", "texte": "..."},
    {"source_id": "f-bizarre", "source_type": "drive", "nom": "x.pdf",
     "acces_stocke": "niveau_inconnu", "texte": "..."},
]
groupes = asyncio.run(campagne._classer(DOCS))
verifier("le niveau RÉEL prime sur le niveau stocké",
         any(d["nom"] == "salaires.pdf" for d in groupes.get("direction_only", [])),
         str({n: [d["nom"] for d in ds] for n, ds in groupes.items()}))
verifier("un partage illisible retombe sur le niveau stocké",
         any(d["nom"] == "plan.pdf" for d in groupes.get("commercial_plus", [])))
verifier("sans avis, le niveau stocké fait foi",
         any(d["nom"] == "catalogue.pdf" for d in groupes.get("all", [])))
verifier("un niveau hors échelle retombe sur le plus restrictif",
         any(d["nom"] == "x.pdf" for d in groupes.get("direction_only", [])))

# ── 3. le câblage : routes, écran, déclaration ─────────────────────────────
print("\n3. Le câblage")
routes = (racine / "routers" / "learning.py").read_text(encoding="utf-8")
verifier("la route de lancement existe, gardée par l'administration",
         '"/enrichir-documents"' in routes and "manage_system" in
         routes.split('"/enrichir-documents"')[1][:800])
verifier("la route de statut existe", '"/enrichir-documents/statut"' in routes)
ecran = (racine.parent / "frontend" / "components" / "settings" / "SyncTab.tsx")
verifier("l'écran d'administration porte le bouton",
         "Enrichir les documents" in ecran.read_text(encoding="utf-8"))
invite = campagne.INVITE_DOCS
verifier("l'invite interdit d'inventer et tolère un lot vide",
         "N'INVENTE RIEN" in invite and "ne donne rien" in invite)

print(f"\n═══ {len(echecs)} échec(s)" + (f" : {', '.join(echecs)}" if echecs else " — tout passe"))
sys.exit(1 if echecs else 0)
