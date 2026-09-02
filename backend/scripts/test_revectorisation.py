"""
Banc « re-vectoriser le corpus » — 02/09.

Demande de Noa, citant l'avertissement que l'écran affichait déjà : « Changer de
modèle impose de re-vectoriser tout le corpus : les vecteurs existants (1536
dimensions) ne se comparent pas à ceux d'un autre modèle. Un modèle qui rend une
autre dimension est refusé à l'écriture, sans rien casser. » — « fais ça ».

L'écran ANNONÇAIT donc l'opération sans permettre de la faire : l'avertissement
était exact et sans issue, ce qui revenait à interdire tout changement de
modèle. Mesuré en production le même jour : 9 427 morceaux, 2 913 vectorisés,
6 514 en attente derrière un quota Gemini épuisé en permanence.

TROIS DÉFAUTS TROUVÉS EN CHEMIN, tous dans le code du 01/09 non déployé :

  · `modele_choisi` était calculé PUIS JETÉ dans `embed_texts` : seul le
    fournisseur comptait, chaque fonction reprenant le modèle par défaut de la
    configuration. Choisir « ollama_cloud:embeddinggemma » vectorisait avec un
    autre modèle que celui affiché, sans que rien ne le dise.
  · LE FOURNISSEUR `ollama_cloud` N'EXISTAIT PAS dans `_PROVIDERS` : le
    fournisseur `ollama` vise l'instance LOCALE, absente des serveurs. Choisir
    Ollama Cloud pour les embeddings était donc impossible.
  · LE GARDE-FOU D'ÉCRITURE lisait `settings.embedding_dimensions`, valeur du
    fichier de configuration. Après une re-vectorisation vers 768, elle serait
    restée à 1536 et aurait fait refuser TOUS les vecteurs du nouveau modèle,
    en accusant le modèle alors que la base était d'accord avec lui.

Le banc EXÉCUTE le module contre une base doublée : aucune connexion, aucun
réseau. Ce qu'il vérifie surtout, c'est l'ORDRE des opérations SQL, parce qu'un
ALTER avant le DROP de l'index est refusé par Postgres et qu'on ne s'en
apercevrait qu'en production, sur un corpus déjà vidé.
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


print(f"\n═══ RE-VECTORISER LE CORPUS — {BACKEND.resolve().parent}\n")

# ── La base doublée ──────────────────────────────────────────────────────
SQL: list = []
COLONNE = {"valeur": "vector(1536)"}


class _Tx:
    async def __aenter__(self):
        SQL.append("BEGIN")
        return self

    async def __aexit__(self, *x):
        SQL.append("COMMIT" if x[0] is None else "ROLLBACK")
        return False


class _Conn:
    def transaction(self):
        return _Tx()

    async def execute(self, sql, *a):
        SQL.append(" ".join(sql.split()))
        return "INSERT 0 3"

    async def fetchval(self, sql, *a):
        SQL.append(" ".join(sql.split()))
        if "format_type" in sql:
            return COLONNE["valeur"]
        return 9427

    async def fetchrow(self, sql, *a):
        return {"total": 9427, "vectorises": 2913}

    async def fetch(self, sql, *a):
        if "format_type" in sql:
            return [{"table": "documents", "type": COLONNE["valeur"]},
                    {"table": "conversation_memoire", "type": COLONNE["valeur"]}]
        return [{"status": "pending", "n": 6514}, {"status": "completed", "n": 2913}]


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *x):
        return False


faux_db = types.ModuleType("database.connection")
faux_db.get_db = lambda: _Db()
paquet = types.ModuleType("database")
paquet.__path__ = []
sys.modules.setdefault("database", paquet)
sys.modules["database.connection"] = faux_db

faux_config = types.ModuleType("config")
faux_config.settings = types.SimpleNamespace(embedding_dimensions=1536)
sys.modules["config"] = faux_config

# Le producteur de vecteurs est doublé : on mesure la MÉCANIQUE, pas un modèle.
DIMENSION_RENDUE = {"n": 768}
faux_embed = types.ModuleType("vectorstore.embeddings")


# La doublure suit la signature du module livré : `modele_force` permet de
# MESURER un modèle sans le poser en réglage, ce qui est tout l'intérêt du
# catalogue (on mesure, on montre, puis on choisit).
MODELE_ESSAYE = {"dernier": ""}


async def _embed(textes, modele_force=""):
    MODELE_ESSAYE["dernier"] = modele_force
    n = DIMENSION_RENDUE["n"]
    return [[0.0] * n if n else None for _ in textes]


faux_embed.embed_texts = _embed
paquet_vs = types.ModuleType("vectorstore")
paquet_vs.__path__ = []
sys.modules.setdefault("vectorstore", paquet_vs)
sys.modules["vectorstore.embeddings"] = faux_embed

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "revect_banc", BACKEND / "vectorstore" / "revectorisation.py")
rv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rv)

# ── 1. LA DIMENSION SE MESURE ────────────────────────────────────────────
n, detail = asyncio.run(rv.mesurer_dimension())
verifier("EXÉCUTÉ — la dimension vient d'un vrai appel au modèle", n == 768, str(n))
verifier("et l'écran reçoit de quoi la lire", "768 dimensions" in detail)

DIMENSION_RENDUE["n"] = 0
n, detail = asyncio.run(rv.mesurer_dimension())
verifier("un modèle muet ne rend PAS une dimension supposée", n is None)
verifier("et la cause est dite, pas devinée", "aucun vecteur" in detail)

DIMENSION_RENDUE["n"] = 4
n, detail = asyncio.run(rv.mesurer_dimension())
verifier("quatre valeurs ne sont pas un embedding : refusé", n is None)
verifier("le message oriente vers le vrai coupable (le nom du modèle)",
         "nom du modèle" in detail)

DIMENSION_RENDUE["n"] = 3072
n, detail = asyncio.run(rv.mesurer_dimension())
verifier("une dimension trop grande est ACCEPTÉE mais annoncée", n == 3072)
verifier("l'écran est prévenu que l'index HNSW ne se construira pas",
         "index HNSW" in detail)

DIMENSION_RENDUE["n"] = 1024
asyncio.run(rv.mesurer_dimension("ollama_cloud:bge-m3"))
verifier("EXÉCUTÉ — mesurer un modèle NOMMÉ l'essaie vraiment "
         "(le paramètre était ignoré)",
         MODELE_ESSAYE["dernier"] == "ollama_cloud:bge-m3",
         repr(MODELE_ESSAYE["dernier"]))
DIMENSION_RENDUE["n"] = 768

# ── 2. LA DIMENSION ATTENDUE VIENT DE LA COLONNE ─────────────────────────
rv.oublier_dimension()
verifier("EXÉCUTÉ — la dimension attendue est LUE dans la base",
         asyncio.run(rv.dimension_attendue()) == 1536)
COLONNE["valeur"] = "vector(768)"
verifier("elle est mise en cache (une lecture par écriture serait payée 9 400 fois)",
         asyncio.run(rv.dimension_attendue()) == 1536)
rv.oublier_dimension()
verifier("et le cache s'oublie, sinon une re-vectorisation ne prendrait effet "
         "qu'au redémarrage",
         asyncio.run(rv.dimension_attendue()) == 768)
COLONNE["valeur"] = "vector(1536)"
rv.oublier_dimension()

# ── 3. L'OPÉRATION, ET SURTOUT SON ORDRE ─────────────────────────────────
SQL.clear()
res = asyncio.run(rv.revectoriser(768))
trace = "\n".join(SQL)


def rang(motif, depuis=0):
    for i, s in enumerate(SQL):
        if i >= depuis and motif in s:
            return i
    return -1


verifier("tout se fait dans UNE transaction", SQL[0] == "BEGIN" and SQL[-1] == "COMMIT",
         f"{SQL[0]} … {SQL[-1]}")
verifier("LES DEUX tables de vecteurs sont vidées, pas seulement le corpus",
         "UPDATE documents SET embedding = NULL" in trace
         and "UPDATE conversation_memoire SET embedding = NULL" in trace)
verifier("l'index tombe AVANT le changement de type (Postgres le refuse sinon)",
         rang("DROP INDEX") < rang("ALTER TABLE documents"),
         f"drop={rang('DROP INDEX')} alter={rang('ALTER TABLE documents')}")
verifier("les vecteurs sont vidés AVANT le changement de type",
         rang("UPDATE documents SET embedding = NULL") < rang("ALTER TABLE documents"))
verifier("les DEUX colonnes changent de dimension",
         "ALTER TABLE documents ALTER COLUMN embedding TYPE vector(768)" in trace
         and "ALTER TABLE conversation_memoire ALTER COLUMN embedding TYPE vector(768)" in trace)
verifier("l'index est recréé APRÈS", rang("CREATE INDEX") > rang("ALTER TABLE documents"))
verifier("il est recréé en HNSW cosinus, comme la migration 027",
         "USING hnsw (embedding vector_cosine_ops)" in trace)

verifier("tout le corpus retourne en file", "SET status = 'pending'" in trace)
# LE PIÈGE LE PLUS COÛTEUX. `max_attempts` vaut 3 : un job qui a épuisé ses
# essais sous l'ancien modèle ne serait JAMAIS repris, et son morceau resterait
# invisible à la recherche pour toujours, sans que rien ne le signale.
verifier("ET LEURS ESSAIS REPARTENT DE ZÉRO (sinon un job épuisé ne repart pas)",
         "attempts = 0" in trace)
verifier("l'erreur précédente est effacée : elle ne concerne plus ce modèle",
         "error_message = NULL" in trace)
verifier("les morceaux sans job en reçoivent un (file et corpus peuvent diverger)",
         "INSERT INTO embedding_jobs" in trace and "NOT EXISTS" in trace)

verifier("le compte rendu dit combien de morceaux sont en file",
         res["morceaux_en_file"] == 9427, str(res))
verifier("et si l'index a pu être recréé", res["index_recree"] is True)

# Dimension trop grande : l'opération se fait, l'index non — et on le DIT.
SQL.clear()
res = asyncio.run(rv.revectoriser(3072))
verifier("au-delà de la limite d'indexation, l'opération réussit quand même",
         res["dimension"] == 3072)
verifier("mais l'index n'est PAS recréé, et le compte rendu le dit",
         res["index_recree"] is False
         and "CREATE INDEX" not in "\n".join(SQL))

for mauvaise in (0, 12, -5, "768"):
    try:
        asyncio.run(rv.revectoriser(mauvaise))
        refuse = False
    except (ValueError, TypeError):
        refuse = True
    verifier(f"une dimension invalide ({mauvaise!r}) est refusée AVANT d'effacer",
             refuse)

# ── 4. CE QUI ENTOURE : le garde-fou, le fournisseur, la route ───────────
client = (BACKEND / "vectorstore" / "client.py").read_text(encoding="utf-8")
verifier("le garde-fou d'écriture lit la COLONNE, plus la configuration figée",
         "await dimension_attendue()" in client
         and 'getattr(settings, "embedding_dimensions"' not in client)

emb = (BACKEND / "vectorstore" / "embeddings.py").read_text(encoding="utf-8")
verifier("LE MODÈLE CHOISI atteint enfin le fournisseur (il était jeté)",
         "await provider(unique_texts, modele_choisi)" in emb)
verifier("chaque fournisseur sait recevoir un modèle",
         emb.count("modele: str = \"\"") >= 4)
verifier("le fournisseur `ollama_cloud` existe (il manquait)",
         '"ollama_cloud": _embed_ollama_cloud' in emb)
verifier("il est DISTINCT de l'Ollama local, qui vise une autre adresse",
         "ollama_cloud_base_url" in emb and "ollama_base_url" in emb)
verifier("sa clé passe par le cache de `llm.cles`, pas par la configuration seule",
         "from llm.cles import valeur" in emb)
verifier("les vecteurs sont replacés par leur `index`, pas par leur position",
         'item.get("index")' in emb)

reglages = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
verifier("une route LIT l'état sans rien modifier",
         '@router.get("/embeddings")' in reglages)
verifier("une autre LANCE l'opération, réservée à l'administration",
         '@router.post("/embeddings/revectoriser")' in reglages
         and reglages.count('has_permission(current_user.role, "manage_system")') >= 2)
# LA DIMENSION EST RE-MESURÉE AVANT D'EFFACER : celle de l'écran peut dater de
# plusieurs minutes, et deux administrateurs peuvent regarder deux modèles.
verifier("la dimension est RE-MESURÉE avant d'effacer, pas reprise de l'écran",
         "mesuree != body.dimension" in reglages)
verifier("un désaccord annule tout et le dit clairement",
         "Rien n'a été effacé" in reglages)
verifier("l'opération laisse une trace d'audit",
         'action="revectorisation_lancee"' in reglages)

# ── 5. CE QUE LA LECTURE RISQUAIT, ET QUE L'ÉCRAN NIAIT ─────────────────
# L'avertissement affiché promettait « refusé à l'écriture, sans rien casser ».
# L'écriture était bien protégée ; la LECTURE ne l'était pas : les deux voies de
# `rechercher()` partageaient un même `try`, et le cast `::vector` d'un
# embedding mal dimensionné faisait rendre VIDE — pas dégradé, vide.
rag = (BACKEND / "vectorstore" / "rag.py").read_text(encoding="utf-8")
verifier("la voie vectorielle a son PROPRE filet : la lexicale lui survit",
         "Voie vectorielle écartée" in rag)
verifier("un embedding mal dimensionné est écarté AVANT l'aller-retour SQL",
         "len(embedding) != attendue" in rag)
verifier("la voie lexicale est appelée hors du filet de la vectorielle",
         rag.index("voies[\"texte\"]") > rag.index("Voie vectorielle écartée"))
verifier("le désaccord se dit UNE fois, pas à chaque requête",
         "_DIMENSION_DITE" in rag and "if (rendue, attendue) in _DIMENSION_DITE" in rag)
verifier("et le message nomme le geste qui répare",
         "Re-vectorisez le corpus" in rag)

# LE PIÈGE LE PLUS VICIEUX : `google` est le nom du fournisseur dans la cascade
# de texte et dans le catalogue de l'écran ; le moteur d'embedding l'appelle
# `gemini`. Le choix le plus naturel de l'écran coupait donc la vectorisation.
reg = (BACKEND / "llm" / "reglages.py").read_text(encoding="utf-8")
verifier("les embeddings ont leur PROPRE liste de fournisseurs",
         "FOURNISSEURS_EMBEDDING" in reg)
verifier("elle est celle qu'on applique à `modele_embedding`",
         'admis = (FOURNISSEURS_EMBEDDING if nom == "modele_embedding"' in reg)
verifier("un fournisseur de TEXTE seul n'y figure pas (longcat ne vectorise pas)",
         "longcat" not in reg.split("FOURNISSEURS_EMBEDDING = (")[1].split(")")[0])
verifier("« google » y est admis : c'est le nom que l'écran affiche",
         '"google"' in reg.split("FOURNISSEURS_EMBEDDING = (")[1].split(")")[0])
verifier("et le moteur le ramène à gemini, sans quoi il resterait inconnu",
         '"google": _embed_gemini' in emb)

# ── 6. LE CATALOGUE : « quels modèles ai-je ? » ─────────────────────────
# Aucune liste écrite à la main ne peut répondre : cela dépend de l'abonnement,
# cela change, et la dimension — qui décide de tout — n'est annoncée par aucun
# catalogue de fournisseur. On la mesure, modèle par modèle.
routeur = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")
verifier("le serveur déduit l'USAGE d'un modèle (embedding, vision, texte)",
         "def usage_du_modele" in routeur)
verifier("et chaque modèle du catalogue le porte", '"usage": usage_du_modele(m)' in routeur)
verifier("l'embedding est testé AVANT la vision (qwen3-embedding porte les deux "
         "familles de marques)",
         routeur.index("_MARQUES_EMBEDDING") < routeur.index("_MARQUES_VISION"))
verifier("le module rend un catalogue d'embeddings avec leurs dimensions",
         "async def catalogue_embeddings" in
         (BACKEND / "vectorstore" / "revectorisation.py").read_text(encoding="utf-8"))
verifier("il est en cache : un appel par modèle à chaque affichage serait payé "
         "pour rien",
         "_CATALOGUE_EXPIRE" in (BACKEND / "vectorstore" / "revectorisation.py")
         .read_text(encoding="utf-8"))
verifier("une route l'expose, réservée à l'administration",
         '@router.get("/embeddings/catalogue")' in reglages)

ecran = (BACKEND.resolve().parent / "frontend" / "components" / "settings"
         / "ClesApiTab.tsx").read_text(encoding="utf-8")
verifier("les lignes Vision et Embeddings ne proposent que leurs modèles",
         'titre="Vision et OCR" usage="vision"' in ecran
         and 'titre="Embeddings" usage="embedding"' in ecran)
# LE FILTRE NE DOIT PAS ENFERMER. L'usage est déduit d'un NOM : l'heuristique
# peut se tromper, et un menu vide empêcherait de choisir un modèle qu'on sait
# bon. Un fournisseur sans correspondance garde donc sa liste entière.
verifier("un fournisseur sans modèle correspondant garde sa liste entière",
         "gardes.length ? { ...f, modeles: gardes } : f" in ecran)

carte = (BACKEND.resolve().parent / "frontend" / "components" / "settings"
         / "RevectorisationCarte.tsx").read_text(encoding="utf-8")
verifier("l'écran sait demander la liste des modèles et leurs dimensions",
         "embeddings/catalogue" in carte)
verifier("il dit que les dimensions sont MESURÉES, pas déduites d'une liste",
         "pas déduites" in carte)

arbre = ast.parse((BACKEND / "vectorstore" / "revectorisation.py").read_text(encoding="utf-8"))
noms = {n.name for n in arbre.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
verifier("le module expose ce que l'écran et le garde-fou attendent",
         {"mesurer_dimension", "dimension_attendue", "etat", "revectoriser"} <= noms,
         str(sorted(noms)))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
