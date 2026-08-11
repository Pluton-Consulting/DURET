"""
Le type d'erreur des skills, et RIEN d'autre.

POURQUOI UN MODULE À PART. `SkillError` vivait dans `executor.py`, qui importe
la connexion à la base, le bac à sable et l'audit. Un skill qui voulait
seulement signaler « document inconnu » tirait donc toute cette chaîne — au
moment précis où quelque chose allait déjà mal.

Un chemin d'échec ne doit pas pouvoir échouer. Si l'un de ces imports venait à
manquer, le gestionnaire d'erreur lèverait une ImportError à la place de
l'erreur qu'il devait signaler, et la vraie cause serait perdue.

`executor` réexporte ce nom : `from skills.executor import SkillError` reste
valide partout où il était déjà écrit, et l'identité de la classe est unique —
un `except SkillError` continue d'attraper ce qu'il attrapait.
"""
from __future__ import annotations


class SkillError(Exception):
    """Un skill n'a pas pu faire ce qui lui était demandé.

    Levée AUSSI par les skills eux-mêmes, pas seulement par l'exécuteur : un
    échec rendu sous forme de dictionnaire (`{"message": "..."}`) passe pour une
    réussite partout en amont — `ok` vaut True, l'action s'affiche comme
    aboutie, et le modèle croit avoir fait ce qu'il n'a pas fait.
    """
