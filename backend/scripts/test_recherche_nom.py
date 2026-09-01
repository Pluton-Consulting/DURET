"""
Banc « le classement porte les noms » — la recherche par nom, d'instinct.

Demande de Noa du 01/09 : quand une information sur un client n'est pas en
mémoire d'entreprise, l'assistant doit chercher « instinctivement » les
dossiers et fichiers dont le NOM parle de ce client — à TOUTES les
profondeurs, jamais borné au premier niveau — puis montrer les chemins et
proposer d'aller plus loin.

Ce banc prouve : `chercher()` (Drive, exécuté sur un Drive DOUBLÉ) trouve en
profondeur, sans accent, et classe l'exact d'abord ; `garantir_recherche`
affiche le tableau mécanique et propose la suite ; le skill existe des deux
côtés (`drive_chercher` / `nas_chercher`), le prompt porte la règle, et le
« client introuvable » de `fiche_client` renvoie vers la recherche par nom.
"""
import ast
import asyncio
import importlib.util
import pathlib
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def extraire(chemin, noms, espace):
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
        elif isinstance(n, ast.Import) and any(
                (a.asname or a.name) in noms for a in n.names):
            gardes.append(n)
    exec(compile(ast.Module(body=gardes, type_ignores=[]), str(chemin), "exec"), espace)
    manquants = [x for x in noms if x not in espace]
    assert not manquants, f"absent du module livré : {manquants}"
    return espace


print(f"\n═══ RECHERCHE PAR NOM — {BACKEND.resolve().parent}\n")

# ── 1. Le moteur Drive, exécuté sur un Drive doublé (Symbiose seulement) ──
drive_py = BACKEND / "outils" / "drive.py"
nas_cote = (BACKEND / "skills" / "nas.py").exists()
if not nas_cote:
    import logging

    class _Refus(Exception):
        pass

    CATALOGUE = {
        "f1": {"nom": "33 LA TESTE DE BUCH", "parents": ["dr1"]},
        "f2": {"nom": "33 LA TESTE DE BUCH - Davy SAINT LAURENT", "parents": ["f1"]},
        "f3": {"nom": "COMPTABILITÉ", "parents": ["dr1"]},
        "f9": {"nom": "Anciens", "parents": ["dr1"]},
        "f4": {"nom": "SAINT LAURENT archives", "parents": ["f9"]},
    }

    class _Liste:
        def __init__(self, reponse):
            self._r = reponse

        def execute(self):
            return self._r

    class _Fichiers:
        def list(self, **kwargs):
            return _Liste({"files": [
                {"id": "x1", "name": "Devis SAINT LAURENT.pdf",
                 "parents": ["f2"], "modifiedTime": "2026-08-30"}]})

    class _Service:
        def files(self):
            return _Fichiers()

    async def _srv():
        return _Service()

    async def _balaye(service):
        return dict(CATALOGUE), False

    async def _drives(service):
        return [{"id": "dr1", "name": "Symbiose Paysage"}]

    espace_d = {
        "DriveRefuse": _Refus, "logger": logging.getLogger("banc"),
        "_service": _srv, "_balayer_dossiers": _balaye, "_drives_nommes": _drives,
        "_tout_le_drive": lambda p: True,
        "_enfants_par_lots": None, "Optional": __import__("typing").Optional,
        "_MIME_DOSSIER": "application/vnd.google-apps.folder",
        "MAX_DOSSIERS_ARBRE": 3000,
    }
    extraire(drive_py, {"chercher", "_nu", "_echappe", "_ACCENTS",
                        "MAX_TROUVAILLES", "MAX_PROFONDEUR", "asyncio"}, espace_d)
    chercher = espace_d["chercher"]
    peri = [(None, "all")]

    r = asyncio.run(chercher("Davy Saint Laurent", peri))
    noms = [t["nom"] for t in r["resultats"]]
    verifier("le dossier du client est trouvé EN PROFONDEUR (2 niveaux sous la racine)",
             "33 LA TESTE DE BUCH - Davy SAINT LAURENT" in noms)
    dossier_client = next(t for t in r["resultats"]
                          if t["nom"] == "33 LA TESTE DE BUCH - Davy SAINT LAURENT")
    verifier("son CHEMIN complet est reconstruit (Drive partagé compris)",
             dossier_client["chemin"]
             == "Symbiose Paysage/33 LA TESTE DE BUCH/33 LA TESTE DE BUCH - Davy SAINT LAURENT")
    verifier("le fichier trouvé porte son EMPLACEMENT (le dossier qui le contient)",
             any(not t["dossier"] and t["nom"] == "Devis SAINT LAURENT.pdf"
                 and "33 LA TESTE DE BUCH" in t["chemin"] for t in r["resultats"]))
    r2 = asyncio.run(chercher("comptabilite", peri))
    verifier("la recherche de dossiers est INSENSIBLE AUX ACCENTS (« comptabilite » → COMPTABILITÉ)",
             any(t["nom"] == "COMPTABILITÉ" for t in r2["resultats"]))
    r3 = asyncio.run(chercher("saint laurent", peri))
    verifier("un nom en plusieurs mots trouve TOUTES ses correspondances",
             sum(1 for t in r3["resultats"] if t["dossier"]) >= 2)
    r4 = asyncio.run(chercher("33 LA TESTE DE BUCH", peri))
    verifier("l'exact passe DEVANT (le dossier demandé avant ses variantes)",
             r4["resultats"][0]["nom"] == "33 LA TESTE DE BUCH")
    try:
        asyncio.run(chercher("", peri))
        verifier("un motif vide est REFUSÉ", False)
    except _Refus:
        verifier("un motif vide est REFUSÉ", True)
    src = drive_py.read_text(encoding="utf-8")
    verifier("le chemin cloisonné descend par niveaux sans sortir des racines",
             "_enfants_par_lots(service, niveau)" in src and "MAX_PROFONDEUR" in src)

