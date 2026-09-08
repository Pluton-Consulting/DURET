"""
Banc « OUVRE UN DEVIS » — conversation Symbiose du 08/09 soir (relevé de Noa).

« ouvre moi un devis » → « lequel ? » ; « trouves un devis que nous avons fait
et ouvre le, sur le drive ou envoyé par mail peu importe » → neuf accords,
cinq gestes, 993 correspondances, RIEN d'ouvert ; « ouvre en un au hasar » →
une page de plus de dossiers « Devis », l'arborescence d'un dossier « Devis »
(« 12 050 dossiers · 13 411 fichiers » pour deux fichiers), et « l'action
d'ouverture n'a pas été exécutée à ce tour ». Neuf « Résultat en cours… »
empilés au-dessus de la réponse.

CE QUE CE BANC PROUVE (même fichier des deux côtés ; la partie Drive ne joue
que là où `outils/drive.py` existe) :
  1. la recherche par nom DIT d'ouvrir un FICHIER quand la demande est
     d'ouvrir (`garantir_recherche`, exécuté), avec le geste de chaque côté ;
  2. les demandes exactes de prod sont reconnues comme « ouvrir UN document »,
     et une pièce jointe ouverte compte comme but atteint ;
  3. une chaîne d'accords garde UNE bulle (`rebaptiserBulle`, source) ;
  4. Drive : dossiers et fichiers se partagent chaque page (`_paginer_mixte`,
     `chercher` exécutés sur le cas « devis » : 300 dossiers, 12 fichiers) ;
     l'arborescence d'un sous-dossier porte SES comptes (`_compter_arbre`) ;
     `lister` NOMME les fichiers d'un dossier (exécuté) ; un CHEMIN
     « dossier/fichier » s'ouvre dans ce dossier (`_resoudre_fichier`, exécuté) ;
     le geste `drive_lister` est au catalogue et `drive_ouvrir` accepte `chemin`.
Tombe sur la version d'avant.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import logging
import pathlib
import re
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
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


print(f"\n═══ OUVRE UN DEVIS — {BACKEND.parent}\n")
nas_cote = (BACKEND / "skills" / "nas.py").exists()

# ── 1. La recherche par nom dit d'OUVRIR quand c'est la demande ───────────
spec = importlib.util.spec_from_file_location("affichage_banc_devis", BACKEND / "skills" / "affichage.py")
aff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aff)

r = aff.garantir_recherche({
    "motif": "devis", "nombre": 993, "page": 1, "pages": 25,
    "dossiers_total": 981, "fichiers_total": 12,
    "resultats": [{"nom": "Devis", "chemin": "A/B", "dossier": True},
                  {"nom": "Devis abri LEFEVRE.pdf", "chemin": "A/C", "dossier": False}]},
    "devis", ouvreur="drive_ouvrir")
a = str(r.get("a_faire"))
verifier("la consigne dit d'ENCHAÎNER l'ouverture quand la demande est d'ouvrir",
         "SI LA DEMANDE DE CE TOUR EST D'OUVRIR" in a and "enchaîne MAINTENANT" in a, a[:200])
verifier("… avec le geste du côté (`drive_ouvrir`), sur une ligne « Fichier », jamais un dossier",
         "`drive_ouvrir`" in a and "« Fichier »" in a and "jamais un dossier" in a)
verifier("… sans demander lequel (« au hasard » se choisit)",
         "ne demande pas lequel" in a and "au hasard" in a)
verifier("le compte dit les FICHIERS de toute la recherche, pas seulement les dossiers de la page",
         "981 dossier(s) et 12 fichier(s)" in str(r.get("message_final"))
         and "page 1 sur 25" in str(r.get("message_final")), r.get("message_final"))
verifier("le tableau garanti est intact (Nom / Type / Emplacement)",
         r.get("bloc_garanti") and r["bloc_ui"]["columns"] == ["Nom", "Type", "Emplacement"]
         and r["bloc_ui"]["rows"][1][1] == "Fichier")
r2 = aff.garantir_recherche({"motif": "x", "nombre": 1, "pages": 1,
                             "resultats": [{"nom": "X", "chemin": "A", "dossier": True}]}, "x")
verifier("sans ouvreur nommé, la consigne parle du « geste d'ouverture » (jamais un nom inventé)",
         "le geste d'ouverture" in str(r2.get("a_faire")) and "`None`" not in str(r2.get("a_faire")))
r3 = aff.garantir_recherche({"motif": "devis", "nombre": 5, "page": 1, "pages": 1,
                             "dossiers_total": 5, "fichiers_total": 0,
                             "resultats": [{"nom": "Devis", "chemin": "A", "dossier": True}]},
                            "devis", ouvreur="nas_ouvrir")
verifier("sans fichier du tout, pas de fausse piste « type: fichiers »",
         "type:" not in str(r3.get("a_faire")))
sk_nas = BACKEND / "skills" / "nas.py"
if sk_nas.exists():
    verifier("Duret : `nas_chercher` passe son ouvreur à la recherche",
             'garantir_recherche(resultat, motif, ouvreur="nas_ouvrir")' in sk_nas.read_text(encoding="utf-8"))
sk_out = BACKEND / "skills" / "outils.py"
if not nas_cote:
    verifier("Symbiose : `drive_chercher` passe son ouvreur à la recherche",
             'garantir_recherche(resultat, motif, ouvreur="drive_ouvrir")' in sk_out.read_text(encoding="utf-8"))

# ── 2. Les demandes exactes de prod, et la pièce jointe comme but atteint ──
sys.modules.setdefault("agents", types.ModuleType("agents"))
chemin = BACKEND / "agents" / "annonce.py"
ann = types.ModuleType("agents.annonce")
ann.__dict__["__file__"] = str(chemin)
exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), ann.__dict__)
for demande in ("ouvre moi un devis",
                "trouves un devis que nous avons fait et ouvre le , sur le drive ou envoyé par mail peu importe",
                "ouvre en un au hasar"):
    verifier(f"« {demande[:40]} » = ouvrir UN document", ann.demande_d_ouvrir_un_seul(demande))
verifier("« ouvre tous les devis du dossier » n'en est pas une",
         not ann.demande_d_ouvrir_un_seul("ouvre tous les devis du dossier"))
agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
m = re.search(r"SKILLS_LECTURE_FICHIER = frozenset\(\{([^}]*)\}\)", agent1, re.S)
verifier("une pièce jointe OUVERTE (`lire_piece_jointe`) est un but atteint, comme un fichier du classement",
         m and "lire_piece_jointe" in m.group(1) and "drive_ouvrir" in m.group(1))
verifier("le listage du Drive est un résultat généreux (jamais coupé au milieu de ses lignes)",
         '"drive_lister"' in agent1.split("RESULTATS_GENEREUX = ", 1)[1][:400])

# ── 3. Une chaîne d'accords garde UNE bulle ───────────────────────────────
cw = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("`rebaptiserBulle` existe : la bulle change de propriétaire au lieu d'en créer une",
         "const rebaptiserBulle = (ancienne: string, nouvelle: string" in cw
         and "tachesSuiviesRef.current.delete(ancienne)" in cw
         and "tachesSuiviesRef.current.add(nouvelle)" in cw)
bloc = cw.split('res.status === "pending_validation" && res.validation_id && String(res.validation_id) !== id', 1)[1][:900]
verifier("dans la chaîne d'accords, la bulle « Résultat en cours… » est rebaptisée vers l'accord suivant",
         "rebaptiserBulle(porteuse, cleAccord(suivant)!, TEXTE_ATTENTE_ACCORD)" in bloc
         and "const porteuse = liee ? liee.id : cle" in bloc)
verifier("… et une nouvelle bulle ne naît que s'il n'y en avait aucune à rebaptiser",
         "} else {\n          bulleAccord(suivant)" in bloc
         and "setPrincipalOccupe(true)\n        bulleAccord(suivant)" not in bloc)
verifier("la bulle rebaptisée reprend le texte d'attente (plus « Résultat en cours… » figé)",
         "...(m.placeholder ? { content: contenu } : {})" in cw)

# ── 4. Le Drive (Symbiose seulement) ──────────────────────────────────────
drive_py = BACKEND / "outils" / "drive.py"
if not nas_cote and drive_py.exists():

    class _Refus(Exception):
        pass

    # 4a. La pagination mixte, pure.
    esp = {}
    extraire(drive_py, {"_paginer_mixte"}, esp)
    pm = esp["_paginer_mixte"]
    D = [{"nom": f"d{i}", "dossier": True} for i in range(50)]
    F = [{"nom": f"f{i}", "dossier": False} for i in range(45)]
    p1, pages = pm(D, F, 40, 1)
    verifier("50 dossiers + 45 fichiers : page 1 = 20 dossiers ET 20 fichiers, 3 pages",
             pages == 3 and sum(1 for e in p1 if e["dossier"]) == 20 and len(p1) == 40)
    p3, _ = pm(D, F, 40, 3)
    verifier("… page 3 = les 15 restants (10 dossiers, 5 fichiers)",
             len(p3) == 15 and sum(1 for e in p3 if e["dossier"]) == 10)
    p1s, pages_s = pm(D + D[:45], [], 40, 1)
    verifier("95 dossiers seuls : 40 par page, 3 pages — la pagination d'avant est conservée",
             pages_s == 3 and len(p1s) == 40 and len(pm(D + D[:45], [], 40, 3)[0]) == 15)
    p1d, pages_d = pm([{"nom": f"Devis {i}", "dossier": True} for i in range(981)],
                      [{"nom": f"devis {i}.pdf", "dossier": False} for i in range(12)], 40, 1)
    verifier("le cas de prod (981 dossiers « Devis », 12 fichiers) : les 12 FICHIERS sont sur la page 1",
             sum(1 for e in p1d if not e["dossier"]) == 12 and len(p1d) == 40)
    verifier("rien trouvé : une page vide, pas une division par zéro", pm([], [], 40, 1) == ([], 1))
    verifier("une page au-delà de la fin est vide, le nombre de pages reste juste",
             pm(D, F, 40, 9) == ([], 3))

    # 4b. `chercher` exécuté sur le cas « devis ».
    class _Liste:
        def __init__(self, reponse):
            self._r = reponse

        def execute(self):
            return self._r

    class _Fichiers:
        def list(self, **kwargs):
            return _Liste({"files": [
                {"id": f"x{i}", "name": f"Devis abri {i} - REF LEFEVRE.pdf",
                 "parents": ["f1"], "modifiedTime": "2026-08-30"} for i in range(12)]})

    class _Service:
        def files(self):
            return _Fichiers()

    async def _srv(identite=None):
        return _Service()

    CATALOGUE = {"f1": {"nom": "33 TALENCE - LEFEVRE", "parents": ["dr1"]}}
    for i in range(300):
        CATALOGUE[f"dv{i}"] = {"nom": "Devis", "parents": ["f1"]}

    async def _catalogue_double(service, identite=None):
        return dict(CATALOGUE), False, {}, False

    async def _drives(service):
        return [{"id": "dr1", "name": "Symbiose Paysage"}]

    esp_c = {"DriveRefuse": _Refus, "logger": logging.getLogger("banc"),
             "_service": _srv, "_drives_nommes": _drives, "_catalogue": _catalogue_double,
             "_tout_le_drive": lambda p: True, "_enfants_par_lots": None,
             "Optional": __import__("typing").Optional,
             "_MIME_DOSSIER": "application/vnd.google-apps.folder", "MAX_DOSSIERS_ARBRE": 3000}
    extraire(drive_py, {"chercher", "_paginer_mixte", "_nu", "_echappe", "_ACCENTS",
                        "MAX_TROUVAILLES", "MAX_PROFONDEUR", "asyncio"}, esp_c)
    rc = asyncio.run(esp_c["chercher"]("devis", [(None, "all")]))
    fichiers_p1 = [t for t in rc["resultats"] if not t["dossier"]]
    verifier("« devis » : 300 dossiers « Devis » + 12 fichiers → les 12 fichiers sont sur la page 1",
             len(fichiers_p1) == 12 and rc["nombre"] == 312 and rc["pages"] == 8,
             f"{len(fichiers_p1)} fichiers, {rc['nombre']} au total, {rc['pages']} pages")
    verifier("… le résultat dit les totaux par sorte (`dossiers_total`, `fichiers_total`)",
             rc.get("dossiers_total") == 300 and rc.get("fichiers_total") == 12)
    verifier("… un fichier garde son chemin et sa date", fichiers_p1[0]["chemin"] == "Symbiose Paysage/33 TALENCE - LEFEVRE"
             and fichiers_p1[0].get("modifie_le"))
    rf = asyncio.run(esp_c["chercher"]("devis", [(None, "all")], genre="fichiers"))
    verifier("`type: fichiers` ne garde que les fichiers (12, une page)",
             rf["nombre"] == 12 and rf["pages"] == 1 and all(not t["dossier"] for t in rf["resultats"])
             and rf.get("type") == "fichiers")
    rd = asyncio.run(esp_c["chercher"]("devis", [(None, "all")], genre="dossiers", page=8))
    verifier("`type: dossiers` : 300 dossiers, page 8 = les 20 derniers",
             rd["nombre"] == 300 and rd["pages"] == 8 and len(rd["resultats"]) == 20)

    # 4c. L'arborescence d'un sous-dossier porte SES comptes.
    esp_a = {}
    extraire(drive_py, {"_compter_arbre"}, esp_a)
    foret = [{"nom": "Devis", "fichiers": 2, "enfants": [
        {"nom": "2024", "fichiers": 3, "enfants": []},
        {"nom": "2025", "fichiers": 1, "enfants": [{"nom": "2024", "fichiers": 99, "cycle": True}]}]}]
    verifier("« Devis » (2 fichiers) + 2024 (3) + 2025 (1) = 2 sous-dossiers, 6 fichiers — le cycle ne compte pas",
             esp_a["_compter_arbre"](foret) == (2, 6), esp_a["_compter_arbre"](foret))
    src = drive_py.read_text(encoding="utf-8")
    verifier("`arborescence(dossier)` prend les comptes du sous-arbre, plus ceux du Drive entier",
             "dossiers_total, total_fichiers = _compter_arbre(racines)" in src
             and '"dossiers_total": dossiers_total' in src)
    verifier("… et dit que l'arbre ne nomme pas les fichiers (→ `drive_lister`)",
             "L'arbre ne nomme pas les" in src and "`drive_lister` sur ce dossier" in src)

    # 4d. `lister` nomme les fichiers d'un dossier, avec chemin, taille, date.
    ENTREES = ([{"id": "sd", "name": "2025", "mimeType": "application/vnd.google-apps.folder"}]
               + [{"id": f"p{i}", "name": f"Devis {i:03d}.pdf", "mimeType": "application/pdf",
                   "size": str(1000 + i), "modifiedTime": "2026-05-26"} for i in range(250)])

    async def _lister_double(service, dossier, limite=1000):
        assert dossier == "ID-DEVIS"
        return {"entrees": list(ENTREES), "tronque": False}

    async def _resoudre_double(service, chemin, racines, partout=False):
        assert chemin == "33 LACANAU DE MIOS - DULUGAT Julien/Devis", chemin
        return "ID-DEVIS"

    async def _racines_double(service):
        return ["dr1"]

    esp_l = {"DriveRefuse": _Refus, "logger": logging.getLogger("banc"), "_service": _srv,
             "_racines": _racines_double, "_resoudre": _resoudre_double,
             "_lister": _lister_double, "_garde_perimetre": lambda d, p: None,
             "_tout_le_drive": lambda p: True, "Optional": __import__("typing").Optional,
             "_MIME_DOSSIER": "application/vnd.google-apps.folder"}
    extraire(drive_py, {"lister", "_classer", "_nu", "_ACCENTS", "MAX_ENTREES",
                        "LISTAGE_PAR_PAGE", "asyncio"}, esp_l)
    rl = asyncio.run(esp_l["lister"]("33 LACANAU DE MIOS - DULUGAT Julien/Devis", [(None, "all")]))
    verifier("`lister` rend 1 sous-dossier et 250 fichiers NOMMÉS, le sous-dossier d'abord",
             rl["dossiers"] == 1 and rl["fichiers"] == 250 and rl["entrees"][0]["dossier"]
             and rl["entrees"][0]["nom"] == "2025" and not rl["entrees"][1]["dossier"])
    verifier("… chaque fichier porte son chemin « dossier/nom », sa taille et sa date",
             rl["entrees"][1]["chemin"] == "33 LACANAU DE MIOS - DULUGAT Julien/Devis/Devis 000.pdf"
             and rl["entrees"][1]["octets"] == 1000 and rl["entrees"][1]["modifie_le"] == "2026-05-26")
    verifier("… paginé (200 par page), la suite dite, jamais coupé",
             rl["pages"] == 2 and len(rl["entrees"]) == 200 and "page=2" in str(rl.get("pour_continuer")))
    rl2 = asyncio.run(esp_l["lister"]("33 LACANAU DE MIOS - DULUGAT Julien/Devis", [(None, "all")], page=2))
    verifier("… page 2 = les 51 restants, sans « pour_continuer »",
             len(rl2["entrees"]) == 51 and "pour_continuer" not in rl2)
    gl = aff.garantir_listage(dict(rl), "Devis", ouvreur="drive_ouvrir")
    verifier("le tableau garanti du listage nomme les fichiers et dit d'enchaîner `drive_ouvrir`",
             gl.get("bloc_garanti") and gl["bloc_ui"]["rows"][1][0] == "Devis 000.pdf"
             and "`drive_ouvrir`" in str(gl.get("a_faire")) and gl.get("entrees"))

    # 4e. Un CHEMIN « dossier/fichier » s'ouvre DANS ce dossier.
    requetes = []

    class _FichiersChemin:
        def list(self, **kwargs):
            requetes.append(kwargs.get("q", ""))
            q = kwargs.get("q", "")
            if "'ID-DEVIS' in parents" in q and "name = 'Devis 007.pdf'" in q:
                return _Liste({"files": [{"id": "p7", "name": "Devis 007.pdf", "mimeType": "application/pdf"}]})
            if "'ID-DEVIS' in parents" in q:
                return _Liste({"files": []})
            return _Liste({"files": [{"id": "ailleurs", "name": "Devis 007.pdf", "mimeType": "application/pdf"},
                                     {"id": "ailleurs2", "name": "Devis 007.pdf", "mimeType": "application/pdf"}]})

    class _ServiceChemin:
        def files(self):
            return _FichiersChemin()

    async def _srv_chemin(identite=None):
        return _ServiceChemin()

    async def _resoudre_chemin(service, chemin, racines, partout=False):
        if chemin == "DULUGAT/Devis":
            return "ID-DEVIS"
        raise _Refus("dossier inconnu")

    esp_r = {"DriveRefuse": _Refus, "logger": logging.getLogger("banc"), "_service": _srv_chemin,
             "_racines": _racines_double, "_resoudre": _resoudre_chemin,
             "_garde_perimetre": lambda d, p: None, "_tout_le_drive": lambda p: True,
             "Optional": __import__("typing").Optional,
             "_MIME_DOSSIER": "application/vnd.google-apps.folder"}
    extraire(drive_py, {"_resoudre_fichier", "asyncio"}, esp_r)
    f, _s, autres = asyncio.run(esp_r["_resoudre_fichier"]("DULUGAT/Devis/Devis 007.pdf", [(None, "all")]))
    verifier("« DULUGAT/Devis/Devis 007.pdf » ouvre LE fichier de ce dossier (exact, pas un homonyme d'ailleurs)",
             f["id"] == "p7" and not autres)
    verifier("… la requête cherche DANS le dossier résolu, par nom exact d'abord",
             requetes and "'ID-DEVIS' in parents" in requetes[0] and "name = 'Devis 007.pdf'" in requetes[0])
    requetes.clear()
    f2, _s, _a = asyncio.run(esp_r["_resoudre_fichier"]("Inconnu/Devis 007.pdf", [(None, "all")]))
    verifier("un chemin qui ne se résout pas retombe sur la recherche par le nom seul (jamais un refus sec)",
             f2["id"] == "ailleurs" and requetes and "in parents" not in requetes[-1]
             and "Devis 007.pdf" in requetes[-1])
    f3, _s, _a = asyncio.run(esp_r["_resoudre_fichier"]("Devis 007.pdf", [(None, "all")]))
    verifier("un nom nu suit la voie d'avant", f3["id"] == "ailleurs")

    # 4f. Le catalogue et les câblages.
    out = sk_out.read_text(encoding="utf-8")
    verifier("le geste `drive_lister` est au catalogue, effet lecture, `dossier` requis, `page` en option",
             re.search(r'"drive_lister": Declaration\(.*?requis=\["dossier"\], optionnels=\["page"\].*?effet="lecture"', out, re.S))
    verifier("`drive_lister` passe par `garantir_listage` avec `drive_ouvrir` comme ouvreur",
             'garantir_listage(resultat, dossier, ouvreur="drive_ouvrir")' in out)
    verifier("`drive_ouvrir` accepte `chemin` (le chemin rendu par le listage)",
             'data.get("chemin")' in out.split("async def drive_ouvrir", 1)[1][:600]
             and re.search(r'"drive_ouvrir": Declaration\(.*?optionnels=\["chemin"\]', out, re.S))
    verifier("`drive_chercher` accepte `type` (fichiers / dossiers)",
             re.search(r'"drive_chercher": Declaration\(.*?optionnels=\["page", "type"\]', out, re.S)
             and 'genre=data.get("type")' in out)
    verifier("`drive_apercu` dit qu'il compte sans nommer (→ `drive_lister`)",
             "pour leurs NOMS, `drive_lister`" in out)
    verifier("la carte du classement nomme `drive_lister` comme geste de listage",
             'GESTE_LISTER = "drive_lister"' in (BACKEND / "classement" / "source.py").read_text(encoding="utf-8"))
    verifier("le prompt dit : « ouvre un devis / un au hasard » → cherche ou liste, puis OUVRE sans demander",
             "puis OUVRE un fichier sans demander lequel" in agent1 and "`drive_lister`" in agent1)

print(f"\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ tous les contrôles passent'}\n")
sys.exit(1 if echecs else 0)
