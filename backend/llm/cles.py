"""
Résolution des identifiants de fournisseurs — base d'abord, `.env` ensuite.

Pourquoi : changer de fournisseur imposait d'éditer le `.env` sur le serveur
puis de redéployer. Une clé qui expire bloquait l'application jusqu'à la
prochaine session SSH. Les Paramètres permettent désormais de les saisir, et
cette couche fait le pont.

L'ordre est volontaire : la base SURCHARGE l'environnement. Une instance sans
aucune ligne en base se comporte exactement comme avant, ce qui rend le
changement neutre au déploiement.

Le cache est court (30 s). Une clé corrigée doit prendre effet tout de suite —
c'est justement le cas d'usage — mais interroger la base à chaque appel de
modèle serait absurde.
"""
from __future__ import annotations

import logging
import time

from config import settings

logger = logging.getLogger("duret.llm.cles")

# Clés surchargeables. Liste FERMÉE : on ne veut pas qu'une ligne fantaisiste en
# base puisse redéfinir n'importe quel réglage de l'application.
CLES_CONNUES = (
    "ollama_cloud_api_key",
    "longcat_api_key",
    "deepseek_api_key",
    "openrouter_api_key",
    "groq_api_key",
    "anthropic_api_key",
    "google_api_key",
)

DUREE_CACHE_S = 30

_CACHE: dict[str, str] = {}
_EXPIRE: float = 0.0


def masquer(valeur: str | None) -> str:
    """Empreinte affichable d'une clé : assez pour la reconnaître, pas pour s'en servir."""
    v = (valeur or "").strip()
    if not v:
        return ""
    if len(v) <= 10:
        return "•" * len(v)
    return f"{v[:4]}…{v[-4:]}"


async def rafraichir(force: bool = False) -> None:
    """Recharge les surcharges depuis la base. Ne lève jamais."""
    global _CACHE, _EXPIRE
    if not force and time.monotonic() < _EXPIRE:
        return
    _EXPIRE = time.monotonic() + DUREE_CACHE_S
    try:
        from database.connection import get_db
        async with get_db() as conn:
            lignes = await conn.fetch("SELECT cle, valeur FROM cles_api")
    except Exception as e:  # noqa: BLE001 - base indisponible : on garde le .env
        logger.debug("Surcharges de clés indisponibles (%s)", e)
        return
    _CACHE = {l["cle"]: l["valeur"] for l in lignes
              if l["cle"] in CLES_CONNUES and (l["valeur"] or "").strip()}


def valeur(nom: str) -> str | None:
    """Clé effective : surcharge en base si elle existe, sinon `.env`.

    Volontairement SYNCHRONE : appelée depuis la construction des modèles, qui
    ne peut pas attendre. Elle lit le cache — et RELANCE le rafraîchissement
    quand il est périmé, sans l'attendre.

    Ce déclenchement manquait, et une clé enregistrée dans Paramètres était
    IGNORÉE après chaque redéploiement : le cache ne se remplissait que si
    quelqu'un rouvrait la page Paramètres. Relevé en production — la clé
    Google créditée dormait en base pendant que l'application retombait sur
    celle du `.env`, au palier gratuit. L'appel courant garde la valeur du
    moment (le repli `.env`), le suivant a la bonne : au démarrage, la
    première lecture réelle arrive après le rafraîchissement du lifespan.
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
    """Écrit ou supprime une surcharge. Retourne l'empreinte masquée.

    Une valeur vide SUPPRIME la surcharge plutôt que d'enregistrer une chaîne
    vide : sans cela, effacer un champ désactiverait le fournisseur au lieu de
    revenir au `.env`, ce qui n'est jamais l'intention.
    """
    from database.connection import get_db

    if nom not in CLES_CONNUES:
        raise ValueError(f"Clé inconnue : {nom}")
    v = (brut or "").strip()
    async with get_db() as conn:
        if not v:
            await conn.execute("DELETE FROM cles_api WHERE cle = $1", nom)
        else:
            await conn.execute(
                "INSERT INTO cles_api (cle, valeur, updated_by) VALUES ($1, $2, $3::uuid) "
                "ON CONFLICT (cle) DO UPDATE SET valeur = EXCLUDED.valeur, "
                "  updated_at = NOW(), updated_by = EXCLUDED.updated_by",
                nom, v, user_id)
    await rafraichir(force=True)
    return masquer(v)


async def etat() -> list[dict]:
    """Pour l'interface : ce qui est configuré, et d'où ça vient. JAMAIS la valeur."""
    await rafraichir(force=True)
    lignes = []
    for nom in CLES_CONNUES:
        surcharge = _CACHE.get(nom)
        depuis_env = (getattr(settings, nom, None) or "").strip()
        effective = surcharge or depuis_env
        lignes.append({
            "cle": nom,
            "configuree": bool(effective),
            "origine": "parametres" if surcharge else ("env" if depuis_env else None),
            "empreinte": masquer(effective),
        })
    return lignes
