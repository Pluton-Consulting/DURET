"""
Banc des LEÇONS — apprendre d'une correction plutôt qu'écrire une règle (15/09).

Demande de Noa : « c'est mieux d'entraîner l'IA ». Quand la personne corrige
l'assistant, le modèle puissant tire UNE leçon générale de l'échange ; elle est
rappelée quand une demande semblable revient, et le relecteur la connaît.

CE QUE CE BANC PROUVE (sans réseau, modèle et base doublés) :
  · la lecture d'une leçon : valide, absente (« null »), trop courte, ou qui
    porte une balise de masquage (un cas, pas une règle) → écartée ;
  · l'échange retrouvé dans l'historique du 15/09 (« mais c'est pas ma
    signature ça ») : la réponse corrigée, la correction, la nouvelle réponse ;
  · `apprendre_du_tour` EXÉCUTÉ : rien sans correction signalée ; une leçon
    créée, puis la même RENFORCÉE au lieu d'être dupliquée ; une panne ne lève
    jamais ;
  · le rappel : la requête plein texte en OU, la lecture en base (les siennes
    et celles de l'entreprise, rappels comptés), le bloc du prompt qui laisse
    le modèle juger ;
  · le câblage : migration idempotente, déclenchement en fin de tour (les deux
    chemins du runtime), rappel dans llm_node, routes (chacun les siennes,
    retrait, portée réservée à l'administration), volet Leçons.
Tombe sur la version d'avant (module absent).

Usage : python backend/scripts/test_lecons.py [backend]
"""
import asyncio
import importlib
import json
import pathlib
import sys
import types

racine = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
sys.path.insert(0, str(racine))
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {str(detail)[:300]}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def msg(qui, texte):
    return types.SimpleNamespace(type=qui, content=texte)


try:
    L = importlib.import_module("learning.lecons")
except Exception as e:  # noqa: BLE001
    L = None
    verifier("learning/lecons.py existe", False, e)

LECON = {"lecon": {"situation": "Quand on demande d'apprendre la signature de la boîte mail",
                   "erreur": "Elle a été prise dans un message REÇU, celui d'un tiers.",
                   "conduite": "Ne l'apprendre que depuis un message ENVOYÉ par la boîte, et vérifier l'expéditeur.",
                   "gestes": ["apprendre_signature"]}}
HISTORIQUE = [
    msg("human", "affiche moi la signature de la boite mail"),
    msg("ai", "Aucune signature n'est enregistrée pour la boîte."),
    msg("human", "oui"),
    msg("ai", "La signature a bien été apprise depuis votre dernier message envoyé."),
    msg("human", "mais c'est pas ma signature ca"),
    msg("ai", "Vous avez raison, j'ai capturé la signature d'une cliente citée dans le message."),
]

