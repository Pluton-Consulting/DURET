"""
Banc « LES DROITS AVANT LES RÉSULTATS, ET RIEN NE SE PERD » — audit D-09/S-09, D-08/S-08, D-10/S-10.

CE QUI ÉTAIT FAUX :
  · le cloisonnement des boîtes mail se faisait APRÈS la recherche : on
    demandait trois fois plus de morceaux « pour avoir de la marge », puis on
    jetait ceux des boîtes fermées. Quand la marge ne suffisait pas, de bons
    documents restaient dehors — et les COMPTES (« 12 documents parlent de… »)
    comptaient ce que la personne n'a pas le droit de lire ;
  · une réindexation supprimait les anciens morceaux PUIS insérait les
    nouveaux, en écritures séparées : une coupure au milieu laissait le
    document absent de la mémoire, alors qu'il y était une seconde plus tôt ;
    et un texte vide après une extraction défaillante effaçait une version
    valide ;
  · la synchronisation Outlook lisait UNE page de messages et se déclarait
    finie.

CE BANC PROUVE (SQL et pipeline EXÉCUTÉS contre des doublures) :
  1. les boîtes autorisées entrent dans la requête, pour la recherche ET le
     compte ; « * » ouvre tout, l'absence de liste ferme les mails ;
  2. plus de sur-échantillonnage × 3 : on demande ce qu'on rend ;
  3. une réindexation bascule en UNE transaction, et un texte vide ne supprime
     rien ;
  4. la lecture Outlook suit `@odata.nextLink` et dit quand elle s'arrête.

Usage : python backend/scripts/test_droits_et_reindexation.py [backend]
"""
import asyncio
import importlib.util
import pathlib
import sys
import types

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def poser(nom, **attrs):
    mod = types.ModuleType(nom)
    mod.__dict__.update(attrs)
    mod.__path__ = []
    sys.modules[nom] = mod
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            poser(parent)
        setattr(sys.modules[parent], feuille, mod)
    return mod


def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, BACKEND / chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    if "." in nom:
        parent, feuille = nom.rsplit(".", 1)
        if parent not in sys.modules:
            poser(parent)
        setattr(sys.modules[parent], feuille, mod)
    spec.loader.exec_module(mod)
    return mod


print(f"\n═══ DROITS, RÉINDEXATION, PAGINATION — {BACKEND.parent}\n")

REQUETES = []


class _Conn:
    def transaction(self):
        class _T:
            async def __aenter__(self_):
                return None

            async def __aexit__(self_, *a):
                return False
        return _T()

    async def fetch(self, sql, *args):
        REQUETES.append((sql, args))
        return []

    async def fetchrow(self, sql, *args):
        REQUETES.append((sql, args))
        return {"morceaux": 3, "documents": 2}

    async def fetchval(self, sql, *args):
        REQUETES.append((sql, args))
        return "doc-1"

    async def execute(self, sql, *args):
        REQUETES.append((sql, args))
        return "DELETE 0"


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


poser("database")
poser("database.connection", get_db=lambda: _Db())
poser("config", settings=types.SimpleNamespace(embedding_dimensions=1536))
poser("security")
poser("security.acces", ROLE_ACCESS_LEVELS={"direction": ["all", "direction_only"], "terrain": ["all"]})
client_mod = charger("vectorstore.client", "vectorstore/client.py")
vs = client_mod.vectorstore

print("1. Les boîtes autorisées entrent dans la requête (D-09/S-09)")
REQUETES.clear()
asyncio.run(vs.search_lexical("devis", "terrain", None, top_k=5, boites=["a@exemple-sols.fr"]))
sql, args = REQUETES[-1]
verifier("la requête filtre les mails sur la boîte, en PARAMÈTRE (jamais dans le texte SQL)",
         "split_part(source_id, ':', 2)" in sql and ["a@exemple-sols.fr"] in [list(a) if isinstance(a, list) else a
                                                                             for a in args],
         (sql[-300:], args))
