"""
File d'attente du chat : lancer une tâche pendant qu'une autre tourne.

CE QUE ÇA PERMET. L'utilisateur envoie une demande longue, puis une deuxième
sans attendre : la deuxième part ici, tourne en parallèle, et sa carte avance
dans la colonne de droite. Il peut en lancer plusieurs, fermer l'onglet,
revenir le lendemain — l'état vit en base, la reprise d'une validation vit dans
le checkpointer Postgres.

UN FIL PAR TÂCHE (`file:<id>`). Deux exécutions simultanées sur un même fil
LangGraph se disputeraient le checkpointer et corrompraient l'historique. C'est
le même choix que les tâches planifiées (`task:<id>`), pour la même raison.
La contrepartie est assumée : l'échange d'une tâche différée vit sur son propre
fil, pas dans l'historique de la conversation principale — comme les tâches
planifiées depuis toujours.

LA PROGRESSION vit en MÉMOIRE (`_VIVANTES`) et l'état durable en BASE. La
mémoire donne le libellé qui se renouvelle à l'écran sans marteler Postgres à
chaque nœud du graphe ; la base garantit qu'un redémarrage ne perd ni le
résultat ni l'attente de validation. Les tâches tuées par un redémarrage sont
requalifiées « interrompue » au démarrage — un état honnête, plutôt qu'un
« en cours » qui ne bougerait plus jamais.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.connection import get_db
from database.models import User
from security.audit import log_action

logger = logging.getLogger("duret.file_attente")

router = APIRouter()

# Progression vivante : id (str) -> {"progress": str, "node": str}.
# Volontairement SANS les réponses : le contenu ne dort pas en mémoire partagée.
_VIVANTES: dict[str, dict] = {}

# Trois tâches de front au plus. Au-delà, elles attendent leur tour : chaque
# tâche consomme des appels de modèle, et dix graphes simultanés se voleraient
# mutuellement les quotas du fournisseur pour finir tous plus tard.
MAX_SIMULTANEES = 3

# Plafond PAR PERSONNE, sur les tâches non terminées. Le sémaphore ci-dessus est
# global : sans ce second plafond, un seul compte peut y empiler des centaines
# de demandes et faire attendre tout le monde derrière — sans malveillance, une
# touche restée enfoncée suffit.
MAX_PAR_PERSONNE = 5

# Une tâche qui ne rend jamais la main garde son créneau pour toujours : trois
# graphes pendus (fournisseur muet, réseau coupé) gèlent la file entière jusqu'au
# redémarrage. Le délai est généreux — certains tours légitimes durent plusieurs
# minutes — mais il existe.
DELAI_MAX_S = 20 * 60

# La demande exécutée doit être CELLE QUI EST TRACÉE. Tronquer en base et
# exécuter le texte entier ferait diverger l'audit de la réalité.
MAX_CARACTERES_DEMANDE = 4000

_semaphore: Optional[asyncio.Semaphore] = None


def _porte() -> asyncio.Semaphore:
    """Le sémaphore, créé dans la boucle d'événements du serveur.

    Créé à l'import, il s'attacherait à la boucle du processus de MIGRATION ou
    d'un shell — et tout `acquire` ultérieur lèverait « attached to a different
    loop ». Paresseux, il naît dans la boucle qui s'en sert.
    """
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_SIMULTANEES)
    return _semaphore


class NouvelleTache(BaseModel):
    query: str


async def requalifier_interrompues() -> int:
    """Au démarrage : les tâches « en cours » d'avant le redémarrage sont mortes.

    Leur asyncio.Task n'existe plus ; les laisser « en_cours » afficherait une
    progression figée pour toujours. « interrompue » dit la vérité et laisse
    l'utilisateur relancer. Les `attente_validation` ne sont PAS touchées :
    leur reprise vit dans le checkpointer Postgres, elle survit au redémarrage.
    """
    async with get_db() as conn:
        n = await conn.fetchval(
            """WITH maj AS (
                   UPDATE taches_differees SET status = 'interrompue',
                          error = 'redémarrage du serveur pendant l''exécution',
                          updated_at = NOW()
                   WHERE status = 'en_cours' RETURNING 1)
               SELECT COUNT(*) FROM maj""")
    if n:
        logger.info("File d'attente : %d tâche(s) requalifiée(s) interrompue(s)", n)
    return int(n or 0)


def _libelle_echec(e: Exception) -> str:
    """Ce qu'on montre à l'utilisateur d'une panne. Jamais le message brut.

    `str(e)` d'un pilote Postgres ou d'un client HTTP contient des adresses
    internes, des noms d'hôte et parfois des fragments d'identifiants. Affiché
    sur une carte et conservé en base, il fuiterait l'infrastructure à qui
    regarde. Le détail complet part dans le journal serveur, où il est utile.
    """
    from agents.runtime import FilOccupe
    if isinstance(e, FilOccupe):
        return str(e)          # message métier, écrit pour être lu
    return ("Le traitement n'a pas abouti. L'incident est enregistré ; "
            "réessayez, et prévenez l'administrateur s'il se répète.")


async def _executer(tache_id: str, user_id: str, query: str) -> None:
    """Déroule une tâche dans le graphe habituel, en notant sa progression."""
    from agents import runtime
    from tasks.identity import charger_executant

    async with _porte():
        # Droits RECALCULÉS au moment d'exécuter, pas à la mise en file : un
        # compte désactivé entre-temps ne doit plus rien déclencher.
        utilisateur = await charger_executant(user_id)
        if utilisateur is None:
            await _terminer(tache_id, "echec", erreur="compte inactif")
            return

        fil = f"file:{tache_id}"
        _VIVANTES[tache_id] = {"progress": "je démarre la tâche", "node": ""}
        reponse_finale: Optional[str] = None
        validation_id: Optional[str] = None

        async def _derouler():
            nonlocal reponse_finale, validation_id
            async for ev in runtime.stream_turn(
                    query=query, user_id=str(utilisateur.id),
                    user_role=utilisateur.role,
                    has_attachment=False, thread_id=fil):
                t = ev.get("type")
                if t == "node":
                    vivante = _VIVANTES.get(tache_id)
                    if vivante is not None:
                        noeud = str(ev.get("node") or "")
                        if noeud:
                            vivante["node"] = noeud
                        libelle = ev.get("libelle")
                        if isinstance(libelle, str) and libelle.strip():
                            vivante["progress"] = libelle.strip()
                elif t == "final":
                    reponse_finale = ev.get("response") or ""
                elif t == "pending_validation":
                    validation_id = str(ev.get("validation_id") or "") or None

        try:
            await asyncio.wait_for(_derouler(), timeout=DELAI_MAX_S)
        except asyncio.TimeoutError:
            logger.warning("Tâche différée %s : délai de %d s dépassé",
                           tache_id, DELAI_MAX_S)
            await _terminer(tache_id, "echec",
                            erreur=f"délai dépassé ({DELAI_MAX_S // 60} min)")
            return
        except Exception as e:  # noqa: BLE001 - une tâche fautive ne tue pas les autres
            # Le message BRUT reste dans le journal serveur ; l'utilisateur, lui,
            # reçoit une phrase. Une erreur de pilote Postgres ou un corps
            # d'API fournisseur porte des adresses internes et des noms de
            # déploiement, qui n'ont rien à faire sur une carte de chat — ni à
            # dormir des mois dans une colonne de base.
            logger.warning("Tâche différée %s en échec : %s", tache_id, e, exc_info=True)
            await _terminer(tache_id, "echec", erreur=_libelle_echec(e))
            return
        finally:
            _VIVANTES.pop(tache_id, None)

        if validation_id:
            # SUSPENDUE, pas terminée : le graphe attend dans le checkpointer.
            # La carte de validation prend le relais à l'écran ; la reprise, à
            # l'approbation, remettra cette ligne à jour (routers/validation.py).
            await _terminer(tache_id, "attente_validation",
                            validation_id=validation_id,
                            progress="en attente de votre accord")
            return

        await _terminer(tache_id, "terminee", reponse=reponse_finale or "",
                        progress="terminée")


async def _terminer(tache_id: str, statut: str, *, reponse: Optional[str] = None,
                    erreur: Optional[str] = None, validation_id: Optional[str] = None,
                    progress: Optional[str] = None) -> None:
    async with get_db() as conn:
        await conn.execute(
            """UPDATE taches_differees
               SET status = $1,
                   response = COALESCE($2, response),
                   error = COALESCE($3, error),
                   validation_id = COALESCE($4::uuid, validation_id),
                   progress = COALESCE($5, progress),
                   updated_at = NOW()
               WHERE id = $6::uuid""",
            statut, reponse, erreur, validation_id, progress, tache_id)


@router.post("/taches")
async def lancer_tache(body: NouvelleTache, current_user: User = Depends(get_current_user)):
    """Met une demande en file : elle s'exécute en tâche de fond, tout de suite."""
    query = (body.query or "").strip()
    if not query:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Demande vide")
    if len(query) > MAX_CARACTERES_DEMANDE:
        # On REFUSE plutôt que de tronquer : tronquer en base tout en exécutant
        # le texte entier ferait diverger l'audit de ce qui a réellement tourné.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Demande trop longue ({len(query)} caractères, maximum "
                   f"{MAX_CARACTERES_DEMANDE}). Découpez-la.")

    async with get_db() as conn:
        # Plafond par personne : sans lui, un seul compte empile des centaines
        # de demandes derrière le sémaphore global et fait attendre tout le monde.
        en_cours = await conn.fetchval(
            """SELECT COUNT(*) FROM taches_differees
               WHERE user_id = $1 AND status IN ('en_cours', 'attente_validation')""",
            current_user.id)
        if int(en_cours or 0) >= MAX_PAR_PERSONNE:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Vous avez déjà {en_cours} tâches en cours ou en attente "
                       f"de validation (maximum {MAX_PAR_PERSONNE}). Attendez "
                       "qu'elles se terminent, ou tranchez les accords en attente.")

        ligne = await conn.fetchrow(
            """INSERT INTO taches_differees (user_id, query, status, progress)
               VALUES ($1, $2, 'en_cours', 'en file d''attente')
               RETURNING id""",
            current_user.id, query)
        tache_id = str(ligne["id"])
        await conn.execute(
            "UPDATE taches_differees SET thread_id = $1 WHERE id = $2::uuid",
            f"file:{tache_id}", tache_id)

    await log_action(action="tache_differee_lancee", user_id=str(current_user.id),
                     metadata={"tache_id": tache_id})
    # La requête HTTP répond tout de suite ; l'exécution vit sa vie. La
    # référence est gardée dans _VIVANTES via le runner lui-même — asyncio ne
    # ramasse pas une tâche référencée nulle part, d'où la variable nommée.
    execution = asyncio.create_task(
        _executer(tache_id, str(current_user.id), query),
        name=f"file:{tache_id}")
    _TACHES_ASYNCIO[tache_id] = execution
    execution.add_done_callback(lambda _t, i=tache_id: _TACHES_ASYNCIO.pop(i, None))
    return {"tache_id": tache_id}


