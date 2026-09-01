"""
Banc « les réglages s'écrivent VRAIMENT » — 01/09 nuit.

Relevé de Noa, deux fois : « il y a des HTTP 500 partout dans les paramètres »,
puis « dans les paramètres Symbiose il y a encore écrit partout HTTP 500 ».
Journaux de production à l'appui :

    UnboundLocalError: cannot access local variable 'valeur'
      File "/app/llm/reglages.py", line 157, in enregistrer
    AttributeError  (via `.strip()` sur un entier)
      File "/app/llm/reglages.py", line 166, in etat

DEUX BUGS, UNE SEULE ORIGINE : l'ajout du réglage `llm_simultanes`.

  1. Sa validation faisait `valeur = (brut or "").strip()`. Or ce module expose
     une FONCTION `valeur()`, appelée au `return` de cette même fonction. En
     Python, une assignation — même dans une branche jamais prise — rend le nom
     LOCAL À TOUTE LA FONCTION : le retour levait donc `UnboundLocalError` pour
     TOUS les réglages. Choisir un modèle, couper l'anonymisation, poser la date
     des indicateurs : tout tombait, et pas seulement le réglage ajouté.
  2. `etat()` faisait `(getattr(settings, nom) or "").strip()`. Tous les
     réglages ne sont pas des chaînes dans la configuration : `llm_simultanes`
     est un ENTIER, et `8.strip()` faisait tomber l'écran ENTIER des réglages.

POURQUOI CE BANC EXISTE. `test_ollama_concurrence` lisait le SOURCE — il a
vérifié que le réglage était déclaré partout, ce qui était vrai, et n'a rien vu.
Ces deux défauts ne se voient qu'en EXÉCUTANT. Ce banc appelle donc `enregistrer`
et `etat` sur CHAQUE réglage connu, avec une base doublée : c'est le contrôle qui
manquait, et il tombe sur la version d'avant.
"""
import ast
import asyncio
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ LES RÉGLAGES S'ÉCRIVENT VRAIMENT — {BACKEND.resolve().parent}\n")

# ── Le module livré, avec une base et une configuration doublées ─────────
ECRITS: list = []


class _Conn:
    async def execute(self, sql, *args):
        ECRITS.append((sql.split()[0].upper(), args))

    async def fetch(self, sql, *args):
        return []


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


faux_db = types.ModuleType("database.connection")
faux_db.get_db = lambda: _Db()
paquet_db = types.ModuleType("database")
paquet_db.__path__ = []
sys.modules.setdefault("database", paquet_db)
sys.modules["database.connection"] = faux_db

faux_config = types.ModuleType("config")
# LES TYPES SONT CEUX DE `config.py`, et c'est tout l'objet du banc : un entier
# reste un entier, et le code doit y survivre.
faux_config.settings = types.SimpleNamespace(
    llm_tete="", llm_simultanes=8, kpi_depuis="", anonymisation="desactivee",
    modele_rapide=None, modele_puissant=None)
sys.modules["config"] = faux_config

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("reglages_banc",
                                              BACKEND / "llm" / "reglages.py")
reglages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reglages)

USER = "00000000-0000-0000-0000-000000000000"

# ── 1. CHAQUE réglage connu s'écrit sans lever ───────────────────────────
VALEURS = {
    "llm_tete": "standard=google:gemini-flash-latest",
    "llm_simultanes": "10",
    "kpi_depuis": "2026-09-01",
    "anonymisation": "desactivee",
    "modele_rapide": "ollama_cloud:deepseek-v4-flash:0731",
    "modele_puissant": "ollama_cloud:deepseek-v4-pro:0813",
    # 01/09 : la vision et les embeddings se choisissent aussi à l'écran.
    "modele_vision": "ollama_cloud:qwen3.5:397b",
    "modele_embedding": "ollama_cloud:embeddinggemma",
}
verifier("le banc couvre TOUS les réglages déclarés (sinon il ne prouve rien)",
         set(reglages.REGLAGES_CONNUS) <= set(VALEURS),
         str(set(reglages.REGLAGES_CONNUS) - set(VALEURS)))

for nom in reglages.REGLAGES_CONNUS:
    essai = VALEURS.get(nom, "")
    try:
        asyncio.run(reglages.enregistrer(nom, essai, USER))
        ok, souci = True, ""
    except Exception as e:  # noqa: BLE001
        ok, souci = False, f"{type(e).__name__}: {e}"
    verifier(f"« {nom} » s'enregistre sans lever", ok, souci)