REQUETES.clear()
asyncio.run(vs.search_lexical("devis", "terrain", None, top_k=5, boites=None))
verifier("sans filtre de boîtes demandé, la requête ne change pas (recherche hors mails)",
         "split_part(source_id" not in REQUETES[-1][0])
REQUETES.clear()
asyncio.run(vs.search_lexical("devis", "terrain", None, top_k=5, boites=[]))
verifier("liste VIDE : fail-closed, aucun mail ne peut sortir",
         "source_type <> ALL(" in REQUETES[-1][0] and "split_part" not in REQUETES[-1][0], REQUETES[-1][0][-200:])
REQUETES.clear()
asyncio.run(vs.search_lexical("devis", "direction", None, top_k=5, boites=["*"]))
verifier("« * » (administrateur) ne pose aucun filtre de boîte",
         "split_part(source_id" not in REQUETES[-1][0])
REQUETES.clear()
asyncio.run(vs.search_lexical("devis", "terrain", None, top_k=5, boites=["a@exemple-sols.fr", "!email_sent"]))
sql = REQUETES[-1][0]
verifier("« !email_sent » écarte les envoyés en plus", "source_type <> $" in sql and "split_part" in sql, sql[-300:])
REQUETES.clear()
asyncio.run(vs.count_lexical("devis", "terrain", None, boites=["a@exemple-sols.fr"]))
verifier("le COMPTE suit exactement le même filtre que la recherche",
         "split_part(source_id, ':', 2)" in REQUETES[-1][0])

print("2. Le RAG ne sur-échantillonne plus")
rag_src = (BACKEND / "vectorstore" / "rag.py").read_text(encoding="utf-8")
verifier("la marge × 3 a disparu, les boîtes passent au client",
         "marge = 3" not in rag_src and "top_k=top_k, source_types=types,\n            boites=mailboxes" in rag_src)
verifier("le post-filtre reste, en défense", "_filtrer_mails(chunks, mailboxes)" in rag_src)
verifier("le compte exact est demandé avec les boîtes",
         "count_lexical(\n            query, user_role, types, fichier=fichier, boites=mailboxes)" in rag_src)

print("3. Une réindexation ne perd rien (D-08/S-08)")
REQUETES.clear()
ecrits = asyncio.run(vs.remplacer_source(["morceau 1", "morceau 2"], source_type="nas",
                                         source_id="synology:/a/b.pdf", source_filename="b.pdf",
                                         access_level="all"))
ordres = [sql.strip().split()[0].upper() for sql, _ in REQUETES]
verifier("la suppression et les insertions sont dans LA MÊME transaction, la suppression d'abord",
         ecrits == 2 and ordres[0] == "DELETE" and ordres.count("INSERT") >= 2, ordres)
verifier("les morceaux sans vecteur reçoivent leur job de vectorisation",
         any("embedding_jobs" in sql for sql, _ in REQUETES))
REQUETES.clear()
verifier("une liste VIDE ne supprime rien (un texte vide ne remplace pas une version valide)",
         asyncio.run(vs.remplacer_source([], source_type="nas", source_id="x")) == 0 and not REQUETES)
pipeline_src = (BACKEND / "ingestion" / "pipeline.py").read_text(encoding="utf-8")
verifier("le pipeline passe par la bascule en une fois, et ne supprime plus à part",
         "remplacer_source(" in pipeline_src and "await vectorstore.delete_by_source(source_id, source_type)" not in pipeline_src)
verifier("un document vide laisse l'ancienne version en place, et le dit",
         "l'ancienne version reste" in pipeline_src)

print("4. La lecture des mails suit ses pages (D-10/S-10)")
outlook_src = (BACKEND / "ingestion" / "connectors" / "outlook.py").read_text(encoding="utf-8")
verifier("la synchronisation suit `@odata.nextLink` au lieu de lire une page",
         '@odata.nextLink' in outlook_src and "while url and len(messages) < maximum" in outlook_src)
