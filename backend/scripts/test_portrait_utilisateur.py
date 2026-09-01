"""
Banc « le portrait d'une personne » — 01/09 nuit.

Demande de Noa : « fais en sorte que tous les jours à minuit, pour chaque
utilisateur, il relise la conversation complète pour apprendre au max de
l'utilisateur et avoir cette mémoire / contexte propre à chaque utilisateur. Il
doit retenir la façon de parler, mais aussi les détails, la façon de travailler,
les méthodes de travail, les préférences subtiles. »

CE QUE CE BANC PROTÈGE, et c'est plus le CADRE que le mécanisme :

  · le modèle ne voit JAMAIS un nom (masquage avant, réhydratation après) —
    c'est le patron de `learning/debrief.py`, et il n'a pas d'exception ;
  · sans masquage disponible, ON N'ENVOIE RIEN : mieux vaut un portrait qui ne
    progresse pas qu'une conversation entière partie en clair ;
  · le portrait est PLAFONNÉ et RÉÉCRIT, jamais empilé — il est injecté à
    chaque tour, et ce qui gonfle finit par noyer le prompt ;
  · il s'annonce comme une OBSERVATION, pas comme une consigne : sinon « elle
    demande souvent le point sur les mails » devient un ordre de le faire ;
  · la personne peut le lire, le couper et l'effacer. Un portrait construit
    dans son dos et qu'elle ne peut pas consulter serait de la surveillance.

Aucune base, aucun réseau : le pool et le modèle sont doublés.
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


print(f"\n═══ LE PORTRAIT D'UNE PERSONNE — {BACKEND.resolve().parent}\n")

# ── Doublures : base, anonymiseur, modèle, concurrence ───────────────────
ECRITS: list = []
FILS = [{"id": "f1", "title": "Devis Durand"}]
MESSAGES = [
    {"role": "user", "content": "salut, tu me sors le devis Durand vite fait"},
    {"role": "assistant", "content": "Voici le devis de Jean Durand, 4 200 €."},
    {"role": "user", "content": "nickel, mets-le en pdf comme d'hab"},
]


class _Conn:
    async def fetch(self, sql, *a):
        if "FROM threads" in sql:
            return FILS
        if "FROM messages" in sql:
            return MESSAGES
        if "FROM users u" in sql:
            return [{"id": "u-1"}, {"id": "u-2"}]
        return []

    async def fetchrow(self, sql, *a):
        return None

    async def fetchval(self, sql, *a):
        return None

    async def execute(self, sql, *a):
        ECRITS.append((" ".join(sql.split()), a))


class _Db:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *x):
        return False


ENVOYE: list = []


class _Reponse:
    content = ("Tutoie l'assistant et va droit au but. Demande souvent des "
               "documents en PDF. Travaille surtout le matin.")


class _Llm:
    async def ainvoke(self, messages):
        ENVOYE.append(messages[0].content)
        return _Reponse()


faux_db = types.ModuleType("database.connection")
faux_db.get_db = lambda: _Db()
paquet_db = types.ModuleType("database")
paquet_db.__path__ = []
sys.modules.setdefault("database", paquet_db)
sys.modules["database.connection"] = faux_db

MASQUE: list = []


class _Anon:
    def anonymize_chunks(self, textes, carte):
        MASQUE.append(list(textes))
        # « Durand » devient un jeton : c'est ce que le modèle doit voir.
        return [t.replace("Durand", "[PER_1]").replace("Jean ", "") for t in textes], \
            {"[PER_1]": "Durand"}

    def rehydrate(self, texte, carte):
        for jeton, vrai in (carte or {}).items():
            texte = texte.replace(jeton, vrai)
        return texte


faux_sec = types.ModuleType("security.anonymizer")
faux_sec.anonymizer = _Anon()
paquet_sec = types.ModuleType("security")
paquet_sec.__path__ = []
sys.modules.setdefault("security", paquet_sec)
sys.modules["security.anonymizer"] = faux_sec

faux_conc = types.ModuleType("llm.concurrence")
PORTES: list = []
faux_conc.porter = lambda ident, n: PORTES.append((ident, n))
faux_routeur = types.ModuleType("llm.router")
faux_routeur.get_llm = lambda tier: _Llm()
faux_routeur.LLMTier = type("T", (), {"COMPLEX": "complex", "STANDARD": "standard"})
paquet_llm = types.ModuleType("llm")
paquet_llm.__path__ = []
sys.modules.setdefault("llm", paquet_llm)
sys.modules["llm.concurrence"] = faux_conc
sys.modules["llm.router"] = faux_routeur

faux_lc = types.ModuleType("langchain_core.messages")
faux_lc.HumanMessage = lambda content="": types.SimpleNamespace(content=content)
paquet_lc = types.ModuleType("langchain_core")
paquet_lc.__path__ = []
sys.modules.setdefault("langchain_core", paquet_lc)
sys.modules["langchain_core.messages"] = faux_lc

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "profil_banc", BACKEND / "learning" / "profil_utilisateur.py")
profil = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profil)

# ── 1. LA CONSTRUCTION, EXÉCUTÉE ─────────────────────────────────────────
ECRITS.clear(); ENVOYE.clear(); MASQUE.clear(); PORTES.clear()
profil.oublier_cache()
resultat = asyncio.run(profil.construire("u-1"))
verifier("le portrait s'écrit", resultat.get("ecrit"), str(resultat))
verifier("il dit ce qu'il a lu", resultat.get("conversations") == 1
         and resultat.get("messages") == 3, str(resultat))

verifier("LE MODÈLE N'A VU AUCUN NOM", ENVOYE and "Durand" not in ENVOYE[0],
         "un nom est parti en clair")
verifier("il a bien reçu la matière masquée", ENVOYE and "[PER_1]" in ENVOYE[0])
verifier("le portrait ET l'ancien sont masqués ENSEMBLE (même jeton, même valeur)",
         MASQUE and len(MASQUE[0]) == 2)

ecrit = [e for e in ECRITS if "INSERT INTO profils_utilisateur" in e[0]]
verifier("un seul enregistrement part", len(ecrit) == 1)
verifier("LE PORTRAIT STOCKÉ PORTE LES VRAIS NOMS (réhydraté)",
         ecrit and "[PER_1]" not in ecrit[0][1][1])
verifier("le curseur est posé — la prochaine passe ne relira pas ceci",
         ecrit and ecrit[0][1][4] is not None)
verifier("un créneau de FOND est réservé, pas un du chat",
         PORTES and PORTES[0][0].startswith("fond:"))

# ── 2. SANS MASQUAGE, ON N'ENVOIE RIEN ───────────────────────────────────
class _AnonCasse:
    def anonymize_chunks(self, *a, **k):
        raise RuntimeError("spaCy absent")

    def rehydrate(self, t, c):
        return t


faux_sec.anonymizer = _AnonCasse()
ENVOYE.clear(); ECRITS.clear()
profil.oublier_cache()
r = asyncio.run(profil.construire("u-1"))
verifier("masquage indisponible → AUCUN appel au modèle", not ENVOYE)
verifier("et rien n'est écrit, avec la raison dite",
         not r.get("ecrit") and "masquage" in (r.get("raison") or ""), str(r))
faux_sec.anonymizer = _Anon()

# ── 3. LE CADRE D'INJECTION ──────────────────────────────────────────────
profil.oublier_cache()
profil._CACHE["u-9"] = (10 ** 9, {"profil": "Tutoie. Va droit au but.",
                                  "actif": True})
import time as _t  # noqa: E402
profil._CACHE["u-9"] = (_t.monotonic(), {"profil": "Tutoie. Va droit au but.",
                                         "actif": True})
bloc = asyncio.run(profil.texte_injecte("u-9"))
verifier("le portrait s'injecte", "Tutoie" in bloc)
verifier("IL S'ANNONCE COMME UNE OBSERVATION, pas comme une consigne",
         "pas une consigne" in bloc and "ne te demande RIEN" in bloc)
verifier("et il ne prime jamais sur ce que la personne écrit maintenant",
         "remplace jamais" in bloc)

profil._CACHE["u-8"] = (_t.monotonic(), {"profil": "Quelque chose", "actif": False})
verifier("coupé, il ne s'injecte plus",
         asyncio.run(profil.texte_injecte("u-8")) == "")
verifier("sans portrait, rien ne s'injecte (et rien ne lève)",
         asyncio.run(profil.texte_injecte(None)) == "")

# ── 4. LES BORNES ────────────────────────────────────────────────────────
verifier("le portrait est plafonné (il est lu à CHAQUE tour)",
         profil.MAX_PROFIL <= 2500)
verifier("la matière d'une passe l'est aussi", profil.MAX_MATIERE <= 40000)
verifier("et le nombre de comptes par passe", profil.MAX_COMPTES_PAR_PASSE <= 100)
src = (BACKEND / "learning" / "profil_utilisateur.py").read_text(encoding="utf-8")
verifier("le portrait est RÉÉCRIT, pas empilé",
         "profil = EXCLUDED.profil" in src)
verifier("la consigne interdit de retenir les faits ponctuels — ils périment",
         "CE QUE TU NE RETIENS PAS" in src and "montant" in src)
verifier("elle interdit aussi de supposer", "Dans le doute, tu n'écris rien" in src)

# ── 5. LA PASSE DE NUIT ──────────────────────────────────────────────────
w = (BACKEND / "tasks" / "worker.py").read_text(encoding="utf-8")
verifier("la passe est branchée sur la boucle du worker",
         "_passe_profils_si_due" in w and "await _passe_profils_si_due()" in w)
verifier("elle ne tourne QUE la nuit — un redémarrage de jour ne la déclenche pas",
         "_FENETRE_NUIT = (0, 5)" in w)
verifier("une fois par jour, et un échec ne la rejoue pas en boucle",
         "_derniere_passe_profils = jour" in w
         and w.index("_derniere_passe_profils = jour") < w.index("passe_de_nuit"))
verifier("elle ne casse jamais la boucle des tâches",
         "une passe de fond ne casse jamais la boucle" in w)
verifier("le pourquoi de la place est écrit (pas de compte système inventé)",
         "utilisateur système" in w)

# ── 6. C'EST SA DONNÉE ───────────────────────────────────────────────────
r_src = (BACKEND / "routers" / "learning.py").read_text(encoding="utf-8")
for route in ('@router.get("/portrait")', '@router.post("/portrait/couper")',
              '@router.delete("/portrait")', '@router.post("/portrait/construire")'):
    verifier(f"route {route.split('(')[1].strip(')')} exposée", route in r_src)
verifier("aucune route n'accepte l'identité d'un AUTRE : c'est la session qui tranche",
         "str(current_user.id)" in r_src.split("LE PORTRAIT DE LA PERSONNE")[1]
         and "user_id: str" not in r_src.split("LE PORTRAIT DE LA PERSONNE")[1])

# ── 7. L'INJECTION DANS LE TOUR ──────────────────────────────────────────
a1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("le portrait entre dans le prompt du tour",
         "from learning.profil_utilisateur import texte_injecte as portrait" in a1)
verifier("APRÈS les consignes — un ordre donné prime sur une observation",
         a1.index("from learning.consignes import texte_injecte")
         < a1.index("import texte_injecte as portrait"))

# ── 8. La migration ──────────────────────────────────────────────────────
mig = BACKEND / "database" / "migrations" / "032_profil_utilisateur.sql"
verifier("migration 032, idempotente",
         mig.exists()
         and "CREATE TABLE IF NOT EXISTS profils_utilisateur" in mig.read_text(encoding="utf-8"))
verifier("le portrait meurt avec le compte (ON DELETE CASCADE)",
         "ON DELETE CASCADE" in mig.read_text(encoding="utf-8"))
verifier("la migration dit pourquoi une table de plus, face aux trois qui existent",
         "POURQUOI UNE TABLE DE PLUS" in mig.read_text(encoding="utf-8"))

print(f"\n{'═' * 70}\n{'✗ ' + str(len(echecs)) + ' échec(s) : ' + ', '.join(echecs) if echecs else '✓ 0 échec'}\n")
sys.exit(1 if echecs else 0)
