"""
Banc « LE NAS SANS SON INDEX » — export Langfuse du 08/09, 10:19 → 10:31 (Duret).

Relevé de Noa : « il n'arrive pas à récupérer les documents sur le NAS et les
afficher ». Les traces donnent la cause, et elle n'est pas celle qu'on croyait.

CE QUE LES TRACES PROUVENT :
1. `SYNO.FileStation.Search` rend ZÉRO sur ce serveur, toujours. « modèle » →
   0. « AIRBORNE » → 0. Et surtout « pdf » avec le CHEMIN EXACT du dossier
   d'appel d'offres → 0, alors que l'arborescence du MÊME dossier, à la même
   minute, compte 132 fichiers dont un sous-dossier « PDF » de 14 fichiers.
   L'index de recherche du NAS n'est pas construit ; aucun réglage de notre
   côté n'y change rien. Le correctif du matin (le chemin en tableau JSON)
   était juste, mais ce n'était pas la cause.
2. LE LISTAGE, LUI, MARCHE : 38 dossiers et 132 fichiers en 6,5 secondes.
3. La résolution d'un nom s'arrêtait à 3 niveaux et 60 listages : « ETUDES EN
   COURS » (niveau 3) et « 2029 AIRBORNE… » (niveau 4) étaient introuvables,
   alors que l'utilisateur venait de les voir à l'écran.

CE QUE CE BANC PROUVE, sur un NAS doublé qui se comporte comme le vrai (la
recherche rend toujours zéro, l'arborescence est celle de la production) : la
recherche et la résolution passent par un BALAYAGE par listages, trouvent ce
qui est là, et disent quand un parcours a été interrompu. Tombe sur la
version d'avant.
"""
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LE NAS SANS SON INDEX — {BACKEND.parent}\n")

# ── L'arborescence RÉELLE relevée en production le 08/09 ──
RACINES = ["/home", "/Drive"]          # « /Drive » est la racine fantôme du .env
ARBRE = {
    "/home": [("#recycle", True), ("BUREAU", True), ("Drive", True), ("scan", True)],
    "/home/#recycle": [],
    "/home/BUREAU": [("vieux", True)],
    "/home/BUREAU/vieux": [],
    "/home/scan": [],
    "/home/Drive": [(n, True) for n in (
        "01-Administatif", "02-Devis-affaires", "03-Appel d'offres etudes",
        "04-Chantiers a executer", "05-Fiches tecniques", "06-Commandes archives",
        "07-Avocat", "08-Compta", "09-Planning")],
    "/home/Drive/03-Appel d'offres etudes": [
        ("ETUDES EN COURS", True), ("ETUDES TERMINEE", True), ("ETUDE PERDU", True),
        ("METRE Maquette Vierge.xlsx", False)],
    "/home/Drive/03-Appel d'offres etudes/ETUDES TERMINEE": [],
    "/home/Drive/03-Appel d'offres etudes/ETUDE PERDU": [],
    "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS": [
        ("2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS", True),
        ("AFF 00 Dossier Modèle", True),
        ("IKOS Village réemploi 18-09-2026 AOS", True)],
    "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/AFF 00 Dossier Modèle": [],
    "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/IKOS Village réemploi 18-09-2026 AOS": [],
    "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS": [
        ("1 - DCE", True), ("2 - Etudes", True)],
    "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS/2 - Etudes": [],
    "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS/1 - DCE": [
        ("04 Plans Architecte et BE", True),
        ("2029 RC VF.pdf", False), ("AOS - merignac-sonovision - DCE.zip", False)],
    "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS/1 - DCE/04 Plans Architecte et BE": [
        ("PDF", True)],
    "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS/1 - DCE/04 Plans Architecte et BE/PDF": [
        ("2029 PLAN RDC.pdf", False), ("2029 COUPE AA.pdf", False)],
}
for d in list(ARBRE):
    for nom, dossier in ARBRE[d]:
        if dossier:
            ARBRE.setdefault(f"{d}/{nom}", [])

DCE = "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS/2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS/1 - DCE"
APPELS_SEARCH = []
GETINFO = []
TELECHARGES = []


class NasRefuse(PermissionError):
    pass


def _verifier(chemin):
    c = "/" + (chemin or "").strip("/")
    for r in RACINES:
        if c == r or c.startswith(r + "/"):
            return c
    raise NasRefuse(f"« {chemin} » est hors du périmètre autorisé. Dossiers ouverts : /home, /Drive")


