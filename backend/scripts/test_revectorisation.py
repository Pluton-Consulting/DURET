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
DELAIS: list = []
ECHEC = {"sqlstate": ""}
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

    async def execute(self, sql, *a, timeout=None):
        SQL.append(" ".join(sql.split()))
        DELAIS.append((" ".join(sql.split())[:30], timeout))
        if ECHEC["sqlstate"] and sql.lstrip().startswith("ALTER"):
            e = Exception("canceling statement due to lock timeout")
            e.sqlstate = ECHEC["sqlstate"]
            raise e
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
verifier("une bascule effectuée par un autre processus est immédiatement visible",
         asyncio.run(rv.dimension_attendue()) == 768)
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
# (11/09) La liste est mémorisée, et une ligne qui doit RÉPONDRE écarte les
# modèles d'embedding de ce repli.
# (15/09) SAUF la ligne des embeddings : son repli y proposait les modèles de
# CONVERSATION d'Ollama Cloud, et « deepseek-v4-flash » a été posé chez Duret —
# plus rien ne se vectorisait. Là, le menu reste vide, le champ libre reste
# ouvert, et le serveur mesure le modèle avant de l'accepter
# (test_cause_embeddings).
verifier("un fournisseur sans modèle correspondant garde sa liste entière (hors embeddings)",
         "if (gardes.length) return { ...f, modeles: gardes }" in ecran
         and 'if (usage === "embedding") return { ...f, modeles: [] }' in ecran
         and "!sansEmbedding.length ? f.modeles : sansEmbedding" in ecran)

carte = (BACKEND.resolve().parent / "frontend" / "components" / "settings"
         / "RevectorisationCarte.tsx").read_text(encoding="utf-8")
verifier("l'écran sait demander la liste des modèles et leurs dimensions",
         "embeddings/catalogue" in carte)
verifier("il dit que les dimensions sont MESURÉES, pas déduites d'une liste",
         "pas déduites" in carte)

# ── 7. CE QU'OLLAMA CLOUD PROPOSE VRAIMENT (mesuré en production) ───────
# Sondé le 02/09 sur l'abonnement réel : 19 modèles, TOUS de texte, et
# `POST /v1/embeddings` rend « path "/v1/embeddings" not found » — un 404 sur le
# CHEMIN, pas sur le modèle. La façade compatible OpenAI d'Ollama Cloud ne
# couvre que la complétion. Le fournisseur doit donc essayer la route native
# avant de conclure, et dire quoi faire s'il n'y en a aucune.
verifier("le fournisseur essaie la route NATIVE quand /v1/embeddings est absent",
         "/api/embed" in emb)
# (15/09) Le refus de chaque route est désormais RETENU (sa réponse devient la
# cause affichée) au lieu d'être jeté ; la route suivante est essayée quand même.
verifier("un refus sur la première route n'est pas compté comme une panne",
         emb.count('refus.append(_refus_http("Ollama Cloud", r))') >= 2
         and "for tentative in (_openai_like, _native):" in emb)
verifier("`/api/embed` vit à la racine : le suffixe /v1 est RETIRÉ, pas ajouté",
         'racine = base[:-3].rstrip("/") if base.endswith("/v1") else base' in emb)
verifier("et si aucune route ne répond, le message dit vers quoi se tourner",
         "Choisissez un autre fournisseur" in emb)

