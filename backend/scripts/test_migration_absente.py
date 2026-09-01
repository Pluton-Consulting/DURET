"""
Banc « une migration non appliquée se DIT » — 01/09 soir.

Relevé de Noa en production, verbatim : « il y a des HTTP 500 partout dans les
paramètres et dans les modèles de l'assistant […] c'est pareil dans les
paramètres de mon compte Google ».

LA CAUSE. Le code part sur le VPS par `pluton deployer`, les migrations
s'appliquent À LA MAIN : entre les deux, le backend tourne du code neuf sur une
base ancienne. Trois routes posées dans la journée lisaient des colonnes ou une
table pas encore créées — `role_quota_config.concurrent_limit` et
`users.llm_simultanes` (029), `connexions_google` (026 ici, 031 chez le
jumeau), `mail_signatures` (030) — et rendaient un HTTP 500 NU. Le message ne disait pas lequel des deux
gestes manquait, et personne devant l'écran ne pouvait le deviner.

CE QUE CE BANC EXIGE. Une migration absente doit être RECONNUE comme telle,
NOMMÉE à l'écran, et ne jamais se faire passer pour une absence de données —
« pas encore relié » alors que la table n'existe pas serait un mensonge, parce
que le bouton ne marcherait pas davantage. Une VRAIE panne, elle, doit continuer
de remonter : avaler toutes les erreurs serait le défaut inverse.
"""
import ast
import asyncio
import pathlib
import re
import sys

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend")
FRONTEND = BACKEND.resolve().parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


print(f"\n═══ UNE MIGRATION ABSENTE SE DIT — {BACKEND.resolve().parent}\n")

# ── 1. Le détecteur, EXÉCUTÉ ─────────────────────────────────────────────
espace = {}
arbre = ast.parse((BACKEND / "database" / "connection.py").read_text(encoding="utf-8"))
gardes = [n for n in arbre.body
          if isinstance(n, ast.FunctionDef) and n.name == "schema_incomplet"]
verifier("`schema_incomplet` existe dans le module livré", bool(gardes))
if gardes:
    exec(compile(ast.Module(body=gardes, type_ignores=[]), "connection", "exec"), espace)
    detecte = espace["schema_incomplet"]

    class _FausseColonne(Exception):
        pass

    verifier("une colonne absente est reconnue au message",
             detecte(_FausseColonne(
                 'column "llm_simultanes" of relation "users" does not exist')))
    verifier("une table absente est reconnue au message",
             detecte(_FausseColonne('relation "connexions_google" does not exist')))
    verifier("UNE VRAIE PANNE N'EST PAS AVALÉE (c'est le défaut inverse)",
             not detecte(_FausseColonne("connection refused"))
             and not detecte(_FausseColonne("deadlock detected")))
    verifier("une erreur muette ne passe pas pour une migration",
             not detecte(_FausseColonne("")))

# ── 2. Les trois routes, lues dans le source livré ───────────────────────
st = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
lecture = st.split('@router.get("/concurrence")')[1].split("@router.put")[0]
# 01/09 soir : LA MEILLEURE PARADE A ÉTÉ DE SUPPRIMER LA DÉPENDANCE. Sur
# décision de Noa (« ce paramètre concerne l'ensemble des comptes cumulés »),
# la carte ne règle plus qu'UN plafond, qui vit dans la table `reglages` — donc
# elle ne lit plus aucune colonne ajoutée par une migration récente, et ne peut
# plus tomber pour cette raison. Le durcissement reste utile ailleurs.
verifier("la lecture des plafonds ne dépend plus d'aucune migration récente",
         "role_quota_config" not in lecture and "llm_simultanes" in lecture)
verifier("elle passe par `texte()`, pas par un `.strip()` sur un réglage typé",
         "from llm.reglages import texte" in lecture and '.strip()' not in lecture)
ecriture = st.split('@router.put("/concurrence")')[1].split("@router.")[0]
verifier("l'écriture non plus", "role_quota_config" not in ecriture
         and "UPDATE users" not in ecriture)
verifier("vider le champ rend la main au défaut, il n'impose pas zéro",
         "il n'impose pas zéro" in ecriture)

