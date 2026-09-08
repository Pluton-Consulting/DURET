"""
Banc « LA PLANIFICATION REVIENT DANS LA CONVERSATION » (08/09 soir).

Demande de Noa : « un système d'action planifié … tous les X jours ou tous
les X du mois, à telle heure ; visible dans le tableau de bord ; le compte
rendu dans les indicateurs ; chaque exécution revient dans la conversation
comme un nouveau message. Très fiable. »

CE QUE CE BANC PROUVE (le calcul des échéances et le texte du message sont
EXÉCUTÉS ; le câblage est lu dans le code livré) : « tous les 3 jours à 9h »
et « le 31 de chaque mois à 9h » donnent des échéances justes (jamais dans
le passé, le 31 devient le 30 en septembre et le 28 en février), les
planifications incohérentes sont refusées avec la raison, le rythme se dit
en français ; la tâche garde le fil de sa conversation (posé par le serveur,
jamais par le modèle), le worker y écrit le compte rendu au nom du créateur
sous RLS, le tableau porte le dernier compte rendu, le chat relit son fil au
repos. Tombe sur la version d'avant.
"""
import ast
import pathlib
import sys
import types
from datetime import datetime, time
from zoneinfo import ZoneInfo

BACKEND = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "backend").resolve()
FRONTEND = BACKEND.parent / "frontend"
echecs = []


def verifier(nom, cond, detail=""):
    print(f"  {'✓' if cond else '✗'} {nom}" + (f"  → {detail}" if detail and not cond else ""))
    if not cond:
        echecs.append(nom)


def fonctions(chemin, noms, espace):
    src = chemin.read_text(encoding="utf-8")
    arbre = ast.parse(src)
    morceaux = [ast.get_source_segment(src, n) for n in arbre.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in noms]
    manquantes = [n for n in noms if not any(m.startswith(("def " + n, "async def " + n)) for m in morceaux)]
    if manquantes:
        return manquantes
    exec(compile("from __future__ import annotations\n" + "\n\n".join(morceaux), str(chemin), "exec"), espace)
    return []


print(f"\n═══ LA PLANIFICATION REVIENT DANS LA CONVERSATION — {BACKEND.parent}\n")
PARIS = ZoneInfo("Europe/Paris")
sch_src = BACKEND / "tasks" / "scheduler.py"
sch = types.ModuleType("scheduler_double")
sch.__dict__["__file__"] = str(sch_src)
exec(compile(sch_src.read_text(encoding="utf-8"), str(sch_src), "exec"), sch.__dict__)

print("— les échéances")
verifier("les deux rythmes existent", "every_days" in sch.FORMES and "monthly" in sch.FORMES)
lundi_8h = datetime(2026, 9, 7, 8, 0, tzinfo=PARIS)        # lundi 7 septembre 2026, 08:00
t = {"schedule_kind": "every_days", "interval_days": 3, "time_of_day": time(9, 0)}
e = sch.prochaine_echeance(t, lundi_8h)
verifier("« tous les 3 jours à 9h » créée un lundi à 8h : première échéance le jour même à 9h",
         e == datetime(2026, 9, 7, 9, 0, tzinfo=PARIS), e)
e = sch.prochaine_echeance(t, datetime(2026, 9, 7, 10, 0, tzinfo=PARIS))
verifier("…créée à 10h (l'heure est passée) : le lendemain à 9h", e == datetime(2026, 9, 8, 9, 0, tzinfo=PARIS), e)
e = sch.prochaine_echeance({**t, "next_run_at": datetime(2026, 9, 7, 9, 0, tzinfo=PARIS)},
                           datetime(2026, 9, 7, 9, 0, 30, tzinfo=PARIS))
verifier("après l'exécution du 7 à 9h : la suivante le 10 à 9h (trois jours depuis la DERNIÈRE échéance)",
         e == datetime(2026, 9, 10, 9, 0, tzinfo=PARIS), e)
e = sch.prochaine_echeance({**t, "next_run_at": datetime(2026, 8, 1, 9, 0, tzinfo=PARIS)},
                           datetime(2026, 9, 7, 10, 0, tzinfo=PARIS))
verifier("une tâche restée endormie un mois ne rattrape pas en rafale : la prochaine est STRICTEMENT après maintenant",
         e is not None and e > datetime(2026, 9, 7, 10, 0, tzinfo=PARIS) and (e - datetime(2026, 8, 1, 9, 0, tzinfo=PARIS)).days % 3 == 0, e)
