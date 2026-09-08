"""
RIEN NE SE SUPPRIME SANS LE MOT « SUPPRIMÉ » — règle de Noa du 08/09.

« Il ne doit jamais supprimer quoi que ce soit, à part si c'est dit
explicitement avec un mot "supprimé" dans le message envoyé. »

Le modèle choisit ses gestes d'après ce qu'il comprend ; une consigne
« oublie ça », « enlève cette tâche », « on laisse tomber » peut lui faire
appeler un geste qui EFFACE (une consigne retenue, une tâche programmée, une
trame). Le garde vit dans la boucle d'actions, pas dans le prompt : il lit le
MESSAGE DE LA PERSONNE, tel qu'elle l'a tapé, et refuse tout geste de
suppression tant que ce message ne porte pas le mot. Un skill inconnu dont le
nom commence par « supprimer_ », « oublier_ », « effacer_ » ou « retirer_ »
est traité comme une suppression : fail-closed, comme les effets.

Ce qui n'est PAS une suppression : abandonner un brouillon de document en
cours (`abandonner_document`, rien d'enregistré n'est perdu), fermer une
carte, annuler une action en attente d'accord.
"""
from __future__ import annotations

import unicodedata

SKILLS_QUI_SUPPRIMENT = frozenset({"oublier", "supprimer_tache", "oublier_trame"})
PREFIXES_DE_SUPPRESSION = ("supprimer_", "oublier_", "effacer_", "retirer_")
MOTS_QUI_AUTORISENT = ("supprim", "suppress")   # supprime, supprimé, supprimer / suppression


def _nu(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte or "")
                   if unicodedata.category(c) != "Mn").lower()


def est_une_suppression(skill: str) -> bool:
    nom = (skill or "").strip().lower()
    return nom in SKILLS_QUI_SUPPRIMENT or nom.startswith(PREFIXES_DE_SUPPRESSION)


def autorise_la_suppression(message: str) -> bool:
    """Vrai si LA PERSONNE a écrit le mot (supprime, supprimé, supprimer,
    suppression) dans son message. Pas « efface », pas « enlève », pas
    « oublie » : c'est le mot que Noa a nommé, et un seul mot est une règle
    qu'on peut expliquer."""
    nu = _nu(message)
    return any(m in nu for m in MOTS_QUI_AUTORISENT)


def raison_du_refus(skill: str) -> str:
    """Ce que la boucle d'actions rend au modèle à la place du résultat."""
    return (f"REFUSÉ : « {skill} » SUPPRIME quelque chose, et le message de la personne "
            "ne porte pas le mot « supprime » (ou « supprimé », « suppression »). Rien ne "
            "se supprime sans ce mot écrit par la personne elle-même. Ne réessaie pas ce "
            "geste dans ce tour : dis en une phrase ce qui serait supprimé et qu'il faut "
            "le redemander avec le mot « supprime » pour que ce soit fait.")
