"""
Banc « LISTER UN DOSSIER DU NAS PAR SON NOM » — relevé du 07/09 (Duret).

Export Langfuse `1788803568867-…json` : « liste-moi les dossiers du drive » →
`nas_lister("Drive")` → « ce dossier N'EXISTE PAS sur le NAS », trois fois de
suite (« Drive », « /Drive », sans chemin) — pendant que `nas_apercu("Drive")`
répondait 18 dossiers et 18 fichiers. L'aperçu résolvait le nom (`_resoudre`,
posé pour ce motif exact), le listage exigeait encore le chemin de montage.

CE QUE CE BANC PROUVE : `outils.nas.lister` résout le nom AVANT de lister
(exécuté contre un NAS doublé où « Drive » vit sous /home), et le skill passe
par lui. Tombe sur la version d'avant.

SECOND RELEVÉ, 08/09 : « ouvre un appel d'offres du NAS au hasard » → « le
dossier « 03-Appel d'offres etudes » existe bien dans la liste du Drive, mais
son chemin exact est hors du périmètre qui m'est autorisé ». Un nom nu se
normalise en « /03-Appel d'offres etudes », sous aucune racine : `verifier`
refusait, et `_resoudre` RELANÇAIT ce refus au lieu de chercher le nom sous
les racines. « Drive » ne passait que parce que c'est aussi le nom de la
racine fantôme du .env. Le premier banc ne l'a pas vu : sa doublure de
`_lister_ouvert` ne refusait JAMAIS — elle était plus tolérante que le code.
Elle refuse désormais comme le vrai `verifier`, et la recherche, le lot, les
photos et le dépôt résolvent un `dossier` donné par son nom.
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


print(f"\n═══ LISTER PAR NOM SUR LE NAS — {BACKEND.parent}\n")

# ── Un NAS doublé : la racine configurée « /Drive » n'existe pas, le vrai est /home/Drive ──
ARBRE = {
    "/home": [{"nom": "Drive", "chemin": "/home/Drive", "dossier": True}],
    "/home/Drive": [{"nom": "01-Administatif", "chemin": "/home/Drive/01-Administatif", "dossier": True},
                    {"nom": "02-Devis-affaires", "chemin": "/home/Drive/02-Devis-affaires", "dossier": True},
                    {"nom": "03-Appel d'offres etudes", "chemin": "/home/Drive/03-Appel d'offres etudes", "dossier": True}],
    "/home/Drive/02-Devis-affaires": [],
    "/home/Drive/03-Appel d'offres etudes": [
        {"nom": "DCE 2031 - VAYRES.pdf", "chemin": "/home/Drive/03-Appel d'offres etudes/DCE 2031 - VAYRES.pdf", "dossier": False}],
}
RACINES = ["/home", "/Drive"]        # « /Drive » est la racine FANTÔME du .env de prod


class NasRefuse(Exception):
    pass


def _verifier(chemin):
    """La règle EXACTE de `nas.acces.verifier` : sous une racine, ou refusé."""
    vise = "/" + (chemin or "").strip("/")
    for r in RACINES:
        if vise == r or vise.startswith(r + "/"):
            return vise
    raise NasRefuse(f"« {chemin} » est hors du périmètre autorisé. Dossiers ouverts : " + ", ".join(RACINES))


async def _lister_ouvert(client, base, sid, chemin):
    chemin = _verifier(chemin)
    if chemin not in ARBRE:
        raise RuntimeError("Synology (SYNO.FileStation.List.list) : ce dossier ou fichier N'EXISTE PAS")
    return {"chemin": chemin, "entrees": ARBRE[chemin], "total": len(ARBRE[chemin])}


RECHERCHES = []      # les `dossier` reçus par la recherche doublée


async def _chercher_ouvert(client, base, sid, motif, dossier=None):
    racines = [_verifier(dossier)] if dossier else RACINES
    RECHERCHES.append(dossier)
    trouves = [e for r in racines for c, entrees in ARBRE.items()
               if c == r or c.startswith(r + "/")
               for e in entrees if motif.lower() in (e["nom"] or "").lower()]
    return {"motif": motif, "nombre": len(trouves), "resultats": trouves, "dossiers_explores": racines}


async def _lire_ouvert(client, base, sid, chemin, proprietaire=None):
    chemin = _verifier(chemin)
    return {"chemin": chemin, "type": "pdf", "contenu": "DCE"}


class _Connexion:
    async def __aenter__(self):
        return (None, "http://nas", "sid")

    async def __aexit__(self, *a):
        return False


def _poser(nom, **attrs):
    mod = types.ModuleType(nom)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nom] = mod
    return mod


_poser("nas")
# 08/09 : la résolution d'un nom passe par le balayage partagé de `nas.acces`
# (l'index du serveur rendait toujours zéro). On le double ici sur le MÊME
# arbre, avec la même règle de correspondance.
async def _balayer(client, base, sid, racines, correspond, **k):
    trouves, vus, niveau = [], set(), list(racines)
    for _ in range(8):
        suivant = []
        for d in niveau:
            for e in ARBRE.get(_verifier(d) if d.startswith("/") else d, []):
                if e["chemin"] in vus:
                    continue
                vus.add(e["chemin"])
                if correspond(e):
                    trouves.append(e)
                if e.get("dossier"):
                    suivant.append(e["chemin"])
        niveau = suivant
        if not niveau:
            break
    return trouves, True


def _sans_accent_nas(texte):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (texte or "").lower())
                   if unicodedata.category(c) != "Mn")


_poser("nas.acces", _lister_ouvert=_lister_ouvert, _chercher_ouvert=_chercher_ouvert,
       _lire_ouvert=_lire_ouvert, connexion=lambda: _Connexion(),
       dossiers_autorises=lambda: list(RACINES), _balayer=_balayer,
       _sans_accent_nas=_sans_accent_nas,
       normaliser=lambda c: "/" + (c or "").strip("/"), NasRefuse=NasRefuse,
       verifier=_verifier, lire=None)
_poser("config", settings=types.SimpleNamespace(synology_folders="/home,/Drive"))
_poser("visuels")
_poser("visuels.depot", deposer_octets=lambda *a, **k: "cle")
_poser("ingestion")
_poser("ingestion.connectors")
_poser("ingestion.connectors.synology", _telecharger=None)
_poser("ingestion.parsers", analyser=None, FichierNonSupporte=Exception)

chemin = BACKEND / "outils" / "nas.py"
mod = types.ModuleType("outils_nas_double")
mod.__dict__["__file__"] = str(chemin)
exec(compile(chemin.read_text(encoding="utf-8"), str(chemin), "exec"), mod.__dict__)

verifier("`outils.nas.lister` existe (le listage qui résout le nom)", callable(getattr(mod, "lister", None)))
if callable(getattr(mod, "lister", None)):
    r = asyncio.run(mod.lister("Drive"))
    verifier("« Drive » (un NOM) liste bien /home/Drive, pas la racine fantôme /Drive",
             r.get("chemin") == "/home/Drive" and len(r.get("entrees") or []) == 3, r)
    try:
        r = asyncio.run(mod.lister("02-Devis-affaires"))
    except NasRefuse as e:
        r = {"refus": str(e)}
    verifier("« 02-Devis-affaires » (petit-enfant de la racine /home) se résout en descendant les niveaux",
             r.get("chemin") == "/home/Drive/02-Devis-affaires", r)
    r2 = asyncio.run(mod.lister("/home/Drive"))
    verifier("un chemin exact marche toujours", r2.get("chemin") == "/home/Drive")
    r3 = asyncio.run(mod.lister("Drive/02-Devis-affaires"))
    verifier("un chemin en plusieurs segments se résout niveau par niveau",
             r3.get("chemin") == "/home/Drive/02-Devis-affaires", r3)
    try:
        asyncio.run(mod.lister("Inconnu"))
        verifier("un nom introuvable est REFUSÉ avec la liste de ce qui existe", False)
    except NasRefuse as e:
        verifier("un nom introuvable est REFUSÉ avec la liste de ce qui existe",
                 "Drive" in str(e) and "EXACT" in str(e), str(e))

    # ── 08/09 : le tour exact de prod ──
    def _lister(nom):
        try:
            return asyncio.run(mod.lister(nom))
        except NasRefuse as e:
            return {"refus": str(e)}

    r = _lister("03-Appel d'offres etudes")
    verifier("« 03-Appel d'offres etudes » (nom nu, vu dans le listage) se liste — plus « hors du périmètre »",
             r.get("chemin") == "/home/Drive/03-Appel d'offres etudes" and len(r.get("entrees") or []) == 1, r)
    r = _lister("/03-Appel d'offres etudes")
    verifier("le même nom avec une barre devant (chemin recomposé par le modèle) se résout aussi",
             r.get("chemin") == "/home/Drive/03-Appel d'offres etudes", r)
    r = _lister("Drive/03-Appel d'offres etudes")
    verifier("« Drive/03-Appel d'offres etudes » descend niveau par niveau",
             r.get("chemin") == "/home/Drive/03-Appel d'offres etudes", r)
    r = _lister("/homes/secret")
    verifier("un chemin VRAIMENT hors périmètre reste refusé (introuvable sous les racines)",
             "refus" in r and "homes" in r["refus"], r)
    verifier("…et le refus ne décrit que ce qui existe SOUS les racines ouvertes",
             "refus" in r and "secret" not in r["refus"].split("Dossiers présents")[-1], r)

verifier("`outils.nas.chercher` existe (la recherche dont le `dossier` se résout)",
         callable(getattr(mod, "chercher", None)))
if callable(getattr(mod, "chercher", None)):
    RECHERCHES.clear()
    r = asyncio.run(mod.chercher("DCE", "03-Appel d'offres etudes"))
    verifier("chercher « DCE » dans « 03-Appel d'offres etudes » (nom) cherche sous /home/Drive/03-…",
             RECHERCHES == ["/home/Drive/03-Appel d'offres etudes"] and r.get("nombre") == 1, (RECHERCHES, r))
    RECHERCHES.clear()
    r = asyncio.run(mod.chercher("DCE"))
    verifier("sans dossier, la recherche couvre toutes les racines", RECHERCHES == [None] and r.get("nombre") == 1)

if callable(getattr(mod, "lire_lot", None)):
    RECHERCHES.clear()
    r = asyncio.run(mod.lire_lot("DCE", "03-Appel d'offres etudes"))
    verifier("`lire_lot` résout le dossier par son nom",
             RECHERCHES == ["/home/Drive/03-Appel d'offres etudes"] and len(r.get("lus") or []) == 1, (RECHERCHES, r))

if callable(getattr(mod, "ouvrir", None)):
    r = asyncio.run(mod.ouvrir("/03-Appel d'offres etudes/DCE 2031 - VAYRES.pdf"))
    verifier("`ouvrir` sur un chemin recomposé (barre devant, parent perdu) retombe sur la recherche par nom",
             r.get("trouve_par") == "nom" and r.get("chemin", "").startswith("/home/Drive/03-"), r)

# 07/09, second export (20:56) : sept listages, jamais un fichier ouvert, puis
# une liste de fichiers INVENTÉE et un nom de fichier inventé passé à
# `nas_ouvrir`. La note du listage dit le geste qui lit ; le refus d'un nom
# inconnu dit de ne jamais deviner.
acces = (BACKEND / "nas" / "acces.py").read_text(encoding="utf-8")
verifier("la note d'un listage dit qu'un FICHIER se lit avec nas_ouvrir, et comment choisir « au hasard »",
         "se LIT avec `nas_ouvrir`" in acces and "ne reliste pas les autres" in acces)
outils = (BACKEND / "outils" / "nas.py").read_text(encoding="utf-8")
verifier("un nom de fichier inconnu dit au modèle de ne jamais deviner un nom",
         "Ce nom ne vient d'aucun listage" in outils)

skill = (BACKEND / "skills" / "nas.py").read_text(encoding="utf-8")
verifier("le skill `nas_lister` passe par la résolution (outils.nas.lister)",
         "from outils.nas import lister" in skill
         and "from nas.acces import lister," not in skill)
verifier("le skill `nas_chercher` passe par la résolution (outils.nas.chercher)",
         "from outils.nas import chercher" in skill
         and "from nas.acces import chercher," not in skill)
verifier("le skill `nas_deposer` résout le dossier par son nom",
         "resoudre_dossier" in skill)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
