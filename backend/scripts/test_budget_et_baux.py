"""
Banc « LE TEMPS SE COMPTE, LES JOBS SE RÉCLAMENT » — audit D-16/S-16 et D-17/S-17.

CE QUI ÉTAIT FAUX :
  · chaque étage avait son délai (routeur, candidats, tentatives, outils,
    relecteur) et personne ne regardait l'heure de la DEMANDE : des tours de
    trois minutes faits de délais tous « raisonnables » ;
  · quand toute la cascade était écartée, on la retentait ENTIÈREMENT dans la
    même demande — cinq fournisseurs morts × leurs délais, payés avant de
    conclure « aucun modèle disponible » ;
  · les jobs de vectorisation se prenaient par un simple SELECT : deux workers
    pouvaient faire le même, payer deux fois, et le plus lent écrasait l'autre ;
  · un vecteur ne disait pas avec QUEL modèle il avait été calculé — deux
    modèles de même dimension ne partagent pourtant pas le même espace.

CE BANC PROUVE (modules EXÉCUTÉS, SQL doublé) :
  1. le budget d'une demande : temps restant, délai borné, jamais zéro ;
  2. les pannes sont classées (configuration / quota / réseau) et l'on sait ce
     qui mérite un nouvel essai ;
  3. demi-ouverture : un seul candidat rouvert quand tout est écarté ;
  4. les jobs se réclament avec un bail (FOR UPDATE SKIP LOCKED) et le résultat
     d'un bail perdu est ignoré ;
  5. le modèle d'embedding est écrit à côté du vecteur.

Usage : python backend/scripts/test_budget_et_baux.py [backend]
"""
import asyncio
import importlib.util
import pathlib
import sys
import time
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


print(f"\n═══ BUDGET DE TEMPS ET BAUX DE VECTORISATION — {BACKEND.parent}\n")

print("1. Le budget d'une demande")
budget = charger("llm.budget", "llm/budget.py")
b = budget.Budget(10, debut=time.monotonic() - 4)
verifier("il reste ce qui n'a pas été consommé", 5.5 < b.restant() < 6.5, b.restant())
verifier("une étape ne peut pas durer plus que ce qui reste", b.delai(30) <= b.restant() + 0.01)
verifier("elle garde ce qu'elle demande quand il y a la place", abs(b.delai(2) - 2) < 0.01)
epuise = budget.Budget(5, debut=time.monotonic() - 9)
verifier("un budget épuisé le dit", epuise.expire() and epuise.restant() == 0)
verifier("un budget épuisé interdit un délai supplémentaire",
         epuise.delai(10) == 0.0)
verifier("on sait dire si une étape a encore la place", b.assez_pour(3) and not b.assez_pour(60))

print("2. Les pannes classées")
cas = [("Error code: 401 - invalid api key", budget.CONFIGURATION),
       ("Error code: 404 - model not found", budget.CONFIGURATION),
       ("Error code: 429 - rate limit exceeded", budget.QUOTA),
       ("Read timed out", budget.RESEAU),
       ("Error code: 503 - service temporarily unavailable", budget.RESEAU),
       ("quelque chose d'inattendu", budget.INCONNUE)]
verifier("chaque panne tombe dans sa famille",
         all(budget.classer(RuntimeError(m)) == f for m, f in cas),
         [(m, budget.classer(RuntimeError(m))) for m, f in cas if budget.classer(RuntimeError(m)) != f])
verifier("une clé refusée ne se retente pas tout de suite, un quota et un réseau si",
         not budget.a_retenter(budget.CONFIGURATION)
         and budget.a_retenter(budget.QUOTA) and budget.a_retenter(budget.RESEAU))

print("3. Demi-ouverture de la cascade (D-16/S-16)")
routeur_src = (BACKEND / "llm" / "router.py").read_text(encoding="utf-8")
verifier("quand tout est écarté, un SEUL candidat est rouvert",
         "demi-ouverture sur" in routeur_src and "return [prochain]" in routeur_src
         and "return vivants or chain" not in routeur_src)
verifier("c'est celui dont la quarantaine finit le plus tôt", "min(chain, key=lambda c: _QUARANTAINE" in routeur_src)

print("4. Les jobs de vectorisation se réclament (D-17/S-17)")
REQUETES = []
ETAT = {"bail": None}


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
        if "FOR UPDATE SKIP LOCKED" in sql:
            ETAT["bail"] = args[1]
            return [{"job_id": "j1", "document_id": "d1", "attempts": 0,
                     "content": "un morceau", "source_type": "nas"}]
        return []

    async def fetchval(self, sql, *args):
        REQUETES.append((sql, args))
        if "SET status = 'completed'" in sql and "claimed_by = $2" in sql:
            # Le bail : seul son porteur écrit.
            return "d1" if args[1] in (None, ETAT["bail"]) else None
        if "SELECT modele FROM embedding_actif" in sql: return None
        return "d1"

    async def execute(self, sql, *args):
        REQUETES.append((sql, args))
        return "UPDATE 1"


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


poser("database")
poser("database.connection", get_db=lambda: _Db(),
      schema_incomplet=lambda e: "does not exist" in str(e).lower())
poser("config", settings=types.SimpleNamespace(embedding_dimensions=1536))
poser("security")
poser("security.acces", ROLE_ACCESS_LEVELS={"terrain": ["all"]})
poser("vectorstore.revectorisation", dimension_attendue=lambda: asyncio.sleep(0, result=3))
client = charger("vectorstore.client", "vectorstore/client.py")
vs = client.vectorstore
jobs = asyncio.run(vs.get_pending_embedding_jobs(limit=4, preneur="worker-A"))
verifier("la réclamation prend un lot avec FOR UPDATE SKIP LOCKED et pose un bail",
         len(jobs) == 1 and any("FOR UPDATE SKIP LOCKED" in sql for sql, _ in REQUETES)
         and ETAT["bail"] == "worker-A")
REQUETES.clear()
asyncio.run(vs.mark_job_completed("j1", [0.1, 0.2, 0.3], modele="google:gemini-embedding-001",
                                  preneur="worker-A"))
verifier("le porteur du bail écrit son vecteur ET le modèle qui l'a produit",
         any("embedding_modele" in sql for sql, _ in REQUETES)
         and any("google:gemini-embedding-001" in str(a) for _, a in REQUETES), REQUETES[-1:])
REQUETES.clear()
asyncio.run(vs.mark_job_completed("j1", [0.1, 0.2, 0.3], modele="x", preneur="worker-B"))
verifier("un worker qui a PERDU son bail n'écrase pas le travail de l'autre",
         not any("UPDATE documents" in sql for sql, _ in REQUETES), REQUETES)
worker_src = (BACKEND / "vectorstore" / "worker.py").read_text(encoding="utf-8")
verifier("le worker réclame sous son nom et rend le modèle avec le vecteur",
         "preneur=preneur" in worker_src and "modele=modele" in worker_src)
embeddings_src = (BACKEND / "vectorstore" / "embeddings.py").read_text(encoding="utf-8")
verifier("le modèle courant se nomme « fournisseur:modèle »", "def modele_courant(" in embeddings_src)
migration = BACKEND / "database" / "migrations" / "047_baux_embeddings.sql"
verifier("la migration 047 ajoute bail, essais et identité du vecteur",
         migration.exists()
         and all(m in migration.read_text(encoding="utf-8")
                 for m in ("lease_until", "next_attempt_at", "embedding_modele")))

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
