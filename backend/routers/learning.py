"""
Router apprentissage — l'assistant relit une conversation et retient l'utile.

  POST /api/learning/analyser     : relit un fil, PROPOSE (n'écrit rien)
  POST /api/learning/enregistrer  : écrit les seules propositions cochées
  GET  /api/learning/dernier      : de quelle conversation on parle
  GET  /api/learning/historique   : les débriefs déjà passés

Déclenchement MANUEL uniquement : c'est un bouton dans l'onglet Auto-Évolution,
pas une tâche de fond. Rien n'entre en mémoire ni dans le catalogue de skills
sans qu'un humain ait vu et coché la proposition.
"""
import logging
import secrets
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status as http
from pydantic import BaseModel

from auth.dependencies import get_current_user
from database.models import User
from database.connection import get_db
from security.rbac import has_permission
from security.audit import log_action
from learning import debrief

logger = logging.getLogger("duret.learning.api")
router = APIRouter()

FEATURE = "manage_agent3"

# Propositions en attente de confirmation. En mémoire : elles ne survivent pas à
# un redémarrage, et c'est très bien — une analyse périmée se relance en un clic.
_ANALYSES: dict[str, dict] = {}
_TTL_S = 30 * 60
_MAX = 50


def _exiger(user: User) -> None:
    if not has_permission(user.role, FEATURE):
        raise HTTPException(status_code=http.HTTP_403_FORBIDDEN,
                            detail=f"Permission '{FEATURE}' requise")


def _purger() -> None:
    maintenant = time.monotonic()
    for k in [k for k, v in _ANALYSES.items() if v["expire"] < maintenant]:
        _ANALYSES.pop(k, None)
    while len(_ANALYSES) > _MAX:
        _ANALYSES.pop(min(_ANALYSES, key=lambda k: _ANALYSES[k]["expire"]), None)


class AnalyseBody(BaseModel):
    thread_id: Optional[str] = None


class EnregistrerBody(BaseModel):
    token: str
    connaissances: list[int] = []
    procedures: list[int] = []
    competences: list[int] = []


@router.get("/dernier")
async def derniere_conversation(current_user: User = Depends(get_current_user)):
    """Sur quoi porterait un débrief lancé maintenant."""
    _exiger(current_user)
    try:
        conv = await debrief.charger_conversation(str(current_user.id), current_user.role)
    except debrief.PasDeConversation as e:
        return {"disponible": False, "message": str(e)}
    return {"disponible": True, "thread_id": conv["thread_id"], "titre": conv["titre"],
            "date": conv["date"], "messages": len(conv["messages"])}