gp = (BACKEND / "routers" / "google_perso.py").read_text(encoding="utf-8")
verifier("compte Google : la migration est reconnue", "schema_incomplet" in gp)
verifier("elle ne se fait PAS passer pour « pas encore relié »",
         '"migration_absente"' in gp and "MENSONGE" in gp)

sig = (BACKEND / "mail" / "signature.py").read_text(encoding="utf-8")
verifier("signature : l'enregistrement nomme sa migration",
         "030_signatures_mail.sql" in sig and "schema_incomplet" in sig)

# ── 3. L'écran le dit, au lieu d'afficher « HTTP 500 » ───────────────────
cles = (FRONTEND / "components" / "settings" / "ClesApiTab.tsx").read_text(encoding="utf-8")
carte = cles.split("function ReglageConcurrence")[1]
# La notice « migration absente » a disparu de CETTE carte avec les tableaux
# qu'elle expliquait : la carte ne lit plus la base. Ce qu'on exige désormais,
# c'est qu'elle n'ait plus aucune raison de tomber.
verifier("la carte des plafonds ne dépend plus d'une migration",
         "migration_absente" not in carte.split("export default")[0])
verifier("elle dit que le plafond vaut pour tous les comptes",
         "Tous comptes confondus" in carte)
# Le blocage exact que Noa décrivait : « je ne peux pas choisir le modèle
# Ollama ». La clé était enregistrée, mais la carte des modèles ne relisait
# jamais son catalogue — deux composants sœurs, deux états — donc `cle_presente`
# restait faux et « Appliquer » restait grisé jusqu'au rechargement de la page.
verifier("enregistrer une clé fait RELIRE le catalogue des modèles",
         "signal={clesModifiees}" in cles
         and "setClesModifiees((n) => n + 1)" in cles
         and "[charger, signal]" in cles)
verifier("le bouton reste bien conditionné à la présence d'une clé "
         "(choisir un modèle sans clé garantirait l'échec)",
         "fiche?.cle_presente" in cles)

tab = (FRONTEND / "components" / "settings" / "GoogleTab.tsx").read_text(encoding="utf-8")
verifier("l'onglet du compte Google aussi", "migration_absente" in tab)
verifier("le message d'un collaborateur ne cite aucun nom de fichier ni de table",
         re.search(r"Votre administrateur doit terminer la mise en service", tab))

# ── 4. Ce qui était DÉJÀ tolérant doit le rester ─────────────────────────
conc = (BACKEND / "llm" / "concurrence.py").read_text(encoding="utf-8")
verifier("le plafond d'un tour ne bloque JAMAIS personne (défaut du code)",
         "une limite illisible ne bloque personne" in conc)
gperso = (BACKEND / "mail" / "google_perso.py").read_text(encoding="utf-8")
verifier("le cache des connexions tolère la table absente au démarrage",
         "table absente (migration pas passée) : cache vide" in gperso)
verifier("la lecture d'une signature tolère l'absence de table",
         "une signature absente n'arrête rien" in sig)


async def _scenario_limite():
    """Le plafond se lit sans base : c'est le chemin de CHAQUE tour."""
    import types
    faux_config = types.ModuleType("config")
    faux_config.settings = types.SimpleNamespace(
        llm_simultanes=8, llm_simultanes_personne=3, llm_simultanes_fond=2,
        llm_attente_max_s=90)
    sys.modules["config"] = faux_config
    faux_reglages = types.ModuleType("llm.reglages")
    faux_reglages.valeur = lambda nom: ""
    paquet = types.ModuleType("llm")
    paquet.__path__ = []
    sys.modules.setdefault("llm", paquet)
    sys.modules["llm.reglages"] = faux_reglages
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "conc_banc", BACKEND / "llm" / "concurrence.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Aucune base n'est joignable ici : la fonction DOIT rendre le défaut.
    return await mod.limite_de("00000000-0000-0000-0000-000000000000", "direction")


verifier("EXÉCUTÉ : sans base du tout, le plafond d'un tour vaut le défaut",
         asyncio.run(_scenario_limite()) == 3)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