m = {"schedule_kind": "monthly", "day_of_month": 5, "time_of_day": "09:00"}
e = sch.prochaine_echeance(m, datetime(2026, 9, 3, 12, 0, tzinfo=PARIS))
verifier("« le 5 de chaque mois à 9h » le 3 : le 5 de ce mois", e == datetime(2026, 9, 5, 9, 0, tzinfo=PARIS), e)
e = sch.prochaine_echeance(m, datetime(2026, 9, 5, 9, 0, tzinfo=PARIS))
verifier("…le 5 à 9h pile : le 5 du mois SUIVANT (jamais la même échéance deux fois)",
         e == datetime(2026, 10, 5, 9, 0, tzinfo=PARIS), e)
e = sch.prochaine_echeance({**m, "day_of_month": 31}, datetime(2026, 9, 1, 0, 0, tzinfo=PARIS))
verifier("« le 31 » en septembre : le 30 (dernier jour), pas un saut au 31 octobre",
         e == datetime(2026, 9, 30, 9, 0, tzinfo=PARIS), e)
e = sch.prochaine_echeance({**m, "day_of_month": 31}, datetime(2027, 2, 1, 0, 0, tzinfo=PARIS))
verifier("« le 31 » en février 2027 : le 28", e == datetime(2027, 2, 28, 9, 0, tzinfo=PARIS), e)
e = sch.prochaine_echeance({**m, "day_of_month": 15}, datetime(2026, 12, 20, 0, 0, tzinfo=PARIS))
verifier("le passage d'année : décembre → 15 janvier", e == datetime(2027, 1, 15, 9, 0, tzinfo=PARIS), e)
verifier("les trois rythmes d'avant sont inchangés (quotidien : le lendemain quand l'heure est passée)",
         sch.prochaine_echeance({"schedule_kind": "daily", "time_of_day": time(7, 30)}, datetime(2026, 9, 7, 8, 0, tzinfo=PARIS))
         == datetime(2026, 9, 8, 7, 30, tzinfo=PARIS))

print("— la validation et le rythme lisible")
verifier("« tous les 3 jours » sans heure est refusé avec la raison",
         "heure" in (sch.valider_planification({"schedule_kind": "every_days", "interval_days": 3}) or ""))
verifier("« every_days » sans nombre de jours est refusé", "interval_days" in (sch.valider_planification({"schedule_kind": "every_days", "time_of_day": "09:00"}) or ""))
verifier("« le 40 du mois » est refusé", "day_of_month" in (sch.valider_planification({"schedule_kind": "monthly", "day_of_month": 40, "time_of_day": "09:00"}) or ""))
verifier("une planification juste passe", sch.valider_planification({"schedule_kind": "monthly", "day_of_month": 5, "time_of_day": "09:00"}) is None
         and sch.valider_planification({"schedule_kind": "every_days", "interval_days": 2, "time_of_day": "09:00"}) is None)
verifier("le rythme se dit en français",
         sch.rythme_lisible({"schedule_kind": "every_days", "interval_days": 3, "time_of_day": time(9, 0)}) == "tous les 3 jours à 09:00"
         and sch.rythme_lisible({"schedule_kind": "monthly", "day_of_month": 5, "time_of_day": "09:00"}) == "le 5 de chaque mois à 09:00"
         and sch.rythme_lisible({"schedule_kind": "weekly", "days_of_week": [1, 3], "time_of_day": time(8, 0)}) == "chaque lundi, mercredi à 08:00"
         and sch.rythme_lisible({"schedule_kind": "interval", "interval_minutes": 30}) == "toutes les 30 min"
         and sch.rythme_lisible({}) == "sur demande",
         [sch.rythme_lisible({"schedule_kind": "every_days", "interval_days": 3, "time_of_day": time(9, 0)}),
          sch.rythme_lisible({"schedule_kind": "weekly", "days_of_week": [1, 3], "time_of_day": time(8, 0)})])

print("— la tâche se souvient de sa conversation")
sk = (BACKEND / "tasks" / "skills.py").read_text(encoding="utf-8")
verifier("le skill lit tous_les_jours / jour_du_mois et les écrit avec le fil d'origine",
         '"interval_days": data.get("tous_les_jours")' in sk and '"day_of_month": data.get("jour_du_mois")' in sk
         and "interval_days, day_of_month, origin_thread_id)" in sk and 'data.get("_fil")' in sk)
