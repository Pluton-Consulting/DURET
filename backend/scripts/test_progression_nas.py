"""
Banc « OÙ EN EST L'ENRICHISSEMENT DU NAS » (14/09, Duret).

Relevé de Noa : « Enrichir les documents · En cours… · En ce moment :
ouverture des fichiers (voir la carte du connecteur ci-dessous) — il n'y a
aucun détail de où il en est, il faudrait une vraie barre de progression
détaillée » ; et sur la carte du connecteur : « je relève l'arborescence du
NAS · depuis 11 min · 0 traité(s) — il reste constamment à 0 ».

LA CAUSE : la synchronisation du NAS commence par le RELEVÉ de l'arborescence
(le catalogue : jusqu'à 15 min et 60 000 entrées sur le serveur de
l'entreprise). Pendant tout ce temps, rien n'était remonté : le compteur
« traité(s) » ne bouge qu'à l'ouverture des fichiers, qui vient APRÈS. Et le
rapporteur d'avancement, limité à une écriture par seconde, pouvait sauter le
passage d'une étape à l'autre.

CE QUE CE BANC PROUVE (modules EXÉCUTÉS contre un NAS doublé) :
  * le parcours tient un compte vivant : dossiers lus, repérés, fichiers,
    profondeur, dernier dossier lu ;
  * `catalogue_attendu` fait parler la carte PENDANT le relevé ;
  * la ligne lisible dit dossiers, fichiers, temps écoulé et temps imparti ;
  * la synchro dit le tri (à ouvrir / inchangés / non lisibles) avant le
    premier fichier, puis lus / en échec pendant l'ouverture ;
  (le rapporteur, la campagne et l'écran : `test_progression_campagne.py`, socle).
Tombe sur la version d'avant.
"""
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
RACINE = BACKEND.parent
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ OÙ EN EST L'ENRICHISSEMENT DU NAS — {RACINE}\n")

ARBRE = {
    "/home": [("#recycle", True), ("Drive", True)],
    "/home/#recycle": [("vieux.pdf", False)],
    "/home/Drive": [("01-Administratif", True), ("03-Appel d'offres", True), ("note.docx", False)],
    "/home/Drive/01-Administratif": [("statuts.pdf", False), ("kbis.pdf", False)],
    "/home/Drive/03-Appel d'offres": [("ETUDES EN COURS", True)],
    "/home/Drive/03-Appel d'offres/ETUDES EN COURS": [("CCTP.pdf", False), ("DPGF.xlsx", False)],
}


async def _appel(client, base, api, method, version, sid=None, **params):
    if api == "SYNO.FileStation.List":
        chemin = params.get("folder_path")
        await asyncio.sleep(0)
        return {"files": [{"name": n, "path": f"{chemin}/{n}", "isdir": d,
                           "additional": {"size": None if d else 1024}}
                          for n, d in ARBRE.get(chemin, [])],
                "total": len(ARBRE.get(chemin, []))}
    return {}


def _poser(nom, **attrs):
    mod = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nom] = mod
    return mod


_poser("ingestion")
_poser("ingestion.connectors")
_poser("ingestion.connectors.synology", _appel=_appel,
       _message=lambda code, ctx: f"Synology ({ctx}) : erreur {code}")
_poser("config", settings=types.SimpleNamespace(synology_folders="/home", synology_access_level="all"))
_poser("security")
_poser("security.acces", niveaux_visibles=lambda role: ["all"],
       NIVEAUX=("all", "commercial_plus", "bureau_etudes_plus", "direction_only", "admin_only"))


def _exec(chemin, nom):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    sys.modules[nom] = mod
    return mod


_exec(BACKEND / "security" / "lecteur.py", "security.lecteur")
_poser("nas")
acces = _exec(BACKEND / "nas" / "acces.py", "nas.acces")
_exec(BACKEND / "nas" / "niveaux.py", "nas.niveaux")


class _Cnx:
    async def __aenter__(self):
        return (None, "http://nas", "sid")

    async def __aexit__(self, *a):
        return False


acces.connexion = lambda: _Cnx()

print("— Le parcours tient un compte vivant")
import inspect  # noqa: E402

a_progres = "progres" in inspect.signature(acces._balayer).parameters
verifier("`_balayer` accepte un compte de progression", a_progres)
if a_progres:
    p = {}
    entrees, complet = asyncio.run(acces._balayer(None, "http://nas", "sid", ["/home"],
                                                  lambda e: True, progres=p))
    verifier("EXÉCUTÉ — dossiers lus comptés (la corbeille n'est pas descendue)",
             p.get("dossiers_lus") == 5, p)
    verifier("fichiers repérés comptés", p.get("fichiers_vus") == 5, p)
    verifier("profondeur atteinte et dernier dossier lu", p.get("niveau", 0) >= 3 and p.get("dernier"), p)
    ligne = acces.decrire_progression(p)
    verifier("la ligne lisible dit dossiers, fichiers, temps écoulé et temps imparti",
             "5 dossiers lus" in ligne and "5 fichiers" in ligne and "min" in ligne and "arrêt à" in ligne, ligne)

print("— La carte parle PENDANT le relevé")
if hasattr(acces, "decrire_progression"):
    DITS = []
    vrai_sleep = asyncio.sleep

    async def _construire_lent():
        acces._CATALOGUE["en_cours"] = True
        acces._CATALOGUE["progression"] = {"debut": 0.0, "delai_s": 900, "dossiers_lus": 12,
                                           "dossiers_vus": 40, "fichiers_vus": 300, "niveau": 3,
                                           "dernier": "/home/Drive/03-Appel d'offres"}
        for _ in range(3):
            await vrai_sleep(0.01)
        acces._CATALOGUE.update({"etat": "pret", "entrees": [{"nom": "a.pdf", "chemin": "/home/a.pdf"}],
                                 "complet": True, "construit_le": 10 ** 9, "en_cours": False})
        return acces._CATALOGUE

    acces.construire_catalogue = _construire_lent
    acces._CATALOGUE.update({"etat": "vide", "construit_le": 0.0, "en_cours": False})

    async def _dire(texte):
        DITS.append(texte)

    vrai_wait = asyncio.wait

    async def _attendre(fs, timeout=None):
        return await vrai_wait(fs, timeout=0.005)

    asyncio.wait = _attendre
    try:
        entrees, complet = asyncio.run(acces.catalogue_attendu(sur_progres=_dire))
    finally:
        asyncio.wait = vrai_wait
    verifier("EXÉCUTÉ — l'avancement est dit plusieurs fois pendant la construction",
             sum("12 dossiers lus sur 40 repérés" in d for d in DITS) >= 2, DITS[:3])
    verifier("et le catalogue construit est bien rendu", len(entrees) == 1 and complet)

print("— La synchro du NAS")
syn = (BACKEND / "ingestion" / "connectors" / "synology.py").read_text(encoding="utf-8")
verifier("la synchro fait parler la carte pendant le relevé",
         "acces.catalogue_attendu(\n        sur_progres=" in syn)
verifier("elle dit le tri avant le premier fichier", "à ouvrir" in syn and "rien de nouveau à ouvrir" in syn)
verifier("et pendant l'ouverture : lus, en échec, sans texte",
         "lu(s), " in syn and "en échec, " in syn)
print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
