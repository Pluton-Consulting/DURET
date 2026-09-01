"""
Banc « une recherche ne se bloque jamais » — ni en quantité, ni en temps.

Règle de Noa du 01/09 : que ce soit dans la mémoire d'entreprise, sur le
Drive/serveur ou sur internet, une recherche ne doit JAMAIS s'arrêter sur un
plafond de quantité ou de temps. Les garde-fous d'emballement restent ; ce qui
saute, c'est tout ce qui coupait un travail qui AVANCE.

Ce banc prouve : la pagination ne compte plus dans le plafond « même skill »
(enchaîner cinquante pages est permis, les 17 variations du 31/08 restent
bloquées), le tour porte 120 actions, la profondeur RAG sert les pages
lointaines, la recherche Drive est PAGINÉE (jamais coupée), le balayage couvre
30 000 dossiers, le navigateur lit sa borne d'étapes dans la CONFIGURATION
(40, plus 14 en dur) et l'attente la suit, et la recherche NAS va au bout de
son sondage en disant l'inachèvement.
"""
import ast
import pathlib
import re
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


print(f"\n═══ RECHERCHE SANS BORNES — {BACKEND.resolve().parent}\n")

# ── 1. La pagination n'est pas de l'acharnement (agent1) ─────────────────
espace = {}
extraire(BACKEND / "agents" / "agent1.py",
         {"_est_une_page_de_plus", "_CLES_PAGINATION",
          "MAX_ACTIONS_PAR_TOUR", "MAX_APPELS_MEME_SKILL"}, espace)
page_de_plus = espace["_est_une_page_de_plus"]
verifier("« page 2 » du même appel est une page de plus, pas une boucle",
         page_de_plus({"requete": "devis", "page": 1}, {"requete": "devis", "page": 2}))
verifier("« avant » (pagination des mails) compte comme une page de plus",
         page_de_plus({"mailbox": "x", "avant": "a1"}, {"mailbox": "x", "avant": "a2"}))
verifier("« lettre » (annuaire) compte comme une page de plus",
         page_de_plus({"lettre": "A"}, {"lettre": "B"}))
verifier("un appel IDENTIQUE n'est pas une page de plus (le rejeu le gère)",
         not page_de_plus({"page": 2}, {"page": 2}))
verifier("un FILTRE qui change n'est pas de la pagination (les 17 variations du 31/08 restent bloquées)",
         not page_de_plus({"filtres": {"a": 1}}, {"filtres": {"a": 2}})
         and not page_de_plus({"page": 1, "filtres": {"a": 1}}, {"page": 2, "filtres": {"a": 2}}))
verifier("le plafond du tour laisse passer un long travail (120 actions)",
         espace["MAX_ACTIONS_PAR_TOUR"] >= 120)
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le compte « même skill » écarte les pages de plus",
         re.search(r"memes = sum\(.*?_est_une_page_de_plus\(r\.get\(\"args\"\), "
                   r"action\.get\(\"args\"\)\)", agent1, re.S))

# ── 2. La mémoire : les pages profondes existent ─────────────────────────
rag = (BACKEND / "vectorstore" / "rag.py").read_text(encoding="utf-8")
m = re.search(r"PROFONDEUR_MAX = (\d+)", rag)
verifier("la profondeur RAG sert les pages lointaines (≥ 2000 morceaux)",
         m and int(m.group(1)) >= 2000)