arbre = ast.parse((BACKEND / "vectorstore" / "revectorisation.py").read_text(encoding="utf-8"))
noms = {n.name for n in arbre.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
verifier("le module expose ce que l'écran et le garde-fou attendent",
         {"mesurer_dimension", "dimension_attendue", "etat", "revectoriser"} <= noms,
         str(sorted(noms)))

# ── 8. « QUAND JE CLIQUE SUR RE-VECTORISER ÇA MARCHE PAS » (14/09) ─────
# L'opération tournait dans la requête HTTP, sous le délai du pool (180 s) et de
# nginx (300 s) ; son verrou pouvait attendre sans fin derrière une synchro ; et
# l'écran comparait la saisie à un nombre relu toutes les 20 s.
SQL.clear(); DELAIS.clear()
asyncio.run(rv.revectoriser(768))
verifier("EXÉCUTÉ — le verrou est borné AVANT la première écriture",
         SQL[1].startswith("SET LOCAL lock_timeout"), SQL[1])
verifier("aucune instruction de l'opération ne subit le délai du pool (180 s)",
         all(d == rv.DELAI_OPERATION_S for s, d in DELAIS if not s.startswith("SET LOCAL")),
         str(DELAIS))

msg = rv.expliquer_echec(type("E", (Exception,), {"sqlstate": "55P03"})())
verifier("un verrou refusé se dit (quelle tâche, et que rien n'est effacé)",
         "Rien n'a été effacé" in msg and "synchronisation" in msg, msg)


# Ce banc vérifie le suivi de tâche avec une préparation doublée.
# La préparation réelle et la conservation de l'ancien index sont testées sur PostgreSQL.
async def _preparer(dimension,modele,progression):
    return await rv.revectoriser(dimension,modele)
sys.modules['vectorstore.generation']=types.SimpleNamespace(preparer=_preparer)
async def _en_fond(echec=""):
    ECHEC["sqlstate"] = echec
    rv._OPERATION.clear()
    rv.lancer_en_fond(768)
    pendant = dict(rv._OPERATION)
    try:
        rv.lancer_en_fond(768)
        double = False
    except RuntimeError:
        double = True
    await rv._TACHE
    ECHEC["sqlstate"] = ""
    return pendant, double, dict(rv._OPERATION)

pendant, double, apres = asyncio.run(_en_fond())
verifier("EXÉCUTÉ — l'opération part en fond et se dit « en_cours »", pendant.get("phase") == "en_cours")
verifier("une seconde opération est refusée tant que la première tourne", double)
verifier("elle se termine « terminee » avec le compte en file",
         apres.get("phase") == "terminee" and apres.get("morceaux_en_file") == 9427, str(apres))

pendant, double, apres = asyncio.run(_en_fond("55P03"))
verifier("EXÉCUTÉ — un échec en fond laisse sa cause lisible à l'écran",
         apres.get("phase") == "echec" and "Rien n'a été effacé" in apres.get("erreur", ""), str(apres))
verifier("et la transaction est annulée (ROLLBACK), rien d'effacé", SQL[-1] == "ROLLBACK", SQL[-1])

rv._OPERATION.clear(); rv._OPERATION.update(phase="en_cours", dimension=768, debut=0)
rv._DERNIER_ETAT.clear(); rv._DERNIER_ETAT.update(morceaux=9427, vectorises=0)
SQL.clear()
e = asyncio.run(rv.etat())
verifier("pendant l'opération, l'état ne relit pas la table verrouillée",
         SQL == [] and e["operation"]["phase"] == "en_cours" and e["morceaux"] == 9427, str(SQL))
rv._OPERATION.clear()
verifier("hors opération, l'état porte `operation` (vide)", asyncio.run(rv.etat())["operation"] is None)

reglages = (BACKEND / "routers" / "settings.py").read_text(encoding="utf-8")
verifier("la route LANCE en fond et répond tout de suite",
         "rv.lancer_en_fond(mesuree, choisi)" in reglages and "await rv.revectoriser(" not in reglages)
emb = (BACKEND / "vectorstore" / "embeddings.py").read_text(encoding="utf-8")
verifier("une mesure muette dit sa cause quand on la sait (pause de quota Gemini)",
         "def raison_du_silence" in emb and "pause de quota" in emb
         and "raison_du_silence(modele)" in (BACKEND / "vectorstore" / "revectorisation.py").read_text(encoding="utf-8"))
verifier("embed_texts et la cause regardent le MÊME choix de fournisseur",
         "fournisseur_choisi(modele_force)" in emb.split("async def embed_texts")[1])

carte = (BACKEND.resolve().parent / "frontend" / "components" / "settings"
         / "RevectorisationCarte.tsx").read_text(encoding="utf-8")
verifier("le nombre à recopier est FIGÉ à l'ouverture", "attenduFige" in carte
         and "setAttenduFige(String(etat.morceaux))" in carte)
verifier("la saisie se compare en chiffres (« 9 427 » accepté)", "chiffres(confirme) === attendu" in carte)
verifier("un bouton grisé dit pourquoi", "Re-vectorisation indisponible" in carte)
verifier("ouvrir la confirmation re-mesure d'abord", "onClick={ouvrir}" in carte and "await relire()" in carte)
verifier("l'écran suit l'opération en fond et affiche la cause d'un échec",
         'operation?.phase === "echec"' in carte and "operation.erreur" in carte)

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