# ── 2. Le cas exact de la production : choisir un modèle Ollama ──────────
try:
    asyncio.run(reglages.enregistrer("modele_rapide",
                                     "ollama_cloud:deepseek-v4-flash:0731", USER))
    ok, souci = True, ""
except Exception as e:  # noqa: BLE001
    ok, souci = False, f"{type(e).__name__}: {e}"
verifier("LE CAS DE NOA : « je ne peux pas choisir le modèle Ollama »", ok, souci)

# ── 3. Effacer un réglage rend la main au fichier de configuration ───────
ECRITS.clear()
try:
    asyncio.run(reglages.enregistrer("llm_tete", "", USER))
    ok, souci = True, ""
except Exception as e:  # noqa: BLE001
    ok, souci = False, f"{type(e).__name__}: {e}"
verifier("une valeur vide SUPPRIME la surcharge, sans lever", ok, souci)
verifier("et c'est bien un DELETE, pas un INSERT d'une chaîne vide",
         any(v[0] == "DELETE" for v in ECRITS), str(ECRITS))

# ── 4. Les refus restent des refus ───────────────────────────────────────
for nom, mauvais, pourquoi in (
        ("llm_simultanes", "0", "zéro empêcherait de travailler"),
        ("llm_simultanes", "99", "au-delà du plafond admis"),
        ("llm_simultanes", "beaucoup", "ce n'est pas un nombre"),
        ("kpi_depuis", "hier", "ce n'est pas une date"),
        ("anonymisation", "peut-être", "valeur hors des deux admises"),
        ("modele_rapide", "inconnu:x", "fournisseur hors liste"),
        ("modele_rapide", "ollama_cloud:", "modèle vide"),
        ("modele_vision", "inconnu:x", "fournisseur hors liste, vision aussi"),
        ("modele_embedding", "x", "forme « fournisseur:modele » exigée"),
        ("un_reglage_invente", "x", "réglage hors liste")):
    try:
        asyncio.run(reglages.enregistrer(nom, mauvais, USER))
        refuse = False
    except ValueError:
        refuse = True
    except Exception:  # noqa: BLE001 — une AUTRE erreur n'est pas un refus propre
        refuse = False
    verifier(f"refusé : {nom} = « {mauvais} » ({pourquoi})", refuse)

# ── 5. L'écran des réglages se construit, entiers compris ────────────────
try:
    lignes = asyncio.run(reglages.etat())
    ok, souci = True, ""
except Exception as e:  # noqa: BLE001
    ok, souci, lignes = False, f"{type(e).__name__}: {e}", []
verifier("l'écran des réglages se construit (c'est lui qui tombait en entier)",
         ok, souci)
verifier("il rend une ligne par réglage connu",
         len(lignes) == len(reglages.REGLAGES_CONNUS))
verifier("un réglage ENTIER dans la configuration devient une chaîne lisible",
         any(l["cle"] == "llm_simultanes" and l["valeur"] == "8" for l in lignes),
         str([l for l in lignes if l["cle"] == "llm_simultanes"]))
verifier("l'origine est dite (parametres / env / rien)",
         all(l["origine"] in ("parametres", "env", None) for l in lignes))

# ── 6. La règle qui a causé le bug, vérifiée sur le SOURCE ───────────────
# Une assignation locale qui porte le nom d'une fonction du module rend ce nom
# local À TOUTE LA FONCTION. C'est un piège de langage, pas une faute de frappe :
# il mérite un contrôle permanent.
src = (BACKEND / "llm" / "reglages.py").read_text(encoding="utf-8")
arbre = ast.parse(src)
fonctions = {n.name for n in arbre.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
collisions = []
for n in arbre.body:
    if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    locales = {t.id for x in ast.walk(n) if isinstance(x, ast.Assign)
               for t in x.targets if isinstance(t, ast.Name)}
    appelees = {x.func.id for x in ast.walk(n)
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)}
    for masque in locales & appelees & fonctions:
        collisions.append(f"{n.name} masque {masque}()")
verifier("AUCUNE variable locale ne masque une fonction du module",
         not collisions, "; ".join(collisions))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