# Références fortes vers les exécutions en cours : sans elles, le ramasse-miettes
# peut annuler une tâche asyncio en plein vol.
_TACHES_ASYNCIO: dict[str, asyncio.Task] = {}


@router.get("/etat")
async def etat(current_user: User = Depends(get_current_user)):
    """Tout ce que la colonne de droite affiche, en UNE requête.

    Les tâches (en cours, en attente, terminées non vues) ET les validations en
    suspens de la personne. Un seul appel sondé par l'écran plutôt que deux :
    la moitié des requêtes pour le même rafraîchissement.
    """
    async with get_db() as conn:
        # Les états OUVERTS passent devant, avant toute troncature : une tâche
        # qui tourne encore, ou un accord vieux de trois jours, ne doit pas
        # disparaître de l'écran parce que quinze demandes plus récentes sont
        # arrivées depuis. Le contrat est qu'ils RESTENT tant qu'on n'a pas
        # tranché — une limite qui les évince le romprait en silence.
        taches = await conn.fetch(
            """SELECT id, query, status, progress, error, validation_id, created_at
               FROM taches_differees
               WHERE user_id = $1
                 AND (status IN ('en_cours', 'attente_validation')
                      OR (status IN ('terminee', 'echec', 'interrompue') AND NOT vue))
               ORDER BY (status IN ('en_cours', 'attente_validation')) DESC,
                        created_at DESC
               LIMIT 30""",
            current_user.id)
        validations = await conn.fetch(
            """SELECT id, reason, payload, created_at
               FROM validations
               WHERE user_id = $1 AND status = 'pending'
               ORDER BY created_at DESC LIMIT 30""",
            current_user.id)

    import json as _json
    sortie_taches = []
    for t in taches:
        vivante = _VIVANTES.get(str(t["id"]), {})
        sortie_taches.append({
            "id": str(t["id"]),
            "query": t["query"],
            "status": t["status"],
            # La progression vivante (mémoire) prime sur la persistée (base).
            "progress": vivante.get("progress") or t["progress"] or "",
            "node": vivante.get("node") or "",
            "error": t["error"],
            "validation_id": str(t["validation_id"]) if t["validation_id"] else None,
            "created_at": t["created_at"].isoformat() if t["created_at"] else None,
        })

    sortie_validations = []
    for v in validations:
        charge = v["payload"]
        if isinstance(charge, str):
            try:
                charge = _json.loads(charge)
            except ValueError:
                charge = {}
        charge = charge or {}
        sortie_validations.append({
            "id": str(v["id"]),
            "reason": v["reason"],
            "skill": charge.get("skill"),
            "args": charge.get("args"),
            "created_at": v["created_at"].isoformat() if v["created_at"] else None,
        })

    # LE DROIT DE TRANCHER se dit à l'écran. `/etat` sert les accords au
    # DEMANDEUR, mais `/validations/{id}/resolve` exige `validate_skills` ou
    # `manage_users` : un employé ordinaire voyait deux boutons qui échouaient
    # à chaque clic. Deux routeurs qui se contredisent — l'un « c'est à toi de
    # décider », l'autre « tu n'as pas le droit » — se lisent comme une panne.
    from security.rbac import has_permission
    peut = (has_permission(current_user.role, "validate_skills")
            or has_permission(current_user.role, "manage_users"))

    return {"taches": sortie_taches, "validations": sortie_validations,
            "peut_decider": peut}


