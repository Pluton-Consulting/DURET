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
                    {"nom": "02-Devis-affaires", "chemin": "/home/Drive/02-Devis-affaires", "dossier": True}],
    "/home/Drive/02-Devis-affaires": [],
}


class NasRefuse(Exception):
    pass


async def _lister_ouvert(client, base, sid, chemin):
    if chemin not in ARBRE:
        raise RuntimeError("Synology (SYNO.FileStation.List.list) : ce dossier ou fichier N'EXISTE PAS")
    return {"chemin": chemin, "entrees": ARBRE[chemin], "total": len(ARBRE[chemin])}


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
_poser("nas.acces", _lister_ouvert=_lister_ouvert, connexion=lambda: _Connexion(),
       dossiers_autorises=lambda: ["/home", "/Drive"],
       normaliser=lambda c: "/" + (c or "").strip("/"), NasRefuse=NasRefuse,
       verifier=lambda c: c, lire=None)
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
             r.get("chemin") == "/home/Drive" and len(r.get("entrees") or []) == 2, r)
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

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs))
    sys.exit(1)
print("✓ 0 échec")