if L:
    print("1. Lire une leçon")
    l = L.lire_lecon("Voilà : " + json.dumps(LECON, ensure_ascii=False))
    verifier("une leçon valide se lit", l and l["gestes"] == ["apprendre_signature"] and "ENVOYÉ" in l["conduite"], l)
    verifier("« pas de leçon » se lit comme None", L.lire_lecon('{"lecon": null}') is None)
    verifier("une leçon trop courte est écartée",
             L.lire_lecon('{"lecon": {"situation": "court", "conduite": "court"}}') is None)
    avec_balise = json.loads(json.dumps(LECON))
    avec_balise["lecon"]["situation"] = "Quand [PER_1] demande d'apprendre sa signature de la boîte"
    verifier("une leçon qui porte une balise de masquage raconte un cas : écartée",
             L.lire_lecon(json.dumps(avec_balise, ensure_ascii=False)) is None)

    inverse={**l,"conduite":"Ne pas "+l["conduite"]}
    verifier("une conduite inversée ne renforce pas l'ancienne leçon", not L.est_un_doublon(inverse,l) and L.conflit_possible(inverse,l))
    print("2. L'échange retrouvé dans l'historique du 15/09")
    e = L._echange_du_tour(HISTORIQUE)
    verifier("la réponse corrigée, la correction, la nouvelle réponse",
             e and "bien été apprise" in e["reponse_corrigee"] and "pas ma signature" in e["correction"]
             and "Vous avez raison" in e["nouvelle_reponse"] and e["question_precedente"] == "oui", e)
    verifier("un fil trop court : rien", L._echange_du_tour(HISTORIQUE[:2]) is None)
    c = L.consigne_extraction("oui", "apprise", "pas ma signature", "vous avez raison", "1. apprendre_signature")
    verifier("la consigne exclut préférences et noms, et accepte « pas de leçon »",
             "préférence de ton" in c and "SANS nom" in c and '{"lecon": null}' in c)

    print("3. apprendre_du_tour exécuté")
    BASE = []

    class Conn:
        async def fetch(self, sql, *a):
            if "FROM lecons" in sql and "ts_rank" not in sql:
                return [dict(r) for r in BASE]
            if "ts_rank" in sql:
                return [{"id": r["id"], "situation": r["situation"], "erreur": r["erreur"],
                         "conduite": r["conduite"], "rang": 0.5} for r in BASE]
            return []

        async def execute(self, sql, *a):
            if sql.lstrip().startswith("INSERT INTO lecons"):
                BASE.append({"id": f"l{len(BASE)+1}", "user_id": a[0], "situation": a[1], "erreur": a[2],
                             "conduite": a[3], "occurrences": 1, "rappels": 0})
            elif "occurrences = occurrences + 1" in sql:
                for r in BASE:
                    if r["id"] == a[0]:
                        r["occurrences"] += 1
            elif "rappels = rappels + 1" in sql:
                for r in BASE:
                    if r["id"] in a[0]:
                        r["rappels"] += 1

    class Ctx:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, *a):
            return False

    connexion = types.ModuleType("database.connection")
    connexion.get_db = lambda: Ctx()
    connexion.schema_incomplet = lambda e: False
    sys.modules["database"] = types.ModuleType("database")
    sys.modules["database.connection"] = connexion
    PROMPTS = []

    class _LLM:
        reponse = json.dumps(LECON, ensure_ascii=False)
        panne = False

        async def ainvoke(self, messages):
            PROMPTS.append(messages[0].content)
            if _LLM.panne:
                raise RuntimeError("panne")
            return types.SimpleNamespace(content=_LLM.reponse)

    sys.modules["llm"] = types.ModuleType("llm")
    sys.modules["llm.router"] = types.SimpleNamespace(get_llm=lambda t: _LLM(),
                                                      LLMTier=types.SimpleNamespace(COMPLEX="complex"))
    sys.modules["langchain_core"] = types.ModuleType("langchain_core")
    sys.modules["langchain_core.messages"] = types.SimpleNamespace(
        HumanMessage=lambda content: types.SimpleNamespace(content=content))
    etat = {"messages": HISTORIQUE, "user_id": "u-accueil", "thread_id": "fil-a21f89c4",
            "tool_results": [{"skill": "apprendre_signature", "ok": True, "args": {}, "resultat_masque": "{}"}]}
    verifier("sans correction signalée : aucun appel", asyncio.run(L.apprendre_du_tour(etat)) is None and not PROMPTS)
    etat["correction_signalee"] = True
    verifier("une correction : la leçon est créée", asyncio.run(L.apprendre_du_tour(etat)) == "creee" and len(BASE) == 1)
    verifier("le modèle a lu la réponse corrigée et la correction",
             PROMPTS and "bien été apprise" in PROMPTS[-1] and "pas ma signature" in PROMPTS[-1])
    variante = json.loads(json.dumps(LECON))
    variante["lecon"]["conduite"] = "Ne l'apprendre que depuis un message ENVOYÉ par la boîte, en vérifiant l'expéditeur."
    _LLM.reponse = json.dumps(variante, ensure_ascii=False)
    verifier("une autre conduite pour la même situation exige vérification, sans renforcer l'ancienne",
             asyncio.run(L.apprendre_du_tour(etat)) == "a_verifier" and len(BASE) == 2 and BASE[0]["occurrences"] == 1)
    _LLM.panne = True
    verifier("une panne du modèle ne lève jamais", asyncio.run(L.apprendre_du_tour(etat)) is None)
    _LLM.panne = False

    print("4. Le rappel")
    q = L.requete_plein_texte("apprends la signature de ma boîte mail depuis un mail envoyé")
    verifier("la requête plein texte : les mots porteurs, en OU", "signature" in q and " | " in q and "depuis" in q, q)
    verifier("une demande sans mot porteur ne cherche rien", L.requete_plein_texte("ok oui") == "")
    trouvees = asyncio.run(L.pertinentes("u-accueil", "récupère la signature de la boîte mail"))
    verifier("les leçons proches sont rendues, et leur rappel compté", trouvees and BASE[0]["rappels"] == 1, trouvees)
    bloc = L.bloc_pour_le_prompt(trouvees)
    verifier("le bloc laisse le modèle juger si elles s'appliquent",
             "applique celles dont la situation correspond VRAIMENT" in bloc and "ENVOYÉ" in bloc, bloc)
    verifier("aucune leçon : aucun bloc", L.bloc_pour_le_prompt([]) == "")

print("5. Le câblage")
mig = (racine / "database/migrations/043_lecons.sql").read_text(encoding="utf-8")
verifier("migration 043 idempotente", "CREATE TABLE IF NOT EXISTS lecons" in mig
         and "CREATE INDEX IF NOT EXISTS idx_lecons_texte" in mig)
rt = (racine / "agents/runtime.py").read_text(encoding="utf-8")
verifier("la leçon se tire en fin de tour, sur les deux chemins (POST et flux)", rt.count("apprendre_en_fond(state)") == 2)
a1 = (racine / "agents/agent1.py").read_text(encoding="utf-8")
verifier("le routeur dit si la demande corrige l'assistant", '"correction_signalee": correction' in a1)
verifier("les leçons proches sont rappelées dans le prompt, une fois par tour",
         "bloc_pour_le_prompt(await pertinentes(" in a1 and "bloc_lecons + bloc_memoire_txt" in a1)
ro = (racine / "routers/learning.py").read_text(encoding="utf-8")
verifier("routes : chacun les siennes, retrait, portée réservée à l'administration",
         '@router.get("/lecons")' in ro and "/retirer" in ro and "Réservé à l'administration" in ro)
cl = (racine.parent / "frontend/app/(app)/connaissances/ConnaissancesClient.tsx").read_text(encoding="utf-8")
verifier("le volet Leçons est dans Connaissances", "LeconsApprises" in cl)

print()
if echecs:
    print(f"✗ {len(echecs)} échec(s)")
    sys.exit(1)
print("✓ 0 échec")
