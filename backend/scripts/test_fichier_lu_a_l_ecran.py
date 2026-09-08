"""
Banc « LE FICHIER LU S'AFFICHE » — export Langfuse de Duret du 08/09 (10 tours,
04:07 → 04:49), relevé de Noa : « il n'arrive pas à ouvrir un document du NAS
et le prévisualiser dans le chat, il n'arrive à prévisualiser que les documents
qu'il crée ; niveau cohérence il tourne autour du pot ; par contre il navigue
très bien dans le NAS ».

Ce que les traces ont montré, et ce que ce banc PROUVE (fonctions EXÉCUTÉES
contre des doublures, des deux côtés avec le même fichier) :
1. `nas_lire` / `nas_ouvrir` rendaient `{"type": "document", "texte": …}` —
   aucun dépôt, aucune carte : 04:30 et 04:47, le règlement de consultation est
   LU, résumé par le modèle, jamais affiché. `garantir_fichier_lu` dépose et
   pose la carte (`bloc_ui` fichier ou visuel, `bloc_garanti`), et la lecture
   NAS l'appelle quand un propriétaire est connu ; côté Drive, `ouvrir()` passe
   par `_deposer_pour`.
2. `nas_ouvrir(nom="2029 RC VF.pdf")` → « Aucun fichier de ce nom » sur un
   fichier LISTÉ une minute plus tôt et ouvert ensuite par son chemin : la
   recherche DSM passait `folder_path` nu (DSM veut un tableau JSON, comme le
   téléchargement), l'erreur était avalée comme « racine en panne », et zéro
   résultat passait pour une absence. Désormais : tableau JSON, et un échec sur
   TOUTES les racines est une ERREUR dite.
3. 04:34, « ouvre le » : « Le dossier … a été ouvert. Voici son contenu :
   Fichiers (4) : DPGF, DCE 10,5 Mo, plan de réception… » — QUATRE fichiers
   INVENTÉS, aucun geste dans le tour. `decrit_un_contenu_lu` + aucun geste
   réussi → forceur, puis rédacteur de secours si la prose revient.
4. Le listage s'affiche en TABLEAU mécanique (`garantir_listage`), avec la
   consigne d'ENCHAÎNER l'ouverture quand la demande la réclame.
Tombe sur la version d'avant.
"""
import asyncio
import json
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


NAS = (BACKEND / "nas" / "acces.py").exists()
print(f"\n═══ LE FICHIER LU S'AFFICHE — {BACKEND.parent}  (serveur de fichiers : {'NAS' if NAS else 'Drive'})\n")


def _poser(nom, **attrs):
    mod = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nom] = mod
    return mod


def _exec(chemin: pathlib.Path, nom: str, **espace):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    mod.__dict__.update(espace)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    return mod


# ── Doublures du dépôt : l'atelier et le magasin d'images ──
DEPOSES = []
def _deposer_fichier(nom, octets, proprietaire, origine="depot"):
    DEPOSES.append((nom, len(octets), proprietaire, origine))
    return "JETON123"
def _deposer_octets(octets, mime):
    DEPOSES.append(("image", len(octets), mime, "visuel"))
    return "cle_image_abc"
_poser("bureautique")
_poser("bureautique.atelier", deposer_fichier=_deposer_fichier)
_poser("visuels")
_poser("visuels.depot", deposer_octets=_deposer_octets)
_poser("skills")
aff = _exec(BACKEND / "skills" / "affichage.py", "skills.affichage")
sys.modules["skills.affichage"] = aff

