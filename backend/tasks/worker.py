"""
Worker des tâches d'agent — réveille les tâches planifiées et draine les exécutions.

Boucle asyncio dans le processus backend, sur le même patron que le worker de
vectorisation. Un service séparé devrait ré-importer toute la pile (cascade LLM,
anonymiseur spaCy, autorisations) pour 150 à 300 Mo supplémentaires sur un VPS
déjà contraint. La durabilité ne vient pas du conteneur mais de Postgres : un
redémarrage ne perd rien, il requalifie les exécutions interrompues.

Une exécution emprunte EXACTEMENT le même graphe que le chat : anonymisation,
boucle d'outils, validation humaine. Une tâche autonome n'a donc aucun privilège
particulier — c'est le point essentiel du dispositif.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from database.connection import get_db
from security.audit import log_action
from tasks.identity import charger_executant
from tasks.scheduler import prochaine_echeance

logger = logging.getLogger("duret.tasks.worker")

INTERVALLE_TICK_S = 30      # cadence de réveil
MAX_REVEILS_PAR_TICK = 3    # borne le nombre de tâches déclenchées d'un coup
MAX_RUNS_PAR_TICK = 2       # borne les exécutions simultanées (un petit VPS)

_task: Optional[asyncio.Task] = None
_stop = False


async def _requalifier_runs_interrompus() -> None:
    """Au démarrage : les exécutions restées « running » ont été coupées net."""
    try:
        async with get_db() as conn:
            n = await conn.fetchval(
                """UPDATE agent_task_runs
                   SET status = 'failed', error = 'interrompu par un redémarrage',
                       updated_at = NOW()
                   WHERE status = 'running'
                   RETURNING (SELECT COUNT(*) FROM agent_task_runs WHERE status = 'running')""")
        if n:
            logger.warning("%s exécution(s) interrompue(s) requalifiée(s) en échec", n)
    except Exception as e:  # noqa: BLE001 - la table peut ne pas exister avant migration
        logger.info("Requalification des exécutions ignorée : %s", e)


async def _reveiller_taches_dues() -> int:
    """Crée une exécution pour chaque tâche arrivée à échéance. Retourne le nombre créé."""
    crees = 0
    async with get_db() as conn:
        async with conn.transaction():
            # SKIP LOCKED : si un jour deux processus tournent, aucun ne déclenche
            # la même tâche deux fois.
            taches = await conn.fetch(
                """SELECT * FROM agent_tasks
                   WHERE enabled AND next_run_at IS NOT NULL AND next_run_at <= NOW()
                   ORDER BY next_run_at
                   LIMIT $1
                   FOR UPDATE SKIP LOCKED""",
                MAX_REVEILS_PAR_TICK)

            for tache in taches:
                await conn.execute(
                    """INSERT INTO agent_task_runs (task_id, user_id, status, trigger_kind)
                       VALUES ($1, $2, 'pending', 'schedule')""",
                    tache["id"], tache["user_id"])
                # Échéance recalculée AVANT l'exécution : même si le run échoue,
                # la tâche repartira à la bonne heure, sans rattrapage en rafale.
                suivante = prochaine_echeance(dict(tache))
                await conn.execute(
                    "UPDATE agent_tasks SET next_run_at = $1, updated_at = NOW() WHERE id = $2",
                    suivante, tache["id"])
                crees += 1
    return crees


async def _reclamer_run() -> Optional[dict]:
    """Prend une exécution en attente, de façon atomique."""
    async with get_db() as conn:
        ligne = await conn.fetchrow(
            """UPDATE agent_task_runs
               SET status = 'running', started_at = NOW(), updated_at = NOW()
               WHERE id = (
                   SELECT id FROM agent_task_runs
                   WHERE status = 'pending'
                   ORDER BY created_at
                   LIMIT 1
                   FOR UPDATE SKIP LOCKED
               )
               RETURNING *""")
    return dict(ligne) if ligne else None


async def _terminer(run_id, statut: str, resultat=None, erreur: Optional[str] = None) -> None:
    import json
    async with get_db() as conn:
        await conn.execute(
            """UPDATE agent_task_runs
               SET status = $1, result = $2, error = $3, updated_at = NOW()
               WHERE id = $4""",
            statut, json.dumps(resultat) if resultat is not None else None, erreur, run_id)


async def _executer(run: dict) -> None:
    """Exécute une tâche, au nom de son créateur, dans le graphe habituel."""
    from agents import runtime
    # LES TÂCHES DE FOND ONT LEUR PROPRE BUDGET (01/09) : sans lui, une
    # campagne prendrait tous les créneaux du fournisseur et gèlerait le chat.
    from config import settings
    from llm.concurrence import porter
    porter("fond:taches", int(getattr(settings, "llm_simultanes_fond", 2) or 2))

    async with get_db() as conn:
        tache = await conn.fetchrow("SELECT * FROM agent_tasks WHERE id = $1", run["task_id"])
    if tache is None:
        await _terminer(run["id"], "failed", erreur="tâche supprimée")
        return

    # Droits RECALCULÉS ici, pas à la création : un compte désactivé depuis, ou
    # dont une délégation a été révoquée, ne doit plus rien pouvoir déclencher.
    utilisateur = await charger_executant(run["user_id"])
    if utilisateur is None:
        await _terminer(run["id"], "failed", erreur="identity_refused")
        await log_action(action="task_identity_refused", success=False,
                         on_behalf_of=str(run["user_id"]),
                         trigger_type=run["trigger_kind"], trigger_id=str(run["id"]),
                         metadata={"task": str(run["task_id"])})
        logger.warning("Exécution %s refusée : compte inactif", run["id"])
        return

    fil = f"task:{run['id']}"
    async with get_db() as conn:
        await conn.execute("UPDATE agent_task_runs SET thread_id = $1 WHERE id = $2",
                           fil, run["id"])

    await log_action(action="task_triggered", user_id=str(utilisateur.id),
                     on_behalf_of=str(utilisateur.id),
                     trigger_type=run["trigger_kind"], trigger_id=str(run["id"]),
                     metadata={"task": str(run["task_id"]), "titre": tache["title"]})

    try:
        resultat = await runtime.run_turn(
            query=tache["task_prompt"],
            user_id=str(utilisateur.id),
            user_role=utilisateur.role,
            has_attachment=False,
            thread_id=fil,
            trigger_kind=run["trigger_kind"],
        )
    except Exception as e:  # noqa: BLE001 - une tâche fautive ne tue pas le worker
        logger.warning("Exécution %s en échec : %s", run["id"], e)
        await _terminer(run["id"], "failed", erreur=str(e)[:500])
        await log_action(action="task_failed", user_id=str(utilisateur.id),
                         on_behalf_of=str(utilisateur.id), success=False,
                         trigger_type=run["trigger_kind"], trigger_id=str(run["id"]))
        return

    if resultat.get("status") == "pending_validation":
        # L'exécution est SUSPENDUE, pas terminée : une action à effet externe
        # attend une décision humaine. Le graphe est dans le checkpointer Postgres,
        # il survivra à un redémarrage ; la reprise se fera à la validation.
        await _terminer(run["id"], "awaiting_approval",
                        resultat={"validation_id": resultat.get("validation_id"),
                                  "reponse": resultat.get("response")})
        logger.info("Exécution %s en attente de validation", run["id"])
        return

    await _terminer(run["id"], "completed", resultat={"reponse": resultat.get("response")})
    await log_action(action="task_completed", user_id=str(utilisateur.id),
                     on_behalf_of=str(utilisateur.id),
                     trigger_type=run["trigger_kind"], trigger_id=str(run["id"]))
    logger.info("Exécution %s terminée", run["id"])


# ── LA PASSE DE NUIT SUR LES PORTRAITS ───────────────────────────────────
#
# Demande de Noa : « tous les jours à minuit, pour chaque utilisateur, il relit
# la conversation complète pour apprendre au max de l'utilisateur ».
#
# Elle vit DANS la boucle du worker plutôt que dans une tâche planifiée en base,
# et ce n'est pas un raccourci : une tâche en base devrait être créée quelque
# part, pour quelqu'un, avec un propriétaire et des droits — or celle-ci
# n'appartient à personne, elle traite TOUT LE MONDE. La mettre en base
# obligerait à inventer un utilisateur système, c'est-à-dire un compte qui peut
# tout lire et que personne ne surveille.
#
# LA FENÊTRE, ET POURQUOI ELLE EST LARGE. Le repère de « déjà fait aujourd'hui »
# vit en mémoire du processus : un redémarrage l'oublie. Sans fenêtre, un
# conteneur relancé à 14 h relancerait la passe en pleine journée, au moment où
# les créneaux du fournisseur servent le chat. Entre minuit et cinq heures, une
# passe de trop ne dérange personne — et le curseur fait qu'elle ne relit rien.
_FENETRE_NUIT = (0, 5)
_derniere_passe_profils: Optional[str] = None


async def _passe_profils_si_due() -> None:
    """Met à jour les portraits une fois par nuit. Ne lève jamais."""
    global _derniere_passe_profils
    try:
        from tasks.scheduler import _paris
        maintenant = _paris()
        if not (_FENETRE_NUIT[0] <= maintenant.hour < _FENETRE_NUIT[1]):
            return
        jour = maintenant.date().isoformat()
        if _derniere_passe_profils == jour:
            return
        # Posé AVANT la passe : si elle échoue, on ne la rejoue pas en boucle
        # toute la nuit — elle repartira demain, et le curseur n'a pas bougé.
        _derniere_passe_profils = jour
        from learning.profil_utilisateur import passe_de_nuit
        bilan = await passe_de_nuit()
        logger.info("Portraits : %s", bilan)
    except Exception as e:  # noqa: BLE001 - une passe de fond ne casse jamais la boucle
        logger.warning("Passe de nuit sur les portraits : %s", e)


async def _boucle() -> None:
    global _stop
    await _requalifier_runs_interrompus()

    while not _stop:
        try:
            await _reveiller_taches_dues()
            await _passe_profils_si_due()

            traites = 0
            while traites < MAX_RUNS_PAR_TICK and not _stop:
                run = await _reclamer_run()
                if run is None:
                    break
                await _executer(run)
                traites += 1

            await asyncio.sleep(1 if traites else INTERVALLE_TICK_S)
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001 - la boucle ne doit jamais mourir
            logger.warning("Worker de tâches : %s", e)
            await asyncio.sleep(INTERVALLE_TICK_S)


async def start_task_worker() -> None:
    global _task, _stop
    from config import settings
    if not getattr(settings, "agent_tasks_enabled", True):
        logger.info("Worker de tâches désactivé (agent_tasks_enabled=false)")
        return
    _stop = False
    _task = asyncio.create_task(_boucle())
    logger.info("Worker de tâches démarré (tick %ds)", INTERVALLE_TICK_S)


async def stop_task_worker() -> None:
    global _stop
    _stop = True
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