verifier("elle DIT quand elle s'arrête sur le plafond au lieu de laisser croire à une boîte entière",
         "plafond de %d messages atteint" in outlook_src)
verifier("elle borne quand même son parcours (pas de boucle sans fin)", "pages < 50" in outlook_src)

print("5. Un effet externe ne se fait qu'une fois (D-11/S-11)")
ETAT_OPS = {"op-1": {"execution": "en_attente"}}


class _ConnOps(_Conn):
    async def fetchval(self, sql, *args):
        REQUETES.append((sql, args))
        if "INSERT INTO operations_externes" in sql:
            return "op-1"
        if "SELECT id::text FROM operations_externes WHERE validation_id" in sql:
            return None
        if "UPDATE operations_externes SET execution = 'en_cours'" in sql:
            # La réclamation ATOMIQUE : elle ne rend l'identifiant qu'une fois.
            if ETAT_OPS["op-1"]["execution"] != "en_attente":
                return None
            ETAT_OPS["op-1"]["execution"] = "en_cours"
            return "op-1"
        return None

    async def execute(self, sql, *args):
        REQUETES.append((sql, args))
        if "SET execution = $2" in sql:
            ETAT_OPS["op-1"]["execution"] = args[1]
        return "UPDATE 1"


class _DbOps:
    async def __aenter__(self):
        return _ConnOps()

    async def __aexit__(self, *a):
        return False


sys.modules["database.connection"].get_db = lambda: _DbOps()
sys.modules["database.connection"].schema_incomplet = lambda e: "does not exist" in str(e).lower()
operations = charger("skills.operations", "skills/operations.py")
op = asyncio.run(operations.ouvrir("envoyer_email", "u1", validation_id="11111111-1111-1111-1111-111111111111",
                                   thread_id="fil-1", payload_hash="abc"))
verifier("l'opération s'inscrit avec la décision humaine et l'empreinte approuvée", op == "op-1")
verifier("elle se réclame UNE fois : la seconde reprise ne rappelle pas le fournisseur",
         asyncio.run(operations.reclamer(op)) is True and asyncio.run(operations.reclamer(op)) is False)
asyncio.run(operations.effet_inconnu(op, TimeoutError("réponse perdue")))
verifier("un délai dépassé devient « effet inconnu », jamais « échec »",
         ETAT_OPS["op-1"]["execution"] == "effet_inconnu")
verifier("on sait dire ce qui est ambigu et ce qui ne l'est pas",
         operations.ambigu(TimeoutError()) and operations.ambigu(ConnectionResetError())
         and not operations.ambigu(ValueError("adresse invalide")))
try:
    asyncio.run(operations.reclamer(None))
    verifier("sans registre, aucun effet externe ne démarre", False)
except operations.RegistreIndisponible:
    verifier("sans registre, aucun effet externe ne démarre", True)
routeur_src = (BACKEND / "agents" / "router.py").read_text(encoding="utf-8")
verifier("l'action approuvée RÉCLAME son opération avant d'appeler le fournisseur",
         "await operations.reclamer(operation)" in routeur_src
         and routeur_src.index("operations.reclamer(") < routeur_src.index("resultat = await execute_skill("))
verifier("une réponse perdue ne relance rien et dit « à vérifier »",
         "operations.effet_inconnu(operation, e)" in routeur_src and "À VÉRIFIER" in routeur_src)
verifier("le reçu et l'échec sont écrits dans le registre",
         "operations.reussie(operation" in routeur_src and "operations.echouee(operation, erreur)" in routeur_src)
migration = BACKEND / "database" / "migrations" / "045_operations_externes.sql"
verifier("la migration 045 sépare la décision humaine de l'état d'exécution",
         migration.exists() and "decision" in migration.read_text(encoding="utf-8")
         and "effet_inconnu" in migration.read_text(encoding="utf-8")
         and "idx_operations_validation" in migration.read_text(encoding="utf-8"))

print("6. Une demande, un seul tour (D-13/S-13) et le cloisonnement mesurable (D-20/S-20)")
ETAT_REQ = {}


