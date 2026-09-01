"""
Combien d'appels de modèle partent EN MÊME TEMPS.

POURQUOI. L'abonnement du fournisseur autorise un nombre fixe d'appels de
front (dix pour l'offre en cours). Au-delà, il met en file, puis refuse — et
un refus se paie cher chez nous : le disjoncteur de `llm/router.py` met le
modèle en quarantaine cinq minutes sur un 429. Mieux vaut attendre ICI, où
l'attente est bornée, mesurable et journalisée, que se faire refuser là-bas.

DEUX ÉTAGES, dans cet ordre d'acquisition :
  1. par PERSONNE — empêche qu'un seul compte prenne tous les créneaux ;
  2. GLOBAL — la limite du fournisseur, avec une marge sous la sienne.
L'ordre compte : prendre le créneau global d'abord ferait attendre quelqu'un
sur son propre plafond TOUT EN TENANT un créneau du fournisseur, donc en le
gaspillant.

CE QUE LA PORTE ENTOURE : l'appel réseau, et rien de plus. Ni le tour, ni la
cascade — un candidat mort retiendrait un créneau pendant qu'on essaie le
suivant. Un tour de quinze appels séquentiels n'occupe donc qu'un créneau à la
fois, ce qui est exactement ce que compte le fournisseur.

QUAND C'EST PLEIN : on ATTEND, borné (`llm_attente_max_s`). Au moment où
l'appel part, le tour a déjà payé une recherche, de la mémoire, peut-être un
skill : le refuser jetterait ce travail. Passé le délai, `TropDeDemandes` — le
tour échoue proprement par les chemins d'erreur existants, et JAMAIS on ne
bloque pour toujours. Le refus rapide, lui, existe déjà en amont (file
d'attente, verrou de fil) : c'est là qu'il a du sens.
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Optional

from config import settings

logger = logging.getLogger("duret.llm.concurrence")


class TropDeDemandes(RuntimeError):
    """Le service est saturé — levée seulement après l'attente maximale."""


# QUI consomme les créneaux, et combien il a le droit d'en tenir. Un ContextVar
# et non un argument : la valeur suit la tâche asyncio et TOUS ses `await`
# descendants, à travers LangGraph, sans traverser quinze signatures.
PERSONNE: ContextVar[tuple[str, int]] = ContextVar("llm_personne", default=("", 0))


def porter(identifiant: str, plafond: int) -> None:
    """Déclare qui consomme, pour la durée de la tâche asyncio courante.

    À poser AVANT d'entrer dans le graphe. Un ContextVar posé avant
    `asyncio.create_task` est copié dans la tâche fille ; posé après, il ne
    l'atteint pas — c'est le seul piège de ce mécanisme.
    """
    PERSONNE.set((str(identifiant or ""), max(0, int(plafond or 0))))


# LES SÉMAPHORES SONT MÉMORISÉS AVEC LEUR BOUCLE ET LEUR PLAFOND.
# Un sémaphore créé dans une autre boucle d'événements lève « attached to a
# different loop » (leçon déjà payée dans routers/file_attente.py) ; et le
# plafond entre dans la clé pour qu'un changement de réglage reconstruise
# l'objet. Conséquence assumée : pendant la seconde qui suit un changement,
# les appels DÉJÀ en vol tiennent l'ancien sémaphore — on peut dépasser
# transitoirement. C'est préférable à un plafond qu'on ne peut plus changer.
_GLOBAL: dict[tuple, asyncio.Semaphore] = {}
_PAR_PERSONNE: dict[tuple, asyncio.Semaphore] = {}


def _boucle():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def plafond_global() -> int:
    """Le plafond global : réglage en base d'abord, défaut du code ensuite."""
    try:
        from llm.reglages import texte
        # `texte()` et pas `valeur()` : ce réglage est un ENTIER dans la
        # configuration, et `8.strip()` levait — l'exception était avalée juste
        # en dessous, si bien que le réglage d'écran n'avait AUCUN effet. Un
        # bug muet, pire que le 500 qu'il causait ailleurs.
        brut = texte("llm_simultanes")
        if brut.isdigit() and 1 <= int(brut) <= 64:
            return int(brut)
    except Exception:  # noqa: BLE001 - un réglage illisible ne bloque pas les appels
        pass
    return max(1, int(getattr(settings, "llm_simultanes", 8) or 8))


def _porte_globale() -> asyncio.Semaphore:
    n = plafond_global()
    cle = (id(_boucle()), n)
    sem = _GLOBAL.get(cle)
    if sem is None:
        _GLOBAL.clear()                 # un seul plafond global à la fois
        sem = _GLOBAL[cle] = asyncio.Semaphore(n)
    return sem