@router.get("/taches/{tache_id}")
async def detail_tache(tache_id: UUID, current_user: User = Depends(get_current_user)):
    """La réponse complète d'une tâche — pour l'afficher dans le chat au clic."""
    async with get_db() as conn:
        t = await conn.fetchrow(
            """SELECT id, query, status, response, error, created_at
               FROM taches_differees WHERE id = $1 AND user_id = $2""",
            tache_id, current_user.id)
    if not t:
        # L'appartenance fait partie du filtre : la tâche d'un autre n'existe
        # pas, plutôt qu'un 403 qui confirmerait un identifiant deviné.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Tâche introuvable")
    return {"id": str(t["id"]), "query": t["query"], "status": t["status"],
            "response": t["response"], "error": t["error"],
            "created_at": t["created_at"].isoformat() if t["created_at"] else None}


@router.post("/taches/{tache_id}/vu")
async def marquer_vue(tache_id: UUID, current_user: User = Depends(get_current_user)):
    """Ferme la carte à l'écran. La ligne reste : audit et relecture."""
    async with get_db() as conn:
        n = await conn.execute(
            "UPDATE taches_differees SET vue = TRUE, updated_at = NOW() "
            "WHERE id = $1 AND user_id = $2",
            tache_id, current_user.id)
    if n == "UPDATE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Tâche introuvable")
    return {"ok": True}
