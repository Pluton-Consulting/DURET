"""
Registre des skills — UNE déclaration par skill, dans son module.

POURQUOI. Un skill se déclarait à QUATRE endroits : sa fonction dans son module,
son relais et son effet dans `mail/skills.py`, sa description dans
`skills/protocol.py`, son libellé d'écran dans `agents/journal.py`. Quatre
fichiers à modifier pour un outil, quatre occasions d'en oublier un — et l'oubli
le plus sournois ne casse rien : un effet non déclaré verrouille l'action en
« externe », un libellé absent laisse l'écran muet, une description manquante
rend l'action invisible au modèle.

Surtout, cette dispersion rendait le projet IMPOSSIBLE À DUPLIQUER proprement :
adapter l'assistant à une autre entreprise demandait de retoucher le cœur.
Désormais, un module de skills déclare TOUT dans un dictionnaire `SKILLS`, et le
cœur (exécuteur, catalogue, journal) vient lire ici. Dupliquer le projet =
remplacer les dossiers `skills/` et `outils/`, rien d'autre.

CE QUI RESTE HORS REGISTRE. Les skills du socle commun aux projets (mails,
recherche, consignes, données, droits, enrichissement) restent déclarés à
l'ancienne dans `mail/skills.py` et `protocol.py` : ils sont identiques d'un
projet à l'autre et n'ont pas à bouger lors d'une duplication. Le registre
porte ce qui CHANGE d'un projet à l'autre.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("duret.skills.registre")


@dataclass(frozen=True)
class Declaration:
    """Tout ce que le système doit savoir d'un skill, en un seul endroit."""
    fonction: Callable[[dict, object], Awaitable[dict]]
    description: str                       # pour le catalogue montré au modèle
    requis: list[str] = field(default_factory=list)
    optionnels: list[str] = field(default_factory=list)
    # lecture | ecriture_interne | externe. FAIL-CLOSED : « externe » impose la
    # validation humaine — c'est le défaut de l'exécuteur pour tout skill
    # inconnu, on le reprend ici pour qu'un oubli verrouille au lieu d'ouvrir.
    effet: str = "externe"
    libelle: str = ""                      # « je … », affiché à l'écran
    # L'EXPERT D'ÉCRAN À CRÉDITER quand ce skill travaille (« agent2 »…). Le
    # graphe exécute presque tout dans agent1 : sans cette donnée, chaque tour
    # était attribué à l'expert par défaut, la carte des autres experts restait
    # à zéro et leur historique vide — alors que le travail, lui, était fait.
    # Vide = pas d'avis : l'orientation du tour (classify) reste valable.
    expert: str = ""


_CACHE: Optional[dict[str, Declaration]] = None


def collecte(rafraichir: bool = False) -> dict[str, Declaration]:
    """Toutes les déclarations des modules de `skills/`.

    Un module participe en exposant un dictionnaire `SKILLS`. La découverte est
    automatique : déposer un fichier suffit, aucun import à ajouter au cœur —
    c'est précisément ce qui rend la duplication triviale.

    Un module qui refuse de s'importer est IGNORÉ avec un avertissement : un
    outil cassé ne doit pas priver l'assistant de tous les autres.
    """
    global _CACHE
    if _CACHE is not None and not rafraichir:
        return _CACHE

    import skills as paquet

    # L'infrastructure du paquet n'a pas de déclarations et importe la base de
    # données dès le chargement : la parcourir coûterait un import lourd pour
    # rien, et un avertissement trompeur là où elle manque (environnement de
    # contrôle sans asyncpg).
    INFRASTRUCTURE = {"registre", "executor", "protocol", "markdown", "erreurs"}

    declarations: dict[str, Declaration] = {}
    for info in pkgutil.iter_modules(paquet.__path__):
        if info.name.startswith("_") or info.name in INFRASTRUCTURE:
            continue
        try:
            module = importlib.import_module(f"skills.{info.name}")
        except Exception as e:  # noqa: BLE001 - un module cassé n'éteint pas le reste
            logger.warning("Module de skills « %s » inimportable : %s", info.name, e)
            continue
        brut = getattr(module, "SKILLS", None)
        if not isinstance(brut, dict):
            continue
        for nom, decl in brut.items():
            if not isinstance(decl, Declaration):
                logger.warning("skills.%s : « %s » n'est pas une Declaration, ignoré",
                               info.name, nom)
                continue
            if nom in declarations:
                # Deux modules qui déclarent le même nom : c'est un conflit à
                # résoudre par un humain, pas par un ordre d'import silencieux.
                logger.error("Skill « %s » déclaré deux fois — seconde déclaration "
                             "ignorée (module %s)", nom, info.name)
                continue
            declarations[nom] = decl

    _CACHE = declarations
    logger.info("Registre des skills : %d déclaration(s)", len(declarations))
    return declarations


# ── Ce que chaque consommateur vient lire ────────────────────────────

def fonction(nom: str):
    """La fonction exécutable, ou None si le skill n'est pas au registre."""
    decl = collecte().get(nom)
    return decl.fonction if decl else None


def effet(nom: str) -> Optional[str]:
    """L'effet déclaré, ou None si inconnu du registre."""
    decl = collecte().get(nom)
    return decl.effet if decl else None


def libelle(nom: str) -> Optional[str]:
    """Le libellé d'écran, ou None si inconnu du registre."""
    decl = collecte().get(nom)
    return decl.libelle or None if decl else None


def expert(nom: str) -> Optional[str]:
    """L'expert d'écran crédité pour ce skill (« agent2 »…), ou None."""
    decl = collecte().get(nom)
    return (decl.expert or None) if decl else None


def catalogue_declare() -> dict[str, tuple[str, list[str], list[str]]]:
    """Les déclarations au format du catalogue de `protocol.py`."""
    return {nom: (d.description, list(d.requis), list(d.optionnels))
            for nom, d in collecte().items()}