# ── 1. garantir_fichier_lu, exécutée ──
verifier("`garantir_fichier_lu` existe dans skills/affichage.py", callable(getattr(aff, "garantir_fichier_lu", None)))
if callable(getattr(aff, "garantir_fichier_lu", None)):
    DEPOSES.clear()
    r = aff.garantir_fichier_lu({"type": "document", "texte": "Règlement…"}, "2029 RC VF.pdf", b"%PDF" * 1000, "u1")
    verifier("un PDF lu est DÉPOSÉ à l'atelier, origine « serveur » (pas un document produit)",
             DEPOSES and DEPOSES[0][0] == "2029 RC VF.pdf" and DEPOSES[0][2] == "u1" and DEPOSES[0][3] == "serveur", DEPOSES)
    verifier("…et le résultat porte une carte `fichier` GARANTIE avec l'URL de téléchargement",
             r.get("bloc_garanti") is True and (r.get("bloc_ui") or {}).get("type") == "fichier"
             and r["bloc_ui"].get("url") == "/api/documents/JETON123" and r["bloc_ui"].get("format") == "pdf", r.get("bloc_ui"))
    verifier("…le texte lu reste pour le modèle, et l'a_faire interdit de réinventer une carte",
             r.get("texte") == "Règlement…" and "DÉJÀ affiché" in (r.get("a_faire") or "") and "message_final" in r)
    DEPOSES.clear()
    r = aff.garantir_fichier_lu({}, "photo chantier.jpg", b"\xff\xd8" * 100, "u1")
    verifier("une image lue va au dépôt des visuels, bloc `visuel`",
             DEPOSES and DEPOSES[0][3] == "visuel" and (r.get("bloc_ui") or {}).get("type") == "visuel"
             and r["bloc_ui"]["images"][0]["cle"] == "cle_image_abc", (DEPOSES, r.get("bloc_ui")))
    r = aff.garantir_fichier_lu({"texte": "x"}, "a.pdf", b"x", "")
    verifier("sans propriétaire connu : pas de dépôt, la lecture reste telle quelle", "bloc_ui" not in r and r.get("texte") == "x")
    sys.modules["bureautique.atelier"].deposer_fichier = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disque plein"))
    r = aff.garantir_fichier_lu({"texte": "x"}, "a.pdf", b"x", "u1")
    verifier("un dépôt qui échoue ne fait pas tomber la lecture (texte gardé, pas de carte)",
             r.get("texte") == "x" and "bloc_ui" not in r)
    sys.modules["bureautique.atelier"].deposer_fichier = _deposer_fichier

# ── 4. garantir_listage, exécutée ──
verifier("`garantir_listage` existe", callable(getattr(aff, "garantir_listage", None)))
if callable(getattr(aff, "garantir_listage", None)):
    listage = {"chemin": "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/2029 AIRBORNE/1 - DCE",
               "entrees": [{"nom": "01 Pièces Administratives", "chemin": "/x/01", "dossier": True, "octets": None},
                           {"nom": "2029 RC VF.pdf", "chemin": "/x/2029 RC VF.pdf", "dossier": False, "octets": 347078},
                           {"nom": "AOS - DCE.zip", "chemin": "/x/AOS - DCE.zip", "dossier": False, "octets": 179337215}],
               "total": 3, "tronque": False, "note": "3 entrée(s) sur 3."}
    r = aff.garantir_listage(dict(listage), "1 - DCE", ouvreur="nas_ouvrir")
    bloc = r.get("bloc_ui") or {}
    verifier("le listage devient un TABLEAU garanti Nom / Type / Taille",
             r.get("bloc_garanti") is True and bloc.get("type") == "table" and bloc.get("columns") == ["Nom", "Type", "Taille"]
             and len(bloc.get("rows") or []) == 3 and bloc["rows"][1][1] == "Fichier" and "Ko" in bloc["rows"][1][2], bloc)
    verifier("les `entrees` (avec leurs chemins) restent dans le résultat pour le modèle",
             len(r.get("entrees") or []) == 3 and r["entrees"][1]["chemin"] == "/x/2029 RC VF.pdf")
    verifier("l'a_faire ordonne d'ENCHAÎNER l'ouverture (« le plus lourd », « au hasard ») avec le chemin exact, sans demander lequel",
             "nas_ouvrir" in r.get("a_faire", "") and "ne demande pas lequel" in r["a_faire"] and "chemin" in r["a_faire"])

# ── 3. Le contenu décrit sans lecture ──
_poser("agents")
ann = _exec(BACKEND / "agents" / "annonce.py", "agents.annonce")
verifier("`decrit_un_contenu_lu` existe dans annonce.py", callable(getattr(ann, "decrit_un_contenu_lu", None)))
if callable(getattr(ann, "decrit_un_contenu_lu", None)):
    prod = ("Le dossier « **2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS** » a été ouvert. Voici son contenu :\n\n"
            "**Fichiers (4) :**\n- `2029 DPGF.xlsx` — 46,5 Ko\n- `2029 - DCE - 12-09-2026.pdf` — 10,5 Mo\n\n"
            "Souhaitez-vous que j'ouvre l'un de ces fichiers ?")
    verifier("la réponse EXACTE de prod (04:34, quatre fichiers inventés) est reconnue", ann.decrit_un_contenu_lu(prod))
    verifier("« voici son contenu » suffit", ann.decrit_un_contenu_lu("Voici son contenu : trois PDF."))
    verifier("une vraie réponse sans prétention n'est pas visée",
             not ann.decrit_un_contenu_lu("Le maître d'ouvrage est la SAS PAROSA METAL, remise des offres le 18 septembre.")
             and not ann.decrit_un_contenu_lu("Je vais lister le dossier."))