@router.post("/analyser")
async def analyser(body: AnalyseBody, current_user: User = Depends(get_current_user)):
    """Relit la conversation et propose ce qu'il y a à retenir. N'écrit rien."""
    _exiger(current_user)

    try:
        conv = await debrief.charger_conversation(
            str(current_user.id), current_user.role, body.thread_id)
    except debrief.PasDeConversation as e:
        raise HTTPException(status_code=http.HTTP_404_NOT_FOUND, detail=str(e))

    try:
        resultat = await debrief.analyser(conv)
    except RuntimeError as e:      # anonymisation HS -> on ne sort rien vers le LLM
        raise HTTPException(status_code=http.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("Débrief du fil %s échoué : %s", conv["thread_id"], e)
        raise HTTPException(status_code=http.HTTP_502_BAD_GATEWAY,
                            detail="L'analyse n'a pas abouti, réessayez dans un instant.")

    propositions = resultat["propositions"]
    total = sum(len(propositions[k]) for k in ("connaissances", "procedures", "competences"))

    _purger()
    token = secrets.token_urlsafe(24)
    _ANALYSES[token] = {
        "user_id": str(current_user.id),
        "expire": time.monotonic() + _TTL_S,
        "thread_id": conv["thread_id"],
        "titre": conv["titre"],
        "propositions": propositions,
        "entity_map": resultat["entity_map"],
    }

    await log_action(action="apprentissage_analyse", user_id=str(current_user.id),
                     model_used=resultat.get("model_used"),
                     metadata={"thread_id": conv["thread_id"], "propositions": total})

    return {
        "token": token,
        "thread_id": conv["thread_id"],
        "titre": conv["titre"],
        "messages": len(conv["messages"]),
        "total": total,
        **propositions,
    }


@router.post("/enregistrer")
async def enregistrer(body: EnregistrerBody, current_user: User = Depends(get_current_user)):
    """Écrit en mémoire / dans le catalogue les seules propositions cochées."""
    _exiger(current_user)

    _purger()
    entree = _ANALYSES.get(body.token)
    if not entree:
        raise HTTPException(status_code=http.HTTP_410_GONE,
                            detail="Analyse expirée ou inconnue — relancez le débrief.")
    if entree["user_id"] != str(current_user.id):
        raise HTTPException(status_code=http.HTTP_403_FORBIDDEN,
                            detail="Cette analyse ne vous appartient pas")

    from ingestion.pipeline import ingest_document
    from security.anonymizer import anonymizer

    props = entree["propositions"]
    carte = entree["entity_map"] or {}
    fil = entree["thread_id"]

    def _choisir(cle: str, indices: list[int]) -> list[dict]:
        items = props.get(cle) or []
        return [items[i] for i in sorted(set(indices)) if 0 <= i < len(items)]

    def _vrai(texte: str) -> str:
        """Les propositions viennent d'un modèle nourri au texte MASQUÉ : on
        remet les vraies valeurs avant de les ranger en mémoire, sinon la
        mémoire contiendrait « [PER_1] » et ne servirait à rien."""
        return anonymizer.rehydrate(texte or "", carte)

    chunks = 0
    memorise = 0
    echecs: list[str] = []

    for cle, source_type in (("connaissances", "apprentissage"), ("procedures", "procedure")):
        for i, item in enumerate(_choisir(cle, getattr(body, cle))):
            titre = _vrai(item["titre"])
            texte = f"{titre}\n\n{_vrai(item['contenu'])}"
            acces = item.get("acces", "all")
            try:
                chunks += await ingest_document(
                    text=texte,
                    source_type=source_type,
                    # Horodaté : deux débriefs du même fil s'ajoutent au lieu de
                    # s'écraser (`replace_existing` porte sur le source_id).
                    source_id=f"{source_type}:{fil}:{int(time.time())}:{i}",
                    source_filename=titre[:200],
                    access_level=acces,
                )
                memorise += 1
            except Exception as e:  # noqa: BLE001 - un élément fautif n'annule pas le reste
                logger.warning("Mémorisation de « %s » échouée : %s", titre[:60], e)
                echecs.append(titre[:80])

    # Compétences : brouillon dans le catalogue, JAMAIS activé d'office.
    skills_crees: list[str] = []
    for item in _choisir("competences", body.competences):
        try:
            code = await debrief.generer_code_skill(item)
            if not code:
                echecs.append(item["nom"])
                continue
            async with get_db() as conn:
                await conn.execute(
                    """INSERT INTO skills (name, description, code, prompt_template,
                                           status, created_by, enabled)
                       VALUES ($1, $2, $3, $4, 'draft', 'apprentissage', false)
                       ON CONFLICT (name) DO UPDATE
                           SET code = EXCLUDED.code,
                               description = EXCLUDED.description,
                               prompt_template = EXCLUDED.prompt_template,
                               version = skills.version + 1,
                               status = 'draft',
                               enabled = false,
                               updated_at = NOW()""",
                    item["nom"], _vrai(item["description"]), code,
                    _vrai(item.get("entrees") or ""),
                )
            skills_crees.append(item["nom"])
        except Exception as e:  # noqa: BLE001
            logger.warning("Création du skill %s échouée : %s", item["nom"], e)
            echecs.append(item["nom"])

    _ANALYSES.pop(body.token, None)
    await log_action(action="apprentissage_enregistre", user_id=str(current_user.id),
                     metadata={"thread_id": fil, "memorise": memorise, "chunks": chunks,
                               "skills": skills_crees, "echecs": len(echecs)})

    return {"ok": True, "memorise": memorise, "chunks": chunks,
            "skills": skills_crees, "echecs": echecs}


class EnrichissementBody(BaseModel):
    collecter: bool = True          # relancer d'abord la synchronisation des boîtes
    max_lots_par_boite: int = 8
    # Par défaut la campagne EXIGE le modèle principal et s'arrête s'il
    # n'est pas disponible : ce qu'elle écrit reste en mémoire.
    exiger_modele_principal: bool = True


@router.post("/enrichir")
async def enrichir(body: EnrichissementBody, current_user: User = Depends(get_current_user)):
    """Lance la campagne d'enrichissement sur TOUTES les boîtes. Administration.

    Elle tourne en TÂCHE DE FOND : sur un corpus réel l'opération dure des
    heures, une requête HTTP expirerait bien avant. On répond immédiatement, et
    l'avancement se suit sur `/enrichir/statut`.
    """
    import asyncio

    from learning import enrichissement

    # Lire TOUTES les boîtes dépasse de loin la gestion d'Agent 3 : c'est un
    # accès transverse à la correspondance de l'entreprise entière. On exige
    # donc la permission la plus haute, pas celle de l'apprentissage.
    if not has_permission(current_user.role, "manage_system"):
        raise HTTPException(status_code=http.HTTP_403_FORBIDDEN,
                            detail="Réservé à l'administration système : cette campagne "
                                   "lit toutes les boîtes mail.")

    if enrichissement.etat().get("en_cours"):
        raise HTTPException(status_code=http.HTTP_409_CONFLICT,
                            detail="Une campagne est déjà en cours.")

    await log_action(action="enrichissement_lance", user_id=str(current_user.id),
                     metadata={"collecter": body.collecter,
                               "max_lots_par_boite": body.max_lots_par_boite})

    asyncio.create_task(enrichissement.executer(
        lance_par=current_user.email,
        collecter=body.collecter,
        max_lots_par_boite=max(1, min(body.max_lots_par_boite, 40)),
        exiger_modele_principal=body.exiger_modele_principal))

    return {"lance": True,
            "note": ("La campagne tourne en tâche de fond. Les connaissances déduites "
                     "sont rangées en accès direction, les compétences en brouillon "
                     "désactivé : rien n'est exécutable sans relecture.")}


@router.get("/enrichir/statut")
async def statut_enrichissement(current_user: User = Depends(get_current_user)):
    """Avancement de la campagne en cours, ou bilan de la dernière."""
    _exiger(current_user)
    from learning import enrichissement
    return enrichissement.etat()


@router.get("/historique")
async def historique(limit: int = 10, current_user: User = Depends(get_current_user)):
    """Débriefs déjà enregistrés (journal d'audit, source de vérité immuable)."""
    _exiger(current_user)
    limit = max(1, min(limit, 50))
    async with get_db() as conn:
        lignes = await conn.fetch(
            "SELECT u.email, a.metadata, a.created_at FROM audit_log a "
            "LEFT JOIN users u ON u.id = a.user_id "
            "WHERE a.action = 'apprentissage_enregistre' "
            "ORDER BY a.created_at DESC LIMIT $1",
            limit)
    import json as _json
    resultats = []
    for l in lignes:
        meta = l["metadata"]
        if isinstance(meta, str):
            try:
                meta = _json.loads(meta)
            except ValueError:
                meta = {}
        resultats.append({"par": l["email"], "date": l["created_at"].isoformat(),
                          **(meta or {})})
    return resultats
