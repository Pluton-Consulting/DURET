"""
Réglages système NON SECRETS — base d'abord, `.env` ensuite.

Jumeau de `llm/cles.py`, pour ce qui n'est pas un secret. Même ordre de
résolution (la base SURCHARGE l'environnement), même cache court, même
discipline de rafraîchissement — et UNE différence assumée : ici la valeur
est LISIBLE. Un réglage qu'on ne peut pas relire est un réglage qu'on ne peut
pas vérifier, et `cles_api` garde son invariant intact (voir migration 026).

Pourquoi ce module existe : `llm_tete` force un modèle en tête de cascade pour
essayer un fournisseur sur des tours réels. C'est le réglage le plus
expérimental du socle, et c'était le plus coûteux à changer — éditer le `.env`
de chaque VPS, puis recréer le conteneur. Deux clients, deux serveurs, deux
sessions SSH pour un essai qu'on veut pouvoir annuler en dix secondes.
"""
from __future__ import annotations

import logging
import time

from config import settings

logger = logging.getLogger("duret.llm.reglages")

# Liste FERMÉE, comme pour les clés : une ligne fantaisiste en base ne doit pas
# pouvoir redéfinir n'importe quel attribut de la configuration.
REGLAGES_CONNUS = (
    "llm_tete",
)

DUREE_CACHE_S = 30

_CACHE: dict[str, str] = {}
_EXPIRE: float = 0.0


async def rafraichir(force: bool = False) -> None:
    """Recharge les surcharges depuis la base. Ne lève jamais."""
    global _CACHE, _EXPIRE
    if not force and time.monotonic() < _EXPIRE:
        return
    _EXPIRE = time.monotonic() + DUREE_CACHE_S
    try:
        from database.connection import get_db
        async with get_db() as conn:
            lignes = await conn.fetch("SELECT cle, valeur FROM reglages")
    except Exception as e:  # noqa: BLE001 - base indisponible : on garde le .env
        logger.debug("Surcharges de réglages indisponibles (%s)", e)
        return
    _CACHE = {l["cle"]: l["valeur"] for l in lignes
              if l["cle"] in REGLAGES_CONNUS and (l["valeur"] or "").strip()}


def valeur(nom: str) -> str | None:
    """Réglage effectif : surcharge en base si elle existe, sinon `.env`.

    SYNCHRONE à dessein : appelée depuis la construction des cascades, qui ne
    peut pas attendre. Elle lit le cache et RELANCE le rafraîchissement quand
    il est périmé, sans l'attendre.

    Ce second déclenchement n'est pas décoratif : sans lui, le cache ne se
    remplirait qu'à l'ouverture de la page Paramètres, et un réglage
    enregistré serait ignoré après chaque redéploiement. C'est le bug exact
    qu'a connu `llm/cles.py` (commit `fe6e106`), et il a coûté une saga
    entière — on ne le refait pas.
    """
    if time.monotonic() >= _EXPIRE:
        try:
            import asyncio
            asyncio.get_running_loop().create_task(rafraichir())
        except RuntimeError:
            pass  # hors boucle (script) : le repli .env reste le comportement
    if nom in _CACHE:
        return _CACHE[nom]
    return getattr(settings, nom, None)


async def enregistrer(nom: str, brut: str | None, user_id: str) -> str:
    """Écrit ou supprime une surcharge. Retourne la valeur effective.

    Une valeur vide SUPPRIME la surcharge plutôt que d'enregistrer une chaîne
    vide : vider le champ doit rendre la main au `.env`, jamais imposer un
    réglage vide — ce n'est jamais l'intention de qui efface.
    """
    # Le refus vient AVANT tout contact avec la base : un nom hors liste ne
    # doit rien ouvrir du tout, pas même une connexion.
    if nom not in REGLAGES_CONNUS:
        raise ValueError(f"Réglage inconnu : {nom}")
    from database.connection import get_db

    v = (brut or "").strip()
    async with get_db() as conn:
        if not v:
            await conn.execute("DELETE FROM reglages WHERE cle = $1", nom)
        else:
            await conn.execute(
                "INSERT INTO reglages (cle, valeur, updated_by) VALUES ($1, $2, $3::uuid) "
                "ON CONFLICT (cle) DO UPDATE SET valeur = EXCLUDED.valeur, "
                "  updated_at = NOW(), updated_by = EXCLUDED.updated_by",
                nom, v, user_id)
    await rafraichir(force=True)
    return valeur(nom) or ""


async def etat() -> list[dict]:
    """Pour l'interface : la valeur en vigueur, et d'où elle vient."""
    await rafraichir(force=True)
    lignes = []
    for nom in REGLAGES_CONNUS:
        surcharge = _CACHE.get(nom)
        depuis_env = (getattr(settings, nom, None) or "").strip()
        lignes.append({
            "cle": nom,
            "valeur": surcharge or depuis_env or "",
            "origine": "parametres" if surcharge else ("env" if depuis_env else None),
        })
    return lignes