agent1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("route_apres_llm : un contenu décrit sans AUCUN geste réussi part au forceur (livraison fantôme)",
         "decrit_un_contenu_lu(visible)" in agent1
         and agent1.find("decrit_un_contenu_lu(visible)") > agent1.find("def route_apres_llm")
         and 'not any(r.get("ok") for r in (state.get("tool_results") or []))' in agent1)
verifier("rehydrate : si la prose revient quand même, le rédacteur de secours remplace la liste inventée",
         '"contenu_decrit_sans_lecture"' in agent1
         and agent1.find("contenu_decrit_sans_lecture") < agent1.find('besoin = "la_redaction_dement_le_livrable"'))

# ── 2. Le serveur de fichiers, exécuté ──
if NAS:
    APPELS = []
    class SynologyError(Exception):
        pass
    async def _appel(client, base, api, method, version, sid=None, **params):
        APPELS.append((api, method, dict(params)))
        if api == "SYNO.FileStation.Search" and method == "start":
            fp = params.get("folder_path")
            if not (isinstance(fp, str) and fp.startswith("[")):
                raise SynologyError("Synology (SYNO.FileStation.Search.start) : paramètre invalide")
            if json.loads(fp)[0] == "/Drive":
                raise SynologyError("N'EXISTE PAS")
            return {"taskid": "t1"}
        if api == "SYNO.FileStation.Search" and method == "list":
            return {"finished": True, "files": [{"name": "2029 RC VF.pdf", "path": "/home/Drive/x/2029 RC VF.pdf", "isdir": False}]}
        if api == "SYNO.FileStation.Search":
            return {}
        return {"files": [], "total": 0}
    async def _telecharger(client, base, sid, chemin):
        return b"%PDF-1.4 " + b"x" * 500
    _poser("ingestion")
    _poser("ingestion.connectors")
    _poser("ingestion.connectors.synology", _appel=_appel, _telecharger=_telecharger, SynologyError=SynologyError)
    class FichierNonSupporte(Exception):
        pass
    _poser("ingestion.parsers", analyser=lambda nom, brut: {"kind": "texte", "text": "Règlement de consultation…"},
           FichierNonSupporte=FichierNonSupporte)
    _poser("config", settings=types.SimpleNamespace(synology_folders="/home,/Drive", synology_access_level="all"))
    acces = _exec(BACKEND / "nas" / "acces.py", "nas.acces")
    _sleep_orig = asyncio.sleep
    asyncio.sleep = lambda s: _sleep_orig(0)     # le sondage de recherche n'attend pas

    DEPOSES.clear()
    lu = asyncio.run(acces._lire_ouvert(None, "http://nas", "sid", "/home/Drive/x/2029 RC VF.pdf", "u1"))
    verifier("`_lire_ouvert` avec un propriétaire LIT ET DÉPOSE : texte + carte fichier garantie",
             lu.get("type") == "document" and "Règlement" in lu.get("texte", "")
             and (lu.get("bloc_ui") or {}).get("type") == "fichier" and lu.get("bloc_garanti") is True
             and DEPOSES and DEPOSES[0][3] == "serveur", (lu.get("bloc_ui"), DEPOSES))
    DEPOSES.clear()
    lu = asyncio.run(acces._lire_ouvert(None, "http://nas", "sid", "/home/Drive/x/2029 RC VF.pdf"))
    verifier("sans propriétaire (usage interne), aucun dépôt", "bloc_ui" not in lu and not DEPOSES)
    acces.MAX_OCTETS_LECTURE = 10
    lu = asyncio.run(acces._lire_ouvert(None, "http://nas", "sid", "/home/Drive/x/gros.pdf", "u1"))
    verifier("un fichier trop lourd pour être lu est quand même déposé et téléchargeable",
             "trop volumineux" in lu.get("message", "") and (lu.get("bloc_ui") or {}).get("type") == "fichier", lu)
    acces.MAX_OCTETS_LECTURE = 15 * 1024 * 1024

    APPELS.clear()
    r = asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "2029 RC VF.pdf"))
    debuts = [p for a, m, p in APPELS if a == "SYNO.FileStation.Search" and m == "start"]
    premiers = {}
    for p in debuts:                     # le PREMIER essai de chaque racine
        cle = str(p.get("folder_path", "")).strip('[]"')
        premiers.setdefault(cle, str(p.get("folder_path", "")))
    verifier("la recherche DSM passe `folder_path` en TABLEAU JSON au premier essai (comme le téléchargement), la forme nue en second",
             premiers and all(v.startswith("[") for v in premiers.values()), debuts)
    verifier("« 2029 RC VF.pdf » est TROUVÉ (la racine fantôme /Drive en panne n'annule pas /home)",
             r.get("nombre") == 1 and r["resultats"][0]["nom"] == "2029 RC VF.pdf", r)
    verifier("…et la panne partielle est DITE", "ÉCHEC" in r.get("note", "") or "échec" in r.get("note", "").lower(), r.get("note"))
    async def _appel_mort(client, base, api, method, version, sid=None, **params):
        raise SynologyError("Synology (SYNO.FileStation.Search.start) : paramètre invalide")
    sys.modules["ingestion.connectors.synology"]._appel = _appel_mort
    try:
        asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "2029 RC VF.pdf"))
        verifier("une recherche en échec sur TOUTES les racines est une ERREUR, pas « aucun résultat »", False)
    except acces.NasRefuse as e:
        verifier("une recherche en échec sur TOUTES les racines est une ERREUR, pas « aucun résultat »",
                 "ÉCHOUÉ" in str(e) and "nas_lister" in str(e), str(e))
    sys.modules["ingestion.connectors.synology"]._appel = _appel

    outils_sk = (BACKEND / "skills" / "outils.py").read_text(encoding="utf-8")
    verifier("le skill `nas_ouvrir` passe le propriétaire, et préfère `chemin` à `nom`",
             "await ouvrir(quoi, _proprietaire(user))" in outils_sk
             and 'quoi = (data.get("chemin") or data.get("nom") or "").strip()' in outils_sk)
    verifier("le catalogue de `nas_ouvrir` demande le `chemin` EXACT d'un listage et dit que le fichier s'AFFICHE",
             'optionnels=["chemin", "nom"]' in outils_sk and "AFFICHE dans le chat" in outils_sk)
    nas_sk = (BACKEND / "skills" / "nas.py").read_text(encoding="utf-8")
    verifier("`nas_lister` rend un tableau garanti (garantir_listage) et `nas_lire` dépose pour la personne",
             "garantir_listage(await lister(chemin)" in nas_sk and 'await lire(chemin, str(getattr(user, "id", "") or ""))' in nas_sk)
    outils_nas = (BACKEND / "outils" / "nas.py").read_text(encoding="utf-8")
    verifier("`outils.nas.ouvrir` transmet le propriétaire aux deux lectures (chemin direct, résultat de recherche)",
             outils_nas.count("_lire_ouvert(client, base, sid, demande, proprietaire)") == 1
             and 'premier["chemin"], proprietaire)' in outils_nas)