async def _appel(client, base, api, method, version, sid=None, **params):
    """Le NAS de production : le listage marche, la RECHERCHE rend toujours zéro."""
    if api == "SYNO.FileStation.Search":
        APPELS_SEARCH.append((method, params))
        if method == "start":
            return {"taskid": "t"}
        if method == "list":
            return {"finished": True, "files": []}     # l'index est vide, TOUJOURS
        return {}
    if api == "SYNO.FileStation.List" and method == "getinfo":
        import json as _j
        chemin = _j.loads(params.get("path"))[0]
        GETINFO.append(chemin)
        taille = 179_337_215 if chemin.endswith(".zip") else 1024
        return {"files": [{"path": chemin, "isdir": False, "additional": {"size": taille}}]}
    if api == "SYNO.FileStation.List":
        chemin = params.get("folder_path")
        if chemin not in ARBRE:
            raise RuntimeError("Synology (SYNO.FileStation.List.list) : ce dossier N'EXISTE PAS")
        return {"files": [{"name": n, "path": f"{chemin}/{n}", "isdir": d,
                           "additional": {"size": None if d else 1024}}
                          for n, d in ARBRE[chemin]],
                "total": len(ARBRE[chemin])}
    return {}


def _poser(nom, **attrs):
    mod = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nom] = mod
    return mod


_poser("ingestion")
_poser("ingestion.connectors")
async def _telecharger(client, base, sid, chemin):
    TELECHARGES.append(chemin)
    return b"%PDF-1.4 contenu"


_poser("ingestion.connectors.synology", _appel=_appel, _telecharger=_telecharger)
_poser("ingestion.parsers", analyser=lambda n, b: {"kind": "texte", "text": "x"},
       FichierNonSupporte=Exception)
_poser("config", settings=types.SimpleNamespace(synology_folders="/home,/Drive",
                                                synology_access_level="all"))
_poser("skills")
_poser("skills.affichage", garantir_fichier_lu=lambda r, *a, **k: r,
       garantir_listage=lambda r, *a, **k: r, octets_lisibles=lambda n: str(n))
_poser("bureautique")
_poser("bureautique.atelier", deposer_fichier=lambda *a, **k: "J")
_poser("visuels")
_poser("visuels.depot", deposer_octets=lambda *a, **k: "c")
_poser("security")
_poser("security.acces", niveaux_visibles=lambda role: ["all"])


def _exec(chemin, nom):
    mod = types.ModuleType(nom)
    mod.__dict__["__file__"] = str(chemin)
    exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)
    sys.modules[nom] = mod
    return mod


_poser("nas")
acces = _exec(BACKEND / "nas" / "acces.py", "nas.acces")


class _Cnx:
    async def __aenter__(self):
        return (None, "http://nas", "sid")

    async def __aexit__(self, *a):
        return False


acces.connexion = lambda: _Cnx()
_sleep = asyncio.sleep
asyncio.sleep = lambda s: _sleep(0)          # le sondage de l'index n'attend pas
_poser("outils")
outils = _exec(BACKEND / "outils" / "nas.py", "outils.nas")

# ── 1. Le balayage existe et descend ──
verifier("`_balayer` existe dans nas/acces.py (le parcours qui remplace l'index)",
         callable(getattr(acces, "_balayer", None)))

# ── 2. La recherche trouve ce que l'index ne voit pas ──
# D'abord SANS catalogue : c'est le régime de la première minute après un
# redémarrage, et celui du 08/09 à 10:45. Le catalogue est éprouvé plus bas.
_vrai_catalogue_pret = acces.catalogue_pret
acces.catalogue_pret = lambda: None
APPELS_SEARCH.clear()
r = asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "AIRBORNE"))
verifier("« AIRBORNE » est TROUVÉ alors que l'index du serveur rend zéro",
         r.get("nombre") == 1
         and r["resultats"][0]["nom"].startswith("2029 AIRBORNE"), r.get("nombre"))
verifier("…et le résultat dit par quelle méthode (parcours, pas index)",
         r.get("methode") == "parcours des dossiers", r.get("methode"))
verifier("l'index a bien été tenté d'abord (on ne s'en prive pas là où il marche)",
         any(m == "start" for m, _ in APPELS_SEARCH), APPELS_SEARCH[:2])

r = asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "pdf", DCE))
noms = sorted(x["nom"] for x in r.get("resultats") or [])
verifier("« pdf » dans le dossier DCE rend les 3 PDF ET le dossier « PDF » (le cas exact de prod)",
         r.get("nombre") == 4 and "2029 RC VF.pdf" in noms and "2029 PLAN RDC.pdf" in noms, noms)

r = asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "IKOS"))
verifier("la recherche est indulgente aux accents (« réemploi »)", r.get("nombre") == 1, r.get("nombre"))

r = asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "zzz-introuvable"))
# Sans catalogue, la seule note admise dit qu'il se construit — jamais une
# interruption : le parcours est allé au bout, l'absence est prouvée.
verifier("ce qui n'existe VRAIMENT pas rend zéro, sans note d'interruption",
         r.get("nombre") == 0 and "INTERROMPU" not in (r.get("note") or ""), r)

