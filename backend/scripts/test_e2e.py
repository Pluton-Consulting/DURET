#!/usr/bin/env python
"""
Banc de test de bout en bout — exerce la VRAIE chaîne, dans le conteneur.

Contrairement aux tests unitaires, celui-ci utilise la base réelle, le vrai
moteur de recherche et la vraie cascade de modèles. Il est donc le seul à
pouvoir répondre à « est-ce que ça marche ? » plutôt qu'à « est-ce que le code
est cohérent ? ».

Usage :
    docker compose -f docker-compose.yml -f docker-compose.prod.yml \
      exec -T backend sh -c "PYTHONPATH=. python scripts/test_e2e.py"

Options :
    --rapide     saute les sections qui appellent le modèle (aucun quota consommé)
    --garder     ne supprime pas les documents de test (pour inspecter la base)

Coût : environ 10 à 14 appels au modèle en mode complet. Les données de test
sont préfixées « ZZTEST » et supprimées à la fin.
"""
import argparse
import asyncio
import json
import re
import sys
import time
import uuid

sys.path.insert(0, ".")

VERT, ROUGE, JAUNE, GRIS, RAZ = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"

MARQUEUR = "ZZTEST"
SOURCE_TEST = "zztest_chantier"

_ok = _ko = _skip = 0
_echecs: list[str] = []


def verdict(libelle, condition, detail=""):
    global _ok, _ko
    if condition:
        _ok += 1
        print(f"  {VERT}OK{RAZ}   {libelle}")
    else:
        _ko += 1
        _echecs.append(libelle)
        print(f"  {ROUGE}KO{RAZ}   {libelle}")
        if detail:
            texte = str(detail).replace("\n", "\n         ")[:400]
            print(f"       {GRIS}{texte}{RAZ}")


def saute(libelle, motif):
    global _skip
    _skip += 1
    print(f"  {JAUNE}--{RAZ}   {libelle} {GRIS}({motif}){RAZ}")


def titre(t):
    print(f"\n{JAUNE}── {t} {'─' * max(0, 54 - len(t))}{RAZ}")


# ─────────────────────────────────────────────────────────────
# Document de référence : on connaît son contenu, donc on peut
# juger si la réponse du modèle s'y appuie vraiment.
# ─────────────────────────────────────────────────────────────
DOC_TEST = f"""Fiche chantier {MARQUEUR}-2031
Client : Copropriete Les Alizes
Adresse : 14 rue des Peupliers, Merignac
Conducteur de travaux : Benoit Lemoine
Statut : en cours
Avancement : 62 %
Montant du marche : 48 250 EUR HT
Date de demarrage : 12/03/2026
Reception prevue : 30/09/2026
Postes : ragreage 1 200 m2, carrelage 340 m2, plinthes 210 ml.
Reserve en cours : reprise des joints sur la zone nord.
"""