verifier("« tous les 3 jours » écrit en interval avec des jours est compris comme every_days",
         'planification["schedule_kind"] = "every_days"' in sk)
ag1 = (BACKEND / "agents" / "agent1.py").read_text(encoding="utf-8")
verifier("la boucle d'actions pose le fil (`_fil`) pour creer_tache_agent SEULEMENT, depuis l'état, pas depuis le modèle",
         'if action["skill"] == "creer_tache_agent":' in ag1 and 'args = {**args, "_fil": state.get("thread_id")}' in ag1)
pr = (BACKEND / "skills" / "protocol.py").read_text(encoding="utf-8")
verifier("le catalogue dit les deux rythmes et que le compte rendu revient dans la conversation",
         "tous_les_jours=3" in pr and "jour_du_mois=5" in pr and "compte rendu DANS cette conversation" in pr)
mig = BACKEND / "database" / "migrations" / "036_planification_mois_jours.sql"
verifier("migration 036 : la contrainte accepte les deux rythmes, trois colonnes, idempotente",
         mig.exists() and "'every_days', 'monthly'" in mig.read_text(encoding="utf-8")
         and mig.read_text(encoding="utf-8").count("ADD COLUMN IF NOT EXISTS") == 3
         and "DROP CONSTRAINT IF EXISTS" in mig.read_text(encoding="utf-8"))

print("— le worker rapporte dans la conversation")
wk_src = BACKEND / "tasks" / "worker.py"
esp = {}
manque = fonctions(wk_src, ["texte_annonce"], esp)
verifier("`texte_annonce` existe", not manque, manque)
if not manque:
    ta = esp["texte_annonce"]
    ok = ta("Relances factures", "terminee", "3 relances envoyées.", "08/09/2026 à 09h00")
    verifier("terminée : un en-tête daté puis le compte rendu tel quel",
             ok.startswith("⏰ Tâche planifiée « Relances factures » — exécutée le 08/09/2026 à 09h00.") and ok.endswith("3 relances envoyées."))
    verifier("en attente d'accord : dit où approuver", "attend votre accord" in ta("X", "attente_accord", "", "…") and "À valider" in ta("X", "attente_accord", "", "…"))
    verifier("en échec : le dit", "ÉCHEC" in ta("X", "echec", "modèle absent", "…"))
wk = wk_src.read_text(encoding="utf-8")
verifier("les trois issues (terminée, accord en attente, échec) écrivent dans la conversation d'origine",
         wk.count("await _annoncer_dans_la_conversation(dict(tache), utilisateur,") == 3)
verifier("…au nom du créateur sous RLS, dans SON fil seulement (langgraph_thread_id ET user_id)",
         "get_rls_db(str(utilisateur.id), utilisateur.role)" in wk
         and "WHERE langgraph_thread_id = $1 AND user_id = $2::uuid" in wk)
verifier("…avec la métadonnée `tache_planifiee` (c'est elle que le chat reconnaît) et sans jamais lever",
         '"tache_planifiee": str(tache.get("id"))' in wk and "l'annonce est un confort, pas la tâche" in wk)
tb = (BACKEND / "routers" / "tableau.py").read_text(encoding="utf-8")
verifier("le tableau porte le rythme complet et le DERNIER compte rendu de chaque action planifiée",
         "t.interval_days, t.day_of_month" in tb and "LEFT JOIN LATERAL" in tb and "AS compte_rendu" in tb)

print("— l'écran")
tsx = (FRONTEND / "components" / "tableau" / "TableauDeBord.tsx").read_text(encoding="utf-8")
verifier("le tableau de bord dit le rythme en français et montre le dernier compte rendu",
         "function rythme(p: any): string" in tsx and "de chaque mois à" in tsx and "p.compte_rendu && (" in tsx
         and "Dernière exécution en échec" in tsx)
cw = (FRONTEND / "components" / "chat" / "ChatWindow.tsx").read_text(encoding="utf-8")
verifier("le chat relit son fil au repos (45 s, onglet visible, aucun tour en vol) et n'ajoute QUE les comptes rendus planifiés",
         "window.setInterval(relire, 45000)" in cw and 'meta.includes("tache_planifiee")' in cw
         and "if (!tid || loading || principalOccupeRef.current || document.visibilityState !== \"visible\") return" in cw
         and "!vus.has(String(m.id))" in cw)

print(f"\n{'═' * 72}")
if echecs:
    print(f"✗ {len(echecs)} échec(s) : " + ", ".join(echecs)); sys.exit(1)
print("✓ 0 échec")