def _porte_personne(identifiant: str, plafond: int) -> Optional[asyncio.Semaphore]:
    if not identifiant or plafond <= 0:
        return None                      # personne déclarée : seul le global s'applique
    cle = (id(_boucle()), identifiant, plafond)
    sem = _PAR_PERSONNE.get(cle)
    if sem is None:
        if len(_PAR_PERSONNE) > 256:
            _PAR_PERSONNE.clear()
        sem = _PAR_PERSONNE[cle] = asyncio.Semaphore(plafond)
    return sem


@asynccontextmanager
async def porte_llm():
    """Un créneau du fournisseur, le temps d'un appel."""
    delai = max(1, int(getattr(settings, "llm_attente_max_s", 90) or 90))
    identifiant, plafond = PERSONNE.get()
    perso = _porte_personne(identifiant, plafond)
    debut = time.monotonic()

    if perso is not None:
        try:
            await asyncio.wait_for(perso.acquire(), timeout=delai)
        except asyncio.TimeoutError:
            raise TropDeDemandes(
                f"trop d'appels simultanés pour ce compte (plafond {plafond}) : "
                f"rien ne s'est libéré en {delai} s.")
    try:
        glob = _porte_globale()
        try:
            await asyncio.wait_for(glob.acquire(), timeout=delai)
        except asyncio.TimeoutError:
            raise TropDeDemandes(
                f"le service est saturé (plafond global {plafond_global()}) : "
                f"aucun créneau libre en {delai} s.")
        attente = time.monotonic() - debut
        if attente > 1:
            logger.info("Appel LLM mis en attente %.1f s (%s)", attente, identifiant or "anonyme")
        try:
            yield
        finally:
            glob.release()
    finally:
        # Un `wait_for` annulé doit relâcher ce qui a DÉJÀ été pris : sans ce
        # finally, une annulation de tour fuirait un créneau à chaque fois.
        if perso is not None:
            perso.release()


# ── Le plafond d'une personne : compte, puis rôle, puis défaut ───────────
_CACHE: dict[str, tuple[float, int]] = {}
_DUREE_CACHE_S = 60


async def limite_de(user_id: Optional[str], role: Optional[str] = None) -> int:
    """Combien d'appels simultanés ce compte a le droit de tenir.

    Lue UNE fois par tour (le routeur la relirait à chaque appel, soit quinze
    requêtes par tour). Ne lève jamais : base injoignable → le défaut.
    """
    defaut = max(1, int(getattr(settings, "llm_simultanes_personne", 3) or 3))
    if not user_id:
        return defaut
    cle = str(user_id)
    fige = _CACHE.get(cle)
    if fige and (time.monotonic() - fige[0]) < _DUREE_CACHE_S:
        return fige[1]
    valeur = defaut
    try:
        from database.connection import get_db
        async with get_db() as conn:
            ligne = await conn.fetchrow(
                "SELECT u.llm_simultanes AS perso, r.concurrent_limit AS par_role "
                "FROM users u LEFT JOIN role_quota_config r ON r.role = u.role "
                "WHERE u.id = $1::uuid", cle)
        if ligne:
            # Le compte prime sur le rôle, le rôle sur le défaut. NULL n'est
            # pas « zéro » : un plafond nul empêcherait la personne de se
            # servir de l'assistant.
            for candidat in (ligne["perso"], ligne["par_role"]):
                if candidat is not None and int(candidat) > 0:
                    valeur = int(candidat)
                    break
    except Exception as e:  # noqa: BLE001 - une limite illisible ne bloque personne
        logger.info("Plafond de concurrence illisible (%s) : défaut %d", type(e).__name__, defaut)
    if len(_CACHE) > 512:
        _CACHE.clear()
    _CACHE[cle] = (time.monotonic(), valeur)
    return valeur


def etat() -> dict:
    """Ce que l'écran d'administration montre : plafonds et créneaux libres."""
    glob = None
    for sem in _GLOBAL.values():
        glob = sem
    return {
        "plafond_global": plafond_global(),
        "libres": getattr(glob, "_value", None) if glob is not None else None,
        "plafond_personne_defaut": int(getattr(settings, "llm_simultanes_personne", 3) or 3),
        "plafond_fond": int(getattr(settings, "llm_simultanes_fond", 2) or 2),
        "attente_max_s": int(getattr(settings, "llm_attente_max_s", 90) or 90),
        "portes_personnes": len(_PAR_PERSONNE),
    }