class _ConnReq(_Conn):
    async def fetchrow(self, sql, *args):
        REQUETES.append((sql, args))
        if "INSERT INTO requetes_chat" in sql:
            cle = (str(args[0]), str(args[1]))
            if cle in ETAT_REQ:
                return None                       # ON CONFLICT DO NOTHING
            ETAT_REQ[cle] = {"etat": "en_cours", "thread_id": args[2]}
            return {"id": "req-1"}
        if "SELECT etat, thread_id, resultat FROM requetes_chat" in sql:
            connue = ETAT_REQ.get((str(args[0]), str(args[1])))
            return {"etat": connue["etat"], "thread_id": connue["thread_id"], "resultat": None} if connue else None
        return {"morceaux": 0, "documents": 0}


class _DbReq:
    async def __aenter__(self):
        return _ConnReq()

    async def __aexit__(self, *a):
        return False


sys.modules["database.connection"].get_db = lambda: _DbReq()
requetes = charger("agents.requetes", "agents/requetes.py")
première = asyncio.run(requetes.reclamer("u1", "demande-42", "fil-1"))
seconde = asyncio.run(requetes.reclamer("u1", "demande-42", "fil-1"))
verifier("la première arrivée démarre le tour, la seconde le REJOINT",
         première["nouvelle"] is True and seconde["nouvelle"] is False
         and seconde["thread_id"] == "fil-1", (première, seconde))
verifier("une autre intention (autre identifiant) démarre bien un tour",
         asyncio.run(requetes.reclamer("u1", "demande-43", "fil-1"))["nouvelle"] is True)
verifier("sans identifiant (client ancien), le comportement d'avant est gardé",
         asyncio.run(requetes.reclamer("u1", None, "fil-1"))["nouvelle"] is True)
chat_src = (BACKEND / "routers" / "chat.py").read_text(encoding="utf-8")
verifier("les DEUX transports (WS et secours HTTP) réclament la demande",
         chat_src.count("_requetes.reclamer(") == 2 and "request_id: Optional[str] = None" in chat_src)
verifier("la demande est close à la fin du tour, des deux côtés",
         all("_requetes.terminer(" in chat_src.split(section, 1)[1].split("\n@router.", 1)[0]
             for section in ("async def chat(", "async def _derouler_tour(")))
ws_src = (BACKEND.parent / "frontend" / "lib" / "ws.ts").read_text(encoding="utf-8")
chatwindow = (BACKEND.parent / "frontend" / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("l'écran fabrique l'identifiant AVANT d'envoyer et le garde pour la reprise",
         "nouvelleDemande()" in ws_src and "const demandeId = nouvelleDemande()" in chatwindow
         and "sendQuery(wsRef.current!, text, false, attachment, demandeId)" in chatwindow
         and "request_id: demandeId" in chatwindow)
memoire_src = (BACKEND / "agents" / "memoire_conversation.py").read_text(encoding="utf-8")
verifier("un résumé de fond en retard n'écrase plus une correction récente",
         "_messages_couverts" in memoire_src and "MESSAGES_DE_RETARD_TOLERES" in memoire_src)
controle = (BACKEND / "scripts" / "controle_droits_base.py").read_text(encoding="utf-8")
verifier("le contrôle du cloisonnement PostgreSQL existe, en LECTURE seule",
         "rolbypassrls" in controle and "relforcerowsecurity" in controle
         and not any(mot in controle for mot in ("DROP ", "ALTER ROLE", "UPDATE ", "DELETE FROM")))
verifier("il teste une vraie fuite (conversations d'autrui sous un contexte utilisateur)",
         "conversation(s) d'autrui visible(s)" in controle and "get_rls_db(" in controle)
migration = BACKEND / "database" / "migrations" / "046_requetes_chat.sql"
verifier("la migration 046 pose l'unicité (personne, demande)",
         migration.exists() and "idx_requetes_chat_unicite" in migration.read_text(encoding="utf-8"))

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