# ── 2. L'affichage mécanique commun ──────────────────────────────────────
spec = importlib.util.spec_from_file_location("affichage_banc2", BACKEND / "skills" / "affichage.py")
aff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aff)
r = aff.garantir_recherche(
    {"motif": "saint laurent", "nombre": 2,
     "resultats": [{"nom": "Dossier X", "chemin": "A/B", "dossier": True},
                   {"nom": "devis.pdf", "chemin": "A/B/Dossier X", "dossier": False}]},
    "saint laurent")
bloc = r.get("bloc_ui") or {}
verifier("garantir_recherche → tableau mécanique Nom / Type / Emplacement",
         bloc.get("type") == "table" and bloc.get("columns") == ["Nom", "Type", "Emplacement"]
         and ["devis.pdf", "Fichier", "A/B/Dossier X"] in bloc.get("rows", []))
verifier("le résultat est garanti à l'écran et compté dans le message",
         r.get("bloc_garanti") is True and "1 dossier(s) et 1 fichier(s)" in str(r.get("message_final")))
verifier("a_faire : PROPOSER la suite, c'est l'utilisateur qui décide de pousser",
         "PROPOSE la suite" in str(r.get("a_faire")) and "utilisateur" in str(r.get("a_faire")))
vide = aff.garantir_recherche({"motif": "zzz", "nombre": 0, "resultats": []}, "zzz")
verifier("zéro résultat : pas de bloc, et « ne prouve pas l'absence »",
         "bloc_ui" not in vide and "ne prouve pas l'absence" in str(vide.get("a_faire")))

# ── 3. Le skill, le prompt, la fiche client ──────────────────────────────
if nas_cote:
    skills_src = (BACKEND / "skills" / "nas.py").read_text(encoding="utf-8")
    verifier("nas_chercher passe par garantir_recherche",
             "garantir_recherche(resultat, motif)" in skills_src)
    verifier("le catalogue dit D'INSTINCT et rend les CHEMINS",
             "D'INSTINCT" in skills_src and "CHEMINS" in skills_src)
else:
    skills_src = (BACKEND / "skills" / "outils.py").read_text(encoding="utf-8")
    verifier("le skill drive_chercher existe, effet lecture, via garantir_recherche",
             '"drive_chercher": Declaration(' in skills_src
             and "garantir_recherche(resultat, motif)" in skills_src)
    verifier("le catalogue dit D'INSTINCT et rend les CHEMINS",
             "D'INSTINCT" in skills_src and "CHEMINS" in skills_src)
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le prompt : LE CLASSEMENT PORTE LES NOMS, chercher AVANT de dire introuvable",
         "LE CLASSEMENT PORTE LES NOMS" in agent1
         and ("`drive_chercher`" in agent1 or "`nas_chercher`" in agent1)
         and "PROPOSE d'aller plus loin" in agent1)
routines = (BACKEND / "skills" / "routines.py").read_text(encoding="utf-8")
verifier("« client introuvable » renvoie vers la recherche par nom",
         "drive_chercher ou nas_chercher" in routines)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