# Un parcours interrompu le DIT.
vrai_balayer = acces._balayer
async def _court(*a, **k):
    k["delai_s"] = -1                      # le plafond de temps mord tout de suite
    return await vrai_balayer(*a, **k)
acces._balayer = _court
r = asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "AIRBORNE"))
verifier("un parcours INTERROMPU le dit, et refuse de présenter l'absence comme prouvée",
         r.get("nombre") == 0 and "n'est PAS prouvée" in (r.get("note") or ""), r.get("note"))
acces._balayer = vrai_balayer

# ── 3. La résolution d'un nom atteint les niveaux profonds ──
def _lister(nom):
    try:
        return asyncio.run(outils.lister(nom))
    except NasRefuse as e:
        return {"refus": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"refus": str(e)}


r = _lister("ETUDES EN COURS")
verifier("« ETUDES EN COURS » (niveau 3) se résout — il ne se résolvait PAS le 08/09",
         r.get("chemin") == "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS", r)
r = _lister("2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS")
verifier("« 2029 AIRBORNE… » (niveau 4) se résout aussi",
         str(r.get("chemin", "")).endswith("2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS"), r)
r = _lister("/Drive/03-Appel d'offres etudes/ETUDES EN COURS")
verifier("un chemin passant par la racine FANTÔME /Drive se rattrape",
         r.get("chemin") == "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS", r)
r = _lister("Drive")
verifier("un NOM de racine se résout toujours (le cas du 07/09 n'est pas cassé)",
         r.get("chemin") == "/home/Drive", r)
r = _lister("03-Appel d'offres etudes/ETUDES EN COURS")
verifier("un chemin en plusieurs segments descend segment par segment",
         r.get("chemin") == "/home/Drive/03-Appel d'offres etudes/ETUDES EN COURS", r)
r = _lister("Inconnu-xyz")
verifier("un nom vraiment introuvable est refusé, en nommant les dossiers de premier niveau",
         "refus" in r and "premier niveau" in r["refus"] and "Drive" in r["refus"], r)

# ── 4. Ouvrir un fichier par son NOM seul, sans l'index ──
r = asyncio.run(outils.ouvrir("2029 PLAN RDC.pdf"))
verifier("`ouvrir` par le NOM seul retrouve le fichier (il passait par l'index, donc jamais)",
         str(r.get("chemin", "")).endswith("PDF/2029 PLAN RDC.pdf"), r.get("chemin") or r)

# ── 5. Un balayage ne relit pas ce qu'il vient de lire ──
LISTAGES = []
_vrai_lister = acces._lister_ouvert


async def _compte(client, base, sid, chemin):
    LISTAGES.append(chemin)
    return await _vrai_lister(client, base, sid, chemin)


acces._CACHE_LISTAGE.clear()
acces._lister_ouvert = _compte
asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "AIRBORNE"))
premier = len(LISTAGES)
asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "IKOS"))
second = len(LISTAGES) - premier
# La racine fantôme « /Drive » lève à chaque fois : un échec n'est jamais mis
# en cache (un dossier momentanément illisible doit pouvoir revenir). Tout le
# reste est relu de mémoire.
verifier("une seconde recherche dans le même tour ne reliste presque RIEN (le tour du 08/09 en a lancé huit)",
         premier > 5 and second <= 2, (premier, second))
acces._CACHE_LISTAGE.clear()
LISTAGES.clear()
asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "IKOS"))
verifier("…et le cache vidé, le serveur est relu (rien n'est figé pour toujours)", len(LISTAGES) > 5)
src_acces = (BACKEND / "nas" / "acces.py").read_text(encoding="utf-8")
corps_lister = src_acces.split("async def _lister_ouvert")[1].split("\nasync def lister")[0]
verifier("le cache ne sert QU'au balayage : le listage demandé lit toujours le serveur",
         "_CACHE_LISTAGE" not in corps_lister)
acces._lister_ouvert = _vrai_lister

# ── 6. LE CATALOGUE : l'arborescence entière en mémoire, la recherche instantanée ──
acces.catalogue_pret = _vrai_catalogue_pret
acces._CACHE_LISTAGE.clear()
verifier("`construire_catalogue`, `catalogue_pret` et `demarrer_catalogue` existent",
         all(callable(getattr(acces, n, None)) for n in ("construire_catalogue", "catalogue_pret", "demarrer_catalogue")))
etat = asyncio.run(acces.construire_catalogue())
noms_cat = {e.get("nom") for e in etat.get("entrees") or []}
verifier("le catalogue est construit et COMPLET sur l'arborescence de production",
         etat.get("etat") == "pret" and etat.get("complet") is True and len(etat.get("entrees") or []) > 20,
         (etat.get("etat"), len(etat.get("entrees") or [])))