# ── 3. Le Drive / le serveur ─────────────────────────────────────────────
nas_cote = (BACKEND / "skills" / "nas.py").exists()
if not nas_cote:
    drive = (BACKEND / "outils" / "drive.py").read_text(encoding="utf-8")
    verifier("le balayage global couvre 30 000 dossiers (30 pages)",
             re.search(r"MAX_PAGES_BALAYAGE = 30", drive)
             and re.search(r"MAX_PAGES_FICHIERS = 30", drive))
    verifier("un aperçu compte jusqu'à 1000 entrées d'un coup (comptes exacts)",
             re.search(r"MAX_ENTREES = 1000", drive))
    # La recherche paginée, EXÉCUTÉE : 95 dossiers correspondent, rien n'est coupé.
    import asyncio
    import logging

    class _Refus(Exception):
        pass

    CATALOGUE = {f"f{i}": {"nom": f"CLIENT DURAND chantier {i}", "parents": ["dr1"]}
                 for i in range(95)}

    class _Liste:
        def execute(self):
            return {"files": []}

    class _Fichiers:
        def list(self, **kwargs):
            return _Liste()

    class _Service:
        def files(self):
            return _Fichiers()

    async def _srv():
        return _Service()

    async def _balaye(service):
        return dict(CATALOGUE), False

    async def _drives(service):
        return [{"id": "dr1", "name": "Drive"}]

    espace_d = {
        "DriveRefuse": _Refus, "logger": logging.getLogger("banc"),
        "_service": _srv, "_balayer_dossiers": _balaye, "_drives_nommes": _drives,
        "_tout_le_drive": lambda p: True, "_enfants_par_lots": None,
        "Optional": __import__("typing").Optional,
        "_MIME_DOSSIER": "application/vnd.google-apps.folder",
        "MAX_DOSSIERS_ARBRE": 3000,
    }
    extraire(BACKEND / "outils" / "drive.py",
             {"chercher", "_nu", "_echappe", "_ACCENTS",
              "MAX_TROUVAILLES", "MAX_PROFONDEUR", "asyncio"}, espace_d)
    r1 = asyncio.run(espace_d["chercher"]("durand", [(None, "all")]))
    r3 = asyncio.run(espace_d["chercher"]("durand", [(None, "all")], page=3))
    verifier("la recherche Drive est PAGINÉE : 95 trouvailles → 3 pages, compte total dit",
             r1["nombre"] == 95 and r1["pages"] == 3 and len(r1["resultats"]) == 40
             and "page=2" in str(r1.get("pour_continuer")))
    verifier("la page 3 rend la FIN, rien n'est perdu",
             len(r3["resultats"]) == 15 and "pour_continuer" not in r3)
else:
    nas = (BACKEND / "nas" / "acces.py").read_text(encoding="utf-8")
    verifier("le sondage de la recherche NAS va jusqu'à une minute (150 × 0,4 s)",
             "for _ in range(150)" in nas and "limit=200" in nas)
    verifier("une recherche interrompue le DIT (résultats partiels, absence non prouvée)",
             "Recherche INTERROMPUE" in nas)
    verifier("l'arbre du serveur a cinq minutes, plus 90 secondes",
             re.search(r"DELAI_ARBRE_S = 300",
                       (BACKEND / "outils" / "nas.py").read_text(encoding="utf-8")))

# ── 4. Le web ────────────────────────────────────────────────────────────
navigateur = (BACKEND / "browser" / "skills.py").read_text(encoding="utf-8")
verifier("naviguer lit sa borne d'étapes dans la CONFIGURATION (plus de 14 en dur)",
         "max_steps=14" not in navigateur and "browser_agent_max_steps" in navigateur)
verifier("l'attente suit la borne d'étapes (plus de 180 s fixes)",
         "time() + 180" not in navigateur and "* 25)" in navigateur)
verifier("chercher_web monte à 10 résultats quand la demande l'exige",
         "min(nombre, 10)" in navigateur)

# ── 5. L'affichage paginé le dit au modèle ───────────────────────────────
import importlib.util
spec = importlib.util.spec_from_file_location("affichage_banc3", BACKEND / "skills" / "affichage.py")
aff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aff)
r = aff.garantir_recherche(
    {"motif": "durand", "nombre": 95, "page": 1, "pages": 3,
     "resultats": [{"nom": "X", "chemin": "A", "dossier": True}]}, "durand")
verifier("le message dit la page, l'a_faire dit d'enchaîner sans limite",
         "page 1 sur 3" in str(r.get("message_final"))
         and "enchaîne les pages" in str(r.get("a_faire"))
         and "rien ne te limite" in str(r.get("a_faire")))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