else:
    drive = (BACKEND / "outils" / "drive.py").read_text(encoding="utf-8")
    verifier("`outils.drive.ouvrir` accepte un propriétaire et passe par `_deposer_pour`",
             "proprietaire: str | None = None) -> dict:" in drive and drive.count("_deposer_pour(fichier, service, proprietaire") == 2)
    verifier("`_binaire` est partagé par `octets()` (mail) et `ouvrir()` (chat)",
             "async def _binaire(" in drive and "return await _binaire(fichier, service, vrai_nom, mime)" in drive)
    outils_sk = (BACKEND / "skills" / "outils.py").read_text(encoding="utf-8")
    verifier("le skill `drive_ouvrir` passe le propriétaire", "proprietaire=_proprietaire(user))" in outils_sk)
    # `_deposer_pour` exécutée contre un `_binaire` doublé
    src = drive[drive.find("async def _deposer_pour"):drive.find("async def ouvrir(")]
    esp = {"MAX_OCTETS_PIECE": 20 * 1024 * 1024, "logger": types.SimpleNamespace(info=lambda *a, **k: None)}
    async def _binaire(fichier, service, nom, mime):
        return b"%PDF" * 100, "Devis 2026.pdf", "application/pdf"
    esp["_binaire"] = _binaire
    # `str | None` dans les annotations : le conteneur tourne en 3.12, ce Mac en 3.9.
    exec(compile("from __future__ import annotations\n" + src, "drive_extrait", "exec"), esp)
    DEPOSES.clear()
    r = asyncio.run(esp["_deposer_pour"]({"name": "Devis 2026.pdf", "size": "400", "mimeType": "application/pdf"}, None, "u1", {"contenu": "texte"}))
    verifier("`_deposer_pour` dépose et pose la carte garantie, le contenu reste",
             (r.get("bloc_ui") or {}).get("type") == "fichier" and r.get("bloc_garanti") is True and r.get("contenu") == "texte"
             and DEPOSES and DEPOSES[0][0] == "Devis 2026.pdf", (r, DEPOSES))
    r = asyncio.run(esp["_deposer_pour"]({"name": "gros.pdf", "size": str(50 * 1024 * 1024)}, None, "u1", {"contenu": "t"}))
    verifier("un fichier au-delà de la borne n'est pas déposé, la lecture reste", "bloc_ui" not in r and r.get("contenu") == "t")

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