verifier("il porte les niveaux profonds (le DCE, ses PDF)",
         "2029 RC VF.pdf" in noms_cat and "2029 PLAN RDC.pdf" in noms_cat and "ETUDES EN COURS" in noms_cat)
verifier("la corbeille et les dossiers système du NAS n'y sont PAS (« #recycle » mangeait le budget)",
         "#recycle" not in noms_cat and not any(str(n).startswith(("#", "@")) for n in noms_cat if n))
LISTAGES.clear()
acces._lister_ouvert = _compte
r = asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "2029 AIRBORNE SONOVISION"))
verifier("« 2029 AIRBORNE SONOVISION » (le cas de 10:45) est trouvé PAR LE CATALOGUE, sans un seul listage",
         r.get("nombre") == 1 and r.get("methode") == "catalogue" and len(LISTAGES) == 0
         and not r.get("note"), (r.get("nombre"), r.get("methode"), len(LISTAGES), r.get("note")))
r = asyncio.run(acces._chercher_ouvert(None, "http://nas", "sid", "pdf", DCE))
verifier("une recherche dans un dossier précis ne rend que ce qui vit DESSOUS",
         r.get("nombre") == 4 and all(x["chemin"].startswith(DCE + "/") for x in r["resultats"]), r.get("nombre"))
LISTAGES.clear()
r = _lister("2029 AIRBORNE SONOVISION EXTENSION 18-09-2026 AOS")
verifier("la résolution d'un nom profond passe par le catalogue (au plus les racines listées)",
         str(r.get("chemin", "")).endswith("18-09-2026 AOS") and len(LISTAGES) <= 4, (r.get("chemin"), LISTAGES))
acces._lister_ouvert = _vrai_lister
for c in (BACKEND / "main.py", BACKEND.parent.parent / "SYMBIOSE-git" / "symbiose-noa" / "backend" / "main.py"):
    if c.exists():
        verifier(f"le démarrage lance le catalogue en tâche de fond ({c.parent.parent.name})",
                 "demarrer_catalogue" in c.read_text(encoding="utf-8"))

# ── 7. La taille AVANT le téléchargement (le ZIP de 179 Mo, 10:57) ──
TELECHARGES.clear()
r = asyncio.run(acces._lire_ouvert(None, "http://nas", "sid", DCE + "/AOS - merignac-sonovision - DCE.zip", "u1"))
verifier("une archive de 179 Mo est REFUSÉE sans être téléchargée (4 min d'attente le 08/09)",
         not TELECHARGES and "171 Mo" in r.get("message", "") and "ARCHIVE" in r.get("message", ""), (TELECHARGES, r.get("message")))
verifier("…et l'a_faire dit quoi faire : lister le dossier et ouvrir un fichier qu'il contient",
         "nas_lister" in r.get("a_faire", "") and "archive" in r.get("a_faire", "").lower())
TELECHARGES.clear()
r = asyncio.run(acces._lire_ouvert(None, "http://nas", "sid", DCE + "/2029 RC VF.pdf", "u1"))
verifier("un fichier de taille normale est téléchargé et lu comme avant",
         TELECHARGES == [DCE + "/2029 RC VF.pdf"] and r.get("type") == "document", (TELECHARGES, r.get("type")))

# ── 8. Le plafond mord pendant un niveau, et la résolution s'arrête au nom exact ──
acces.catalogue_pret = lambda: None
acces._CACHE_LISTAGE.clear()
LISTAGES.clear()
acces._lister_ouvert = _compte
r = _lister("Drive")
verifier("sans catalogue, « Drive » (niveau 1) se résout en quelques listages, sans balayer tout l'arbre (71 s le 08/09)",
         r.get("chemin") == "/home/Drive" and len(LISTAGES) <= 8, (r.get("chemin"), len(LISTAGES)))
acces._lister_ouvert = _vrai_lister
acces.catalogue_pret = _vrai_catalogue_pret
src_acces = (BACKEND / "nas" / "acces.py").read_text(encoding="utf-8")
verifier("le délai du balayage se vérifie DANS le listage, plus seulement entre deux niveaux",
         "nonlocal coupe" in src_acces and src_acces.count("_t.monotonic() - debut > delai_s") >= 3)

# ── 9. Le catalogue dit ce que coûte un parcours complet ──
skills = (BACKEND / "skills" / "nas.py").read_text(encoding="utf-8")
verifier("le catalogue de `nas_chercher` conseille de donner le dossier, et dit que sans lui c'est long",
         "BEAUCOUP plus rapide" in skills and "ne le relance pas a" in skills)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
