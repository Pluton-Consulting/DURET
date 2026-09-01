"""
Skill natif : déléguer une tâche à un agent depuis le chat.

C'est le déclencheur (a) du dispositif : « à partir de demain, chaque matin à
7h30, trie les mails de contact@ ». L'assistant crée la tâche ; il ne l'exécute
pas dans la foulée.

Effet `ecriture_interne` : créer une ligne ne produit aucun effet hors du
système. Quand la tâche s'exécutera, elle repassera par TOUS les contrôles —
identité rechargée, cloisonnement des boîtes, validation humaine pour toute
action externe. Créer une tâche ne contourne donc rien.
"""
from __future__ import annotations

import json
import logging

from fastapi import HTTPException, status

from database.connection import get_db
from tasks.scheduler import heure_du_jour, prochaine_echeance, valider_planification

logger = logging.getLogger("duret.tasks.skills")


class TacheInvalide(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


async def creer_tache_agent(data: dict, user) -> dict:
    """Crée une tâche planifiée ou manuelle, au nom de la personne connectée."""
    titre = (data.get("titre") or "").strip()
    consigne = (data.get("consigne") or data.get("prompt") or "").strip()
    if not titre or not consigne:
        raise TacheInvalide("Il faut un titre et une consigne pour créer une tâche.")

    planification = {
        "schedule_kind": (data.get("recurrence") or data.get("schedule_kind") or None),
        "interval_minutes": data.get("interval_minutes"),
        "time_of_day": data.get("heure") or data.get("time_of_day"),
        "days_of_week": data.get("jours") or data.get("days_of_week"),
    }
    erreur = valider_planification(planification)
    if erreur:
        raise TacheInvalide(erreur)

    planifiee = bool(planification["schedule_kind"])
    premiere = prochaine_echeance(planification) if planifiee else None

    async with get_db() as conn:
        ligne = await conn.fetchrow(
            """INSERT INTO agent_tasks
                   (user_id, title, task_prompt, params, trigger_kind, schedule_kind,
                    interval_minutes, time_of_day, days_of_week, next_run_at)
               VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6, $7, $8::time, $9, $10)
               RETURNING id, title, next_run_at""",
            str(user.id), titre[:255], consigne, json.dumps({}),
            "schedule" if planifiee else "manual",
            planification["schedule_kind"], planification["interval_minutes"],
            # `heure_du_jour` : asyncpg exige un `time`, pas une chaîne — sans
            # quoi toute tâche quotidienne échouait à la création.
            heure_du_jour(planification["time_of_day"]),
            planification["days_of_week"], premiere,
        )

    logger.info("Tâche « %s » créée par %s (planifiée=%s)", titre, user.id, planifiee)
    return {
        "tache_id": str(ligne["id"]),
        "titre": ligne["title"],
        "planifiee": planifiee,
        "prochaine_execution": ligne["next_run_at"].isoformat() if ligne["next_run_at"] else None,
        "message": (f"Tâche « {titre} » enregistrée."
                    + (f" Première exécution : {ligne['next_run_at']:%d/%m/%Y à %Hh%M}."
                       if ligne["next_run_at"] else
                       " Elle ne se déclenchera que sur demande.")),
    }


# ── VOIR, SUSPENDRE, SUPPRIMER ───────────────────────────────────────────
#
# Demande de Noa (01/09) : « une tâche créée par erreur doit pouvoir se
# supprimer en le demandant au chat aussi ».
#
# Il n'existait AUCUNE voie, ni écran ni chat : le catalogue ne portait que la
# création. Une tâche créée par mégarde en « toutes les 5 minutes » se
# réveillait indéfiniment, consommait du quota, et seul un accès direct à la
# base pouvait l'arrêter. Créer sans pouvoir défaire n'est pas une
# fonctionnalité, c'est un piège.
#
# EFFET `ecriture_interne`, PAS `externe` : supprimer une tâche ne produit rien
# hors du système, et la règle du projet réserve l'accord humain aux effets qui
# SORTENT (envoi, dépôt, tirage). Demander une confirmation ici irait contre la
# règle « une lecture se fait, on ne demande pas » — et Noa a explicitement
# demandé qu'on cesse de multiplier les confirmations.
#
# LE GARDE-FOU EST AILLEURS, ET IL EST PLUS SÛR QU'UNE CONFIRMATION : on ne
# DEVINE JAMAIS. Une désignation qui correspond à plusieurs tâches ne supprime
# rien du tout — elle les liste et demande laquelle. C'est ce qui évite qu'un
# « supprime la tâche des mails » efface les trois qui parlent de mails.

MAX_TACHES_LISTEES = 25


def _resume(ligne) -> dict:
    """Une tâche telle qu'on la montre : sans le prompt entier ni le secret."""
    return {
        "id": str(ligne["id"]),
        "titre": ligne["title"],
        "active": bool(ligne["enabled"]),
        "rythme": ligne["schedule_kind"],
        "prochaine": (ligne["next_run_at"].isoformat()
                      if ligne.get("next_run_at") else None),
    }


async def mes_taches(data: dict, user) -> dict:
    """Les tâches de la personne connectée, actives ou suspendues."""
    async with get_db() as conn:
        lignes = await conn.fetch(
            "SELECT id, title, enabled, schedule_kind, next_run_at "
            "FROM agent_tasks WHERE user_id = $1::uuid "
            "ORDER BY enabled DESC, next_run_at NULLS LAST LIMIT $2",
            str(user.id), MAX_TACHES_LISTEES)
    taches = [_resume(l) for l in lignes]
    if not taches:
        return {"taches": [], "nombre": 0,
                "message": "Aucune tâche enregistrée.",
                "a_faire": "Dis qu'il n'y en a aucune, et propose d'en créer une."}
    actives = sum(1 for t in taches if t["active"])
    return {
        "taches": taches, "nombre": len(taches), "actives": actives,
        "bloc_ui": {"type": "table", "titre": "Tâches enregistrées",
                    "colonnes": ["Tâche", "Rythme", "Prochaine", "État"],
                    "lignes": [[t["titre"], t["rythme"] or "sur demande",
                                (t["prochaine"] or "—")[:16].replace("T", " à "),
                                "active" if t["active"] else "suspendue"]
                               for t in taches]},
        "bloc_garanti": True,
        "message_final": (f"{len(taches)} tâche(s), dont {actives} active(s)."),
        "a_faire": ("Le tableau s'affiche automatiquement : n'écris aucun bloc "
                    "```ui pour lui. Pour agir sur une tâche, utilise son TITRE "
                    "exact avec `supprimer_tache` ou `suspendre_tache`."),
    }


async def _trouver(conn, user, designation: str) -> list:
    """Les tâches que cette désignation vise. Jamais de choix arbitraire."""
    brut = (designation or "").strip()
    if not brut:
        return []
    # Par identifiant exact d'abord : c'est ce que rend `mes_taches`.
    try:
        import uuid as _u
        _u.UUID(brut)
        ligne = await conn.fetchrow(
            "SELECT id, title, enabled, schedule_kind, next_run_at FROM agent_tasks "
            "WHERE id = $1::uuid AND user_id = $2::uuid", brut, str(user.id))
        return [ligne] if ligne else []
    except (ValueError, AttributeError):
        pass
    return list(await conn.fetch(
        "SELECT id, title, enabled, schedule_kind, next_run_at FROM agent_tasks "
        "WHERE user_id = $1::uuid AND title ILIKE $2 LIMIT 10",
        str(user.id), f"%{brut}%"))


def _ambigu(trouvees, verbe: str) -> dict:
    """Plusieurs candidates : on ne tranche pas à la place de la personne."""
    return {
        "ambigu": True,
        "candidates": [_resume(l) for l in trouvees],
        "message": (f"Plusieurs tâches correspondent, rien n'a été {verbe} : "
                    + ", ".join(f"« {l['title']} »" for l in trouvees[:6]) + "."),
        "a_faire": ("Ne choisis PAS à sa place : redemande laquelle, en citant "
                    "les titres ci-dessus."),
    }


async def supprimer_tache(data: dict, user) -> dict:
    """Supprime définitivement une tâche. Ses exécutions passées s'en vont avec.

    Ne supprime QUE les tâches de la personne connectée : l'identifiant vient du
    modèle, la propriété se vérifie en base — composer deux gestes ne compose
    pas les droits.
    """
    designation = (data.get("tache") or data.get("titre") or data.get("id")
                   or data.get("nom") or "")
    async with get_db() as conn:
        trouvees = await _trouver(conn, user, designation)
        if not trouvees:
            raise TacheInvalide(
                "Aucune tâche de ce nom. Appelle `mes_taches` pour voir la "
                "liste exacte, puis reprends le titre tel quel.")
        if len(trouvees) > 1:
            return _ambigu(trouvees, "supprimé")
        cible = trouvees[0]
        await conn.execute("DELETE FROM agent_tasks WHERE id = $1 AND user_id = $2::uuid",
                           cible["id"], str(user.id))
    logger.info("Tâche « %s » supprimée par %s", cible["title"], user.id)
    return {"supprimee": True, "titre": cible["title"],
            "message_final": f"La tâche « {cible['title']} » est supprimée. "
                             "Elle ne se réveillera plus."}


async def suspendre_tache(data: dict, user) -> dict:
    """Met une tâche en pause, ou la relance. Rien n'est perdu.

    C'est le geste à préférer quand on hésite : une tâche suspendue ne se
    réveille plus mais reste là, avec son historique — la supprimer, non.
    """
    designation = (data.get("tache") or data.get("titre") or data.get("id")
                   or data.get("nom") or "")
    brut = data.get("active")
    reprendre = str(brut).strip().lower() in ("true", "1", "oui", "reprendre", "active")
    async with get_db() as conn:
        trouvees = await _trouver(conn, user, designation)
        if not trouvees:
            raise TacheInvalide(
                "Aucune tâche de ce nom. Appelle `mes_taches` pour voir la liste.")
        if len(trouvees) > 1:
            return _ambigu(trouvees, "suspendu")
        cible = trouvees[0]
        # À la reprise, on recalcule l'échéance : celle d'origine est passée, et
        # une tâche relancée avec une date morte ne repartirait jamais.
        prochaine = None
        if reprendre:
            complete = await conn.fetchrow(
                "SELECT schedule_kind, interval_minutes, time_of_day, days_of_week "
                "FROM agent_tasks WHERE id = $1", cible["id"])
            prochaine = prochaine_echeance(dict(complete)) if complete else None
        await conn.execute(
            "UPDATE agent_tasks SET enabled = $2, next_run_at = "
            "  CASE WHEN $2 THEN $3 ELSE next_run_at END "
            "WHERE id = $1 AND user_id = $4::uuid",
            cible["id"], reprendre, prochaine, str(user.id))
    return {
        "titre": cible["title"], "active": reprendre,
        "message_final": (
            f"La tâche « {cible['title']} » "
            + (f"reprend{f' — prochaine exécution le {prochaine:%d/%m/%Y à %Hh%M}' if prochaine else ''}."
               if reprendre else "est suspendue. Elle ne se réveillera plus, mais rien n'est perdu.")),
    }
