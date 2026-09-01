"""
CE QU'UN TOUR A CONSOMMÉ — jetons et euros, mesurés là où tout passe.

POURQUOI CE MODULE (01/09). Le tableau de bord promettait « ce que ça coûte » et
affichait 0,00 € depuis toujours. La cause n'était pas un affichage : personne
n'écrivait jamais `cost_eur`, et `tokens_in`/`tokens_out` n'étaient renseignés
que par la VISION — c'est-à-dire par le chemin le moins emprunté. Les colonnes
« Jetons » et « Coût » du pilotage étaient donc fausses par construction, et
elles l'étaient d'autant plus qu'on regardait le chemin principal.

OÙ COMPTER. Pas dans les nœuds du graphe : il y en a une vingtaine, chacun
appelle le modèle à sa façon, et il en naît de nouveaux. Le seul endroit que
TOUS les appels traversent est `ResilientLLM.ainvoke` (llm/router.py) — un tour
peut y passer quinze fois, et c'est justement ce qu'on veut additionner.

COMMENT REMONTER LE TOTAL. Un `ContextVar`, comme `llm/concurrence.py` le fait
déjà pour l'identité : le routeur LLM ne connaît pas l'état LangGraph, et le lui
faire connaître le coupleraient au graphe pour un compteur. `runtime` ouvre le
compteur au début du tour, le lit à la fin, et le pose dans l'état.

LE COÛT EST UNE ESTIMATION, ET L'ÉCRAN LE DIT. Les tarifs bougent, les
fournisseurs facturent parfois au cache ou à la seconde, et un modèle inconnu
retombe sur un tarif moyen. Ce chiffre sert à voir un ORDRE DE GRANDEUR et une
tendance — « est-ce que ça dérape ce mois-ci » — pas à établir une facture. Un
zéro permanent ne disait rien du tout ; une estimation dit quelque chose.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any, Optional

logger = logging.getLogger("duret.llm.compteur")

# {entree, sortie, euros} pour le tour en cours. `None` hors d'un tour : on ne
# compte pas ce qui n'a pas été ouvert (une campagne de fond, une sonde).
_TOUR: ContextVar[Optional[dict]] = ContextVar("llm_compteur", default=None)

# €/million de jetons, (entrée, sortie). Ordres de grandeur publics de
# septembre 2026, arrondis : ils servent à situer, pas à facturer. Un modèle
# absent de la table prend le tarif par défaut.
TARIFS: dict = {
    "ollama_cloud": (0.15, 0.60),
    "deepseek": (0.25, 1.00),
    "longcat": (0.20, 0.80),
    "google": (0.10, 0.40),
    "groq": (0.15, 0.60),
    "openrouter": (0.50, 1.50),
    "anthropic": (2.50, 10.00),
    "ollama": (0.0, 0.0),          # local : la machine est déjà payée
}
TARIF_DEFAUT = (0.50, 1.50)


def demarrer() -> None:
    """Ouvre un compteur pour ce tour. Appelé par `runtime` avant le graphe."""
    _TOUR.set({"entree": 0, "sortie": 0, "euros": 0.0, "modeles": []})


def _usage(reponse: Any) -> tuple:
    """(entrée, sortie) d'une réponse LangChain, quelle qu'en soit la forme.

    Les fournisseurs ne s'accordent pas : les uns remplissent `usage_metadata`,
    les autres `response_metadata["token_usage"]`, d'autres encore rien du tout.
    On lit ce qu'on trouve, et zéro plutôt qu'une exception : un compteur ne
    doit jamais faire échouer le tour qu'il mesure.
    """
    try:
        u = getattr(reponse, "usage_metadata", None)
        if isinstance(u, dict) and (u.get("input_tokens") or u.get("output_tokens")):
            return int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0)
        meta = getattr(reponse, "response_metadata", None) or {}
        tu = meta.get("token_usage") or meta.get("usage") or {}
        entree = tu.get("prompt_tokens") or tu.get("input_tokens") or 0
        sortie = tu.get("completion_tokens") or tu.get("output_tokens") or 0
        return int(entree or 0), int(sortie or 0)
    except Exception:  # noqa: BLE001 — un compteur ne casse rien
        return 0, 0


def ajouter(fournisseur: str, modele: str, reponse: Any) -> None:
    """Ajoute la consommation d'UN appel. Ne lève jamais."""
    tour = _TOUR.get()
    if tour is None:
        return
    entree, sortie = _usage(reponse)
    if not entree and not sortie:
        return
    tarif_e, tarif_s = TARIFS.get((fournisseur or "").lower(), TARIF_DEFAUT)
    tour["entree"] += entree
    tour["sortie"] += sortie
    tour["euros"] += (entree * tarif_e + sortie * tarif_s) / 1_000_000
    if modele and modele not in tour["modeles"]:
        tour["modeles"].append(modele)


def bilan() -> dict:
    """Ce que le tour a consommé. Zéro si aucun compteur n'a été ouvert."""
    tour = _TOUR.get()
    if tour is None:
        return {"tokens_in": 0, "tokens_out": 0, "cost_eur": 0.0, "modele": None}
    return {
        "tokens_in": int(tour["entree"]),
        "tokens_out": int(tour["sortie"]),
        # Six décimales : la colonne de la base en porte six, et un tour coûte
        # souvent moins d'un centime — arrondir au centime rendrait zéro.
        "cost_eur": round(float(tour["euros"]), 6),
        # LE MODÈLE QUI A RÉPONDU, et pas celui qu'on espérait : un tour qui
        # bascule sur un secours doit le dire, sinon le journal impute la
        # consommation au mauvais fournisseur.
        "modele": tour["modeles"][-1] if tour["modeles"] else None,
    }
