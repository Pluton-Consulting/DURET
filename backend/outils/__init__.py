"""
Bibliothèque d'outils — un dossier par outil, des fonctions par cas d'usage.

POURQUOI. Le coût d'une demande n'est pas le travail, c'est la CONVERSATION.
Mesuré sur 32 tours réels : 57 % du temps part en allers-retours avec le modèle,
14 % seulement dans les outils eux-mêmes. Une demande enchaînant plusieurs
gestes prend 6,7 allers-retours et cent secondes — pour un PDF d'une ligne, on a
relevé 9 allers-retours et 132 secondes, dont 86 d'attente du modèle.

Chaque fonction d'ici réunit une chaîne complète en UN seul appel. Le gain est
double : les allers-retours disparaissent, et la chaîne ne peut plus être ratée
puisqu'elle est écrite une fois, pas rejouée de mémoire à chaque demande.

CE QUI N'ENTRE PAS ICI. Une fonction par cas imaginable. Le catalogue est
injecté dans CHAQUE prompt — 46 % du prompt système mesuré, 339 caractères par
entrée. Le multiplier ralentirait tous les tours, y compris « bonjour », et
rendrait le choix plus difficile : or les tours qui échouaient échouaient sur le
CHOIX de l'action, jamais sur son exécution. On compose, on ne multiplie pas.

D'OÙ LA DESCRIPTION COURTE. Chaque fonction se présente en une ligne. Le mode
d'emploi complet d'un outil — conventions de chemin, vocabulaire maison, limites
— vit dans `docs/<outil>.md` et n'est chargé QUE si on le demande, par l'action
`mode_emploi`. C'est ce qui permet d'improviser quand aucune fonction de la
bibliothèque ne convient, sans faire porter ce texte à tous les tours.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("duret.outils")

DOSSIER_DOCS = Path(__file__).parent / "docs"

# nom de l'outil -> (libellé pour l'écran, module des fonctions composées)
OUTILS: dict[str, tuple[str, str]] = {
    "nas": ("Serveur de fichiers (NAS Synology)", "outils.nas"),
    "documents": ("Documents téléchargeables (PDF, Word, Excel)", "outils.documents"),
}


def outils_disponibles() -> list[tuple[str, str]]:
    """(nom, libellé) de chaque outil, pour l'annoncer au modèle en une ligne."""
    return [(nom, libelle) for nom, (libelle, _) in OUTILS.items()]


def mode_emploi(outil: str) -> str:
    """Le mode d'emploi complet d'un outil, ou un message qui dit quoi faire.

    Servi À LA DEMANDE et jamais injecté : c'est tout l'intérêt: le texte long
    reste disponible sans peser sur chaque tour.
    """
    nom = (outil or "").strip().lower()
    if nom not in OUTILS:
        connus = ", ".join(OUTILS)
        return (f"Outil « {outil} » inconnu. Outils documentés : {connus}.")

    fichier = DOSSIER_DOCS / f"{nom}.md"
    try:
        return fichier.read_text(encoding="utf-8")
    except OSError as e:  # noqa: BLE001 - un mode d'emploi manquant n'est pas une panne
        logger.warning("Mode d'emploi de %s illisible : %s", nom, e)
        return (f"Le mode d'emploi de « {nom} » est indisponible. "
                "Sers-toi des fonctions de la bibliothèque, elles couvrent "
                "les cas courants.")