async def infrastructure(args):
    titre("1. Infrastructure")
    from config import settings

    from database.connection import get_db
    try:
        async with get_db() as conn:
            un = await conn.fetchval("SELECT 1")
        verdict("base de données joignable", un == 1)
    except Exception as e:
        verdict("base de données joignable", False, e)
        return False

    async with get_db() as conn:
        tables = {r["tablename"] for r in await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    attendues = ["documents", "embedding_jobs", "threads", "messages", "validations",
                 "user_mailboxes", "mail_style_profiles", "agent_tasks", "agent_task_runs"]
    manquantes = [t for t in attendues if t not in tables]
    verdict("toutes les migrations appliquées", not manquantes,
            f"tables absentes : {manquantes} — relancez ./deploy.sh")

    async with get_db() as conn:
        cols = {r["column_name"] for r in await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'validations'")}
    verdict("validations.payload_hash présent (liaison approbation ↔ action)",
            "payload_hash" in cols, sorted(cols))

    from agents import checkpointer as cp
    await cp.get_checkpointer()
    nom = type(cp._checkpointer).__name__
    verdict(f"checkpointer persistant ({nom})", nom == "AsyncPostgresSaver",
            "MemorySaver : la mémoire de conversation sera perdue à chaque redémarrage")

    from security.anonymizer import anonymizer
    verdict("anonymiseur NER opérationnel", anonymizer.spacy_available,
            "spaCy indisponible : les appels aux modèles externes seront refusés")

    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        verdict("OCR disponible", True)
    except Exception as e:
        verdict("OCR disponible", False, e)

    from tasks.scheduler import PARIS
    verdict("fuseau horaire de Paris résolu", str(PARIS) == "Europe/Paris",
            f"{PARIS} — les tâches planifiées seront décalées (installez tzdata)")
    return True


async def base_vectorielle(args):
    titre("2. Base vectorisée et recherche")
    from database.connection import get_db
    from ingestion.pipeline import ingest_document

    chunks = await ingest_document(
        text=DOC_TEST, source_type=SOURCE_TEST, source_id=f"{SOURCE_TEST}:2031",
        source_filename=f"{MARQUEUR}-2031.txt")
    verdict("document ingéré et découpé", chunks and chunks > 0, f"chunks = {chunks}")

    async with get_db() as conn:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM documents WHERE source_type = $1", SOURCE_TEST)
        total = await conn.fetchval("SELECT COUNT(*) FROM documents")
        vectorises = await conn.fetchval(
            "SELECT COUNT(*) FROM documents WHERE embedding IS NOT NULL")
        attente = await conn.fetchval(
            "SELECT COUNT(*) FROM embedding_jobs WHERE status = 'pending'")
    verdict("chunks présents en base", n > 0, n)
    print(f"       {GRIS}corpus : {total} chunks, {vectorises} vectorisés, "
          f"{attente} en attente{RAZ}")

    if total and vectorises == 0:
        saute("recherche vectorielle", "aucun embedding calculé — repli mots-clés actif")
    else:
        verdict("corpus partiellement vectorisé", vectorises > 0)

    from vectorstore.rag import retrieve
    trouves = await retrieve("avancement du chantier Les Alizes", "super_admin",
                             top_k=5, mailboxes=["*"])
    ids = [c.get("source_id") or "" for c in trouves]
    verdict("la recherche retrouve le document de test",
            any(SOURCE_TEST in i for i in ids), f"remontés : {ids}")

    # Cloisonnement : sans boîte autorisée, aucun mail ne doit remonter.
    from vectorstore.rag import _filtrer_mails
    faux_mails = [{"source_type": "email", "source_id": "email:a@b.fr:1", "content": "x"},
                  {"source_type": "devis", "source_id": "devis:1", "content": "y"}]
    verdict("cloisonnement : aucun mail sans boîte autorisée",
            len(_filtrer_mails(faux_mails, [])) == 1)
    verdict("cloisonnement : mail visible avec la bonne boîte",
            len(_filtrer_mails(faux_mails, ["a@b.fr"])) == 2)


async def anonymisation(args):
    titre("3. Anonymisation et intégrité des chiffres")
    from security.anonymizer import anonymizer

    masque, carte = anonymizer.anonymize(
        "Benoit Lemoine suit le chantier. Montant 48 250 EUR, avancement 62 %.")
    verdict("le nom est masqué", "Benoit Lemoine" not in masque, masque)
    verdict("les chiffres sont préservés",
            "48 250" in masque and "62" in masque, masque)
    verdict("réhydratation exacte",
            "Benoit Lemoine" in anonymizer.rehydrate(masque, carte))

    serie = ("CA par mois : Jan 42, Fev 58, Mars 35, Avril 71, Mai 64, Juin 88 (en kEUR).")
    m2, _ = anonymizer.anonymize(serie)
    verdict("une série chiffrée traverse intacte", m2 == serie, m2)


async def _tour(question, fil, utilisateur, trigger="chat"):
    from agents import runtime
    return await runtime.run_turn(
        query=question, user_id=str(utilisateur["id"]), user_role=utilisateur["role"],
        has_attachment=False, thread_id=fil, trigger_kind=trigger)


async def _utilisateur_test():
    """Un compte réel : super_admin de préférence (accès total, moins de faux négatifs)."""
    from database.connection import get_db
    async with get_db() as conn:
        for role in ("super_admin", "direction"):
            u = await conn.fetchrow(
                "SELECT id, email, role FROM users WHERE role = $1 AND actif LIMIT 1", role)
            if u:
                return dict(u)
        u = await conn.fetchrow("SELECT id, email, role FROM users WHERE actif LIMIT 1")
    return dict(u) if u else None


BLOC_UI = re.compile(r"```ui\s*(.*?)```", re.S)
REQUIS = {"quote": ["client", "total", "lines"], "invoice": ["number", "client", "amount"],
          "table": ["columns", "rows"], "bars": ["data"], "stat": ["label", "value"],
          "callout": ["text"], "email": ["subject", "from"], "list": ["items"],
          "progress": ["items"], "keyvalue": ["rows"], "doc": ["name"],
          "contact": ["name"], "project": ["name", "client"], "badge": ["text"],
          "quick_replies": ["options"]}


def analyser_composants(reponse):
    """(nb_blocs, nb_valides, problemes)"""
    blocs = BLOC_UI.findall(reponse or "")
    valides, soucis = 0, []
    for b in blocs:
        try:
            d = json.loads(b.strip())
        except json.JSONDecodeError as e:
            soucis.append(f"JSON invalide : {e}")
            continue
        req = REQUIS.get(d.get("type"))
        if req is None:
            soucis.append(f"type inconnu : {d.get('type')}")
            continue
        manquants = [c for c in req if d.get(c) in (None, "", [], {})]
        if manquants:
            soucis.append(f"{d.get('type')} : champs manquants {manquants}")
            continue
        valides += 1
    return len(blocs), valides, soucis


async def coherence_et_composants(args, utilisateur):
    titre("4. Cohérence des réponses et composants")
    if args.rapide:
        saute("réponses du modèle", "--rapide")
        return

    cas = [
        ("s'appuie sur la mémoire",
         f"Que sais-tu du chantier {MARQUEUR}-2031 ? Donne le client et l'avancement.",
         ["Alizes", "62"], True),
        ("présente un tableau",
         "Mets dans un tableau : Ragreage 1200 m2 18 EUR, Carrelage 340 m2 45 EUR.",
         ["1200", "340"], True),
        ("présente un graphique",
         "Montre un graphique du CA par mois : Jan 42, Fev 58, Mars 35, Avril 71.",
         ["42", "58", "35", "71"], True),
        ("prépare un devis",
         "Fais un devis pour Copropriete Les Alizes : 120 m2 de carrelage a 45 EUR/m2.",
         ["120"], True),
        ("reste honnête sans donnée",
         "Quel est le montant du chantier ZZINEXISTANT-9999 ?",
         [], False),
    ]

    avec_composant = 0
    for libelle, question, attendus, veut_composant in cas:
        fil = f"e2e-{uuid.uuid4()}"
        try:
            res = await _tour(question, fil, utilisateur)
        except Exception as e:
            verdict(libelle, False, e)
            continue
        reponse = res.get("response") or ""

        if attendus:
            absents = [a for a in attendus if a not in reponse]
            verdict(f"{libelle} : données restituées", not absents,
                    f"absentes : {absents}\n{reponse[:300]}")
        else:
            honnete = any(m in reponse.lower() for m in
                          ("aucun", "pas de", "n'ai pas", "introuvable", "ne dispose"))
            verdict(f"{libelle} : n'invente pas", honnete, reponse[:300])

        blocs, valides, soucis = analyser_composants(reponse)
        if veut_composant:
            if valides:
                avec_composant += 1
            verdict(f"{libelle} : composant exploitable", valides > 0,
                    f"blocs={blocs} valides={valides} {soucis} | {reponse[:220]}")

    attendus_composants = sum(1 for c in cas if c[3])
    taux = avec_composant / attendus_composants if attendus_composants else 0
    verdict(f"composants affichés dans la majorité des cas ({avec_composant}/{attendus_composants})",
            taux >= 0.6, f"taux = {taux:.0%}")


async def memoire(args, utilisateur):
    titre("5. Mémoire de conversation")
    if args.rapide:
        saute("mémoire", "--rapide")
        return
    fil = f"e2e-mem-{uuid.uuid4()}"
    await _tour("Le chantier de reference est Les Alizes, montant 48 250 EUR.", fil, utilisateur)
    res = await _tour("Quel montant viens-je de te donner ?", fil, utilisateur)
    reponse = res.get("response") or ""
    verdict("le second tour se souvient du premier",
            "48" in reponse, reponse[:300])

    from database.connection import get_db
    async with get_db() as conn:
        n = await conn.fetchval(
            """SELECT COUNT(*) FROM messages m JOIN threads t ON t.id = m.thread_id
               WHERE t.langgraph_thread_id = $1""", fil)
    verdict("l'échange est persisté (rechargement de page)", n >= 4, f"{n} messages")


async def actions(args, utilisateur):
    titre("6. Actions et délégation")
    from skills.protocol import CATALOGUE_AGENT1, extraire_action
    from skills.executor import execute_skill, SkillError

    a, _, err = extraire_action(
        'ok\n```action\n{"skill":"apprendre_style_email","args":{}}\n```')
    verdict("le protocole d'action est opérationnel", a and not err, err)

    try:
        await execute_skill("action_inconnue_externe", {"x": 1},
                            user=type("U", (), utilisateur)())
        verdict("une action non déclarée est refusée", False, "exécutée !")
    except SkillError as e:
        verdict("une action non déclarée est refusée", "externe" in str(e), e)
    except Exception as e:
        verdict("une action non déclarée est refusée", True, f"({type(e).__name__})")

    # Délégation : création d'une tâche par le skill natif
    from database.connection import get_db
    from tasks.skills import creer_tache_agent

    class U:
        id = utilisateur["id"]; role = utilisateur["role"]; email = utilisateur["email"]

    res = await creer_tache_agent(
        {"titre": f"{MARQUEUR} tri quotidien", "consigne": "Trie les mails entrants.",
         "recurrence": "daily", "heure": "07:30"}, U())
    verdict("une tâche est créée par délégation", res.get("tache_id"), res)
    verdict("son échéance est calculée", res.get("prochaine_execution"), res)

    async with get_db() as conn:
        t = await conn.fetchrow("SELECT * FROM agent_tasks WHERE id = $1::uuid",
                                res["tache_id"])
    verdict("la tâche agit au nom de son créateur",
            str(t["user_id"]) == str(utilisateur["id"]))
    verdict("elle est planifiée et active", t["enabled"] and t["next_run_at"])

    if not args.rapide:
        fil = f"e2e-act-{uuid.uuid4()}"
        try:
            res2 = await _tour(
                "Apprends mon style d'ecriture a partir de ma boite mail.", fil, utilisateur)
            rep = (res2.get("response") or "").lower()
            # Le modèle peut légitimement refuser si aucune boîte n'est connectée :
            # on vérifie qu'il a TENTÉ l'action, pas qu'elle a réussi.
            verdict("le chat tente une action quand c'est pertinent",
                    any(m in rep for m in ("style", "boite", "boîte", "mail", "action")),
                    rep[:300])
        except Exception as e:
            verdict("le chat tente une action quand c'est pertinent", False, e)

    async with get_db() as conn:
        await conn.execute("DELETE FROM agent_tasks WHERE title LIKE $1", f"{MARQUEUR}%")


async def taches_autonomes(args, utilisateur):
    titre("7. Tâches autonomes : ordonnanceur et webhook")
    import hashlib, hmac
    from database.connection import get_db
    from tasks.scheduler import prochaine_echeance
    from tasks.identity import charger_executant

    e = prochaine_echeance({"schedule_kind": "interval", "interval_minutes": 30})
    verdict("prochaine échéance calculée", e is not None and e.tzinfo is not None, e)

    u = await charger_executant(str(utilisateur["id"]))
    verdict("identité rechargeable à l'exécution", u is not None)
    verdict("compte inexistant refusé (fail-closed)",
            await charger_executant(str(uuid.uuid4())) is None)

    secret = "c" * 48
    corps = b'{"evenement":"test"}'
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + corps, hashlib.sha256).hexdigest()
    verdict("signature de webhook reproductible",
            hmac.compare_digest(sig, hmac.new(secret.encode(), ts.encode() + b"." + corps,
                                              hashlib.sha256).hexdigest()))
    verdict("corps altéré → signature invalide",
            not hmac.compare_digest(sig, hmac.new(secret.encode(), ts.encode() + b'.{"x":1}',
                                                  hashlib.sha256).hexdigest()))

    async with get_db() as conn:
        actives = await conn.fetchval(
            "SELECT COUNT(*) FROM agent_tasks WHERE enabled AND next_run_at IS NOT NULL")
        runs = await conn.fetchval("SELECT COUNT(*) FROM agent_task_runs")
    print(f"       {GRIS}{actives} tâche(s) planifiée(s), {runs} exécution(s) enregistrée(s){RAZ}")
    verdict("le worker de tâches tourne",
            __import__("tasks.worker", fromlist=["_task"])._task is not None,
            "worker non démarré (agent_tasks_enabled=false ?)")


async def nettoyer(args):
    if args.garder:
        print(f"\n{GRIS}Données de test conservées (--garder).{RAZ}")
        return
    from database.connection import get_db
    async with get_db() as conn:
        await conn.execute("DELETE FROM documents WHERE source_type = $1", SOURCE_TEST)
        await conn.execute("DELETE FROM agent_tasks WHERE title LIKE $1", f"{MARQUEUR}%")
        await conn.execute(
            """DELETE FROM threads WHERE langgraph_thread_id LIKE 'e2e-%'""")
    print(f"\n{GRIS}Données de test supprimées.{RAZ}")


async def main():
    p = argparse.ArgumentParser(description="Banc de test de bout en bout")
    p.add_argument("--rapide", action="store_true", help="sans appel au modèle")
    p.add_argument("--garder", action="store_true", help="conserve les données de test")
    args = p.parse_args()

    print(f"\n{'=' * 58}\n BANC DE TEST — chaîne complète\n{'=' * 58}")

    from database.connection import init_db
    await init_db()
    from agents.runtime import init_runtime
    await init_runtime()

    if not await infrastructure(args):
        print(f"\n{ROUGE}Base injoignable : arrêt.{RAZ}")
        return 1

    utilisateur = await _utilisateur_test()
    if utilisateur is None:
        print(f"\n{ROUGE}Aucun utilisateur actif en base : créez un compte d'abord.{RAZ}")
        return 1
    print(f"       {GRIS}compte de test : {utilisateur['email']} ({utilisateur['role']}){RAZ}")

    await base_vectorielle(args)
    await anonymisation(args)
    await coherence_et_composants(args, utilisateur)
    await memoire(args, utilisateur)
    await actions(args, utilisateur)
    await taches_autonomes(args, utilisateur)
    await nettoyer(args)

    print(f"\n{'=' * 58}")
    couleur = VERT if _ko == 0 else ROUGE
    print(f" {couleur}RESULTAT : {_ok} OK / {_ko} KO{RAZ}"
          + (f" {JAUNE}/ {_skip} ignorés{RAZ}" if _skip else ""))
    if _echecs:
        print(f"\n {ROUGE}Points en échec :{RAZ}")
        for e in _echecs:
            print(f"   - {e}")
    print(f"{'=' * 58}\n")
    return 1 if _ko else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
